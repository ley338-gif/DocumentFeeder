from pathlib import Path

from fastapi.testclient import TestClient

import document_core.api as api_module
from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore


def configure_auth_api(tmp_path: Path, monkeypatch) -> None:
    settings = Settings(
        data_dir=tmp_path,
        auth_enabled=True,
        bootstrap_admin_username="admin",
        bootstrap_admin_password="secure-test-password",
    )
    settings.create_directories()
    store = JobStore("sqlite://")
    monkeypatch.setattr(api_module, "settings", settings)
    monkeypatch.setattr(api_module, "store", store)
    monkeypatch.setattr(
        api_module,
        "pipeline",
        DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir)),
    )


def test_admin_can_login_and_manage_users(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as client:
        assert client.get("/v1/auth/me").status_code == 401
        login = client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "secure-test-password"},
        )
        created = client.post(
            "/v1/users",
            json={
                "username": "viewer",
                "display_name": "Lesender Benutzer",
                "role": "viewer",
                "password": "viewer-test-password",
            },
        )
        users = client.get("/v1/users")

    assert login.status_code == 200
    assert login.json()["role"] == "admin"
    assert "password_hash" not in login.json()
    assert created.status_code == 201
    assert len(users.json()) == 2


def test_viewer_has_read_only_access_and_no_user_management(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as admin:
        admin.post("/v1/auth/login", json={"username": "admin", "password": "secure-test-password"})
        admin.post(
            "/v1/users",
            json={"username": "viewer", "display_name": "Viewer", "role": "viewer", "password": "viewer-test-password"},
        )
    with TestClient(api_module.app) as viewer:
        assert viewer.post("/v1/auth/login", json={"username": "viewer", "password": "viewer-test-password"}).status_code == 200
        assert viewer.get("/v1/jobs").status_code == 200
        assert viewer.get("/v1/users").status_code == 403
        assert viewer.get("/v1/input-channels").status_code == 200
        channel_id = viewer.get("/v1/input-channels").json()[0]["id"]
        assert viewer.patch(
            f"/v1/input-channels/{channel_id}", json={"enabled": False}
        ).status_code == 403
        assert viewer.post("/v1/documents").status_code == 403
        profile = viewer.patch("/v1/auth/me", json={"display_name": "Neuer Name"})
        assert profile.status_code == 200
        assert profile.json()["display_name"] == "Neuer Name"
        assert viewer.post("/v1/auth/logout").status_code == 204
        assert viewer.get("/v1/auth/me").status_code == 401

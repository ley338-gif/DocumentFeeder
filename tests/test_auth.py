from pathlib import Path

from fastapi.testclient import TestClient

import document_core.api as api_module
from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore


def enable_csrf(client: TestClient) -> None:
    client.headers["X-CSRF-Token"] = client.cookies.get("document_core_csrf")


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
        enable_csrf(client)
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
        audit = client.get("/v1/audit-events")
        api_module.store.heartbeat_worker("test-worker")
        system = client.get("/v1/system-status")
        scanner_control = client.post(
            "/v1/system-status/malware-scanner", json={"enabled": False}
        )

    assert login.status_code == 200
    assert login.json()["role"] == "admin"
    assert "password_hash" not in login.json()
    assert created.status_code == 201
    assert len(users.json()) == 2
    assert audit.status_code == 200
    assert {item["action"] for item in audit.json()["items"]} >= {
        "LOGIN",
        "POST /v1/users",
    }
    assert system.status_code == 200
    assert system.json()["status"] == "ok"
    assert system.json()["schema_version"] == "unbekannt"
    assert system.json()["workers"][0]["worker_id"] == "test-worker"
    assert scanner_control.status_code == 200
    assert scanner_control.json() == {"enabled": False, "status": "paused"}


def test_viewer_has_read_only_access_and_no_user_management(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as admin:
        admin.post("/v1/auth/login", json={"username": "admin", "password": "secure-test-password"})
        enable_csrf(admin)
        admin.post(
            "/v1/users",
            json={"username": "viewer", "display_name": "Viewer", "role": "viewer", "password": "viewer-test-password"},
        )
    with TestClient(api_module.app) as viewer:
        assert viewer.post("/v1/auth/login", json={"username": "viewer", "password": "viewer-test-password"}).status_code == 200
        enable_csrf(viewer)
        assert viewer.get("/v1/jobs").status_code == 200
        assert viewer.get("/v1/users").status_code == 403
        assert viewer.get("/v1/system-status").status_code == 403
        assert viewer.post(
            "/v1/system-status/malware-scanner", json={"enabled": False}
        ).status_code == 403
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


def test_failed_login_is_audited_without_password(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as client:
        failed = client.post(
            "/v1/auth/login", json={"username": "admin", "password": "wrong-password"}
        )
        client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "secure-test-password"},
        )
        enable_csrf(client)
        audit = client.get("/v1/audit-events").json()["items"]

    assert failed.status_code == 401
    failure = next(item for item in audit if item["outcome"] == "failure")
    assert failure["action"] == "LOGIN"
    assert "password" not in str(failure["details"]).lower()


def test_write_request_without_csrf_token_is_rejected(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as client:
        client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "secure-test-password"},
        )
        response = client.post(
            "/v1/users",
            json={
                "username": "blocked",
                "display_name": "Blocked",
                "role": "viewer",
                "password": "blocked-test-password",
            },
        )

    assert response.status_code == 403
    assert response.json()["detail"] == "Ungültiger CSRF-Schutz"


def test_password_change_revokes_existing_session(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as client:
        client.post(
            "/v1/auth/login",
            json={"username": "admin", "password": "secure-test-password"},
        )
        enable_csrf(client)
        changed = client.patch(
            "/v1/auth/me", json={"password": "new-secure-test-password"}
        )
        current = client.get("/v1/auth/me")

    assert changed.status_code == 200
    assert current.status_code == 401


def test_repeated_failed_logins_are_rate_limited(tmp_path: Path, monkeypatch):
    configure_auth_api(tmp_path, monkeypatch)
    with TestClient(api_module.app) as client:
        for _ in range(api_module.settings.login_max_attempts):
            assert client.post(
                "/v1/auth/login",
                json={"username": "unknown", "password": "wrong-password"},
            ).status_code == 401
        limited = client.post(
            "/v1/auth/login",
            json={"username": "unknown", "password": "wrong-password"},
        )

    assert limited.status_code == 429

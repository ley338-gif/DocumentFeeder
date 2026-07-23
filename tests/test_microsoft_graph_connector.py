import io
import json
from pathlib import Path

from document_core.connectors import MicrosoftGraphConnector
from document_core.models import DocumentJob, TargetSystem


class Response:
    def __init__(self, payload: dict, status: int = 200):
        self.body = io.BytesIO(json.dumps(payload).encode())
        self.status = status
        self.headers = {"Content-Type": "application/json"}

    def read(self, size: int = -1) -> bytes:
        return self.body.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None


def target() -> TargetSystem:
    return TargetSystem(
        name="SharePoint",
        kind="microsoft_graph",
        graph_tenant_id="tenant",
        graph_client_id="client",
        graph_client_secret="secret",
        graph_drive_id="drive id",
        graph_folder="Eingang/Rechnungen",
    )


def job(tmp_path: Path) -> DocumentJob:
    document = tmp_path / "rechnung.pdf"
    document.write_bytes(b"PDF")
    return DocumentJob(
        id="job-123",
        source="api",
        original_filename="Rechnung Juli.pdf",
        stored_path=document,
        sha256="abc",
        document_type="invoice",
    )


def test_graph_connector_authenticates_and_uploads(tmp_path, monkeypatch):
    requests = []
    responses = iter(
        [
            Response({"access_token": "access-token"}),
            Response(
                {
                    "id": "item-42",
                    "name": "job-123_Rechnung Juli.pdf",
                    "webUrl": "https://example.invalid/item-42",
                },
                status=201,
            ),
        ]
    )

    def urlopen(request, timeout):
        requests.append((request, timeout))
        if request.method == "PUT":
            assert request.data.read() == b"PDF"
        return next(responses)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    receipt = MicrosoftGraphConnector(target()).deliver(job(tmp_path))

    token_request, upload_request = (item[0] for item in requests)
    assert token_request.full_url.endswith("/tenant/oauth2/v2.0/token")
    assert b"client_secret=secret" in token_request.data
    assert upload_request.method == "PUT"
    assert "/drives/drive%20id/root:/Eingang/Rechnungen/job-123_Rechnung%20Juli.pdf:/content" in (
        upload_request.full_url
    )
    assert upload_request.headers["Authorization"] == "Bearer access-token"
    assert receipt.reference == "item-42"
    assert receipt.connector == "microsoft_graph"
    assert receipt.details["path"] == "Eingang/Rechnungen/job-123_Rechnung Juli.pdf"


def test_graph_healthcheck_checks_drive(monkeypatch):
    requests = []
    responses = iter([Response({"access_token": "token"}), Response({"id": "drive id"})])

    def urlopen(request, timeout):
        requests.append(request)
        return next(responses)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    assert MicrosoftGraphConnector(target()).healthcheck() is True
    assert requests[-1].method == "GET"
    assert requests[-1].full_url.endswith("/drives/drive%20id")


def test_graph_uses_upload_session_for_large_files(tmp_path, monkeypatch):
    connector = MicrosoftGraphConnector(target())
    document_job = job(tmp_path)
    connector.max_simple_upload_bytes = 2
    requests = []
    responses = iter(
        [
            Response({"access_token": "token"}),
            Response({"uploadUrl": "https://upload.invalid/session"}),
            Response({"id": "large-item", "name": "large.pdf"}, status=201),
        ]
    )

    def urlopen(request, timeout):
        requests.append(request)
        return next(responses)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    receipt = connector.deliver(document_job)

    assert [request.method for request in requests] == ["POST", "POST", "PUT"]
    assert requests[1].full_url.endswith(":/createUploadSession")
    assert requests[2].headers["Content-range"] == "bytes 0-2/3"
    assert "Authorization" not in requests[2].headers
    assert receipt.reference == "large-item"

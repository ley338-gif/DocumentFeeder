import pytest


@pytest.fixture(autouse=True)
def isolate_local_malware_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's .env from turning unit tests into infrastructure tests."""
    monkeypatch.setenv("DOCUMENT_CORE_MALWARE_SCANNER", "disabled")

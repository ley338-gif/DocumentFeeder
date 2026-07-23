from pathlib import Path

import pytest

from document_core.config import Settings
from document_core.connector_registry import ConnectorModule, ConnectorRegistry
from document_core.connectors import FilesystemConnector
from document_core.licensing import EntitlementRequiredError, EntitlementService
from document_core.models import TargetSystem


def module(tmp_path: Path) -> ConnectorModule:
    return ConnectorModule(
        id="premium",
        name="Premium Connector",
        version="1.0",
        capabilities=("document",),
        license_feature="connector.premium",
        factory=lambda _target: FilesystemConnector(tmp_path),
    )


def test_registry_blocks_unlicensed_connector(tmp_path: Path):
    registry = ConnectorRegistry(EntitlementService())
    registry.register(module(tmp_path))

    with pytest.raises(EntitlementRequiredError, match="connector.premium"):
        registry.create(TargetSystem(name="Premium", kind="premium"))

    assert registry.describe()[0]["licensed"] is False


def test_registry_creates_licensed_connector(tmp_path: Path):
    registry = ConnectorRegistry(EntitlementService.from_csv("connector.premium"))
    registry.register(module(tmp_path))

    connector = registry.create(TargetSystem(name="Premium", kind="premium"))

    assert connector.healthcheck() is True


def test_default_registry_exposes_core_modules(tmp_path: Path):
    from document_core.connector_registry import create_default_connector_registry

    descriptions = create_default_connector_registry(Settings(data_dir=tmp_path)).describe()

    assert {item["id"] for item in descriptions} == {
        "filesystem",
        "http",
        "microsoft_graph",
    }
    by_id = {item["id"]: item for item in descriptions}
    assert by_id["filesystem"]["licensed"] is True
    assert by_id["http"]["licensed"] is True
    assert by_id["microsoft_graph"]["licensed"] is False
    assert by_id["microsoft_graph"]["license_feature"] == "connector.microsoft_graph"

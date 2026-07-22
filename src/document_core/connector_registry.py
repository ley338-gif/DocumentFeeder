from dataclasses import dataclass
from typing import Callable

from .config import Settings
from .connectors import FilesystemConnector, HttpConnector, TargetConnector
from .licensing import EntitlementService
from .models import TargetSystem


ConnectorFactory = Callable[[TargetSystem], TargetConnector]


@dataclass(frozen=True)
class ConnectorModule:
    id: str
    name: str
    version: str
    capabilities: tuple[str, ...]
    factory: ConnectorFactory
    license_feature: str | None = None
    configuration_fields: tuple[str, ...] = ()
    secret_fields: tuple[str, ...] = ()


class ConnectorRegistry:
    def __init__(self, entitlements: EntitlementService):
        self.entitlements = entitlements
        self._modules: dict[str, ConnectorModule] = {}

    def register(self, module: ConnectorModule) -> None:
        if module.id in self._modules:
            raise ValueError(f"Connector-Modul bereits registriert: {module.id}")
        self._modules[module.id] = module

    def get(self, module_id: str) -> ConnectorModule | None:
        return self._modules.get(module_id)

    def require_available(self, module_id: str) -> ConnectorModule:
        module = self.get(module_id)
        if module is None:
            raise ValueError(f"Connector-Modul nicht installiert: {module_id}")
        self.entitlements.require(module.license_feature)
        return module

    def create(self, target: TargetSystem) -> TargetConnector:
        return self.require_available(target.kind).factory(target)

    def describe(self) -> list[dict]:
        return [
            {
                "id": module.id,
                "name": module.name,
                "version": module.version,
                "capabilities": list(module.capabilities),
                "license_feature": module.license_feature,
                "licensed": self.entitlements.allows(module.license_feature),
                "configuration_fields": list(module.configuration_fields),
                "secret_fields": list(module.secret_fields),
            }
            for module in sorted(self._modules.values(), key=lambda item: item.name)
        ]


def create_default_connector_registry(settings: Settings) -> ConnectorRegistry:
    registry = ConnectorRegistry(EntitlementService.from_csv(settings.connector_entitlements))
    registry.register(ConnectorModule(
        id="filesystem",
        name="Dateisystem",
        version="1.0",
        capabilities=("document", "metadata", "folders", "idempotency"),
        configuration_fields=("directory", "path_template"),
        factory=lambda target: FilesystemConnector(
            settings.data_dir / target.directory, target.path_template
        ),
    ))
    registry.register(ConnectorModule(
        id="http",
        name="HTTP API",
        version="1.0",
        capabilities=("document", "metadata", "authentication", "idempotency"),
        configuration_fields=("endpoint_url", "timeout_seconds"),
        secret_fields=("bearer_token",),
        factory=HttpConnector,
    ))
    return registry

from dataclasses import dataclass
from typing import Callable

from .config import Settings
from .connectors import (
    FilesystemConnector,
    HttpConnector,
    MicrosoftGraphConnector,
    TargetConnector,
)
from .licensing import EntitlementService, LicenseValidationError, LicenseVerifier
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


def create_default_connector_registry(
    settings: Settings,
    license_key_provider: Callable[[], tuple[str | None, str]] | None = None,
) -> ConnectorRegistry:
    dynamic_features = None
    if license_key_provider is not None:
        verifier = LicenseVerifier(settings.license_public_key)

        def licensed_features() -> frozenset[str]:
            license_key, installation_id = license_key_provider()
            if not license_key:
                return frozenset()
            try:
                return verifier.verify(license_key, installation_id).features
            except LicenseValidationError:
                return frozenset()

        dynamic_features = licensed_features
    static = EntitlementService.from_csv(settings.connector_entitlements)
    registry = ConnectorRegistry(
        EntitlementService(static.enabled_features, dynamic_features)
    )
    registry.register(ConnectorModule(
        id="filesystem",
        name="Dateisystem",
        version="1.0",
        capabilities=("document", "metadata", "folders", "idempotency"),
        configuration_fields=("directory", "path_template"),
        factory=lambda target: FilesystemConnector(
            settings.destination_root / target.directory, target.path_template
        ),
    ))
    registry.register(ConnectorModule(
        id="http",
        name="HTTP API",
        version="1.0",
        capabilities=("document", "metadata", "authentication", "idempotency"),
        configuration_fields=(
            "endpoint_url", "healthcheck_url", "timeout_seconds", "max_response_bytes"
        ),
        secret_fields=("bearer_token",),
        factory=HttpConnector,
    ))
    registry.register(ConnectorModule(
        id="microsoft_graph",
        name="Microsoft OneDrive / SharePoint",
        version="1.0",
        capabilities=(
            "document",
            "folders",
            "authentication",
            "idempotency",
            "healthcheck",
        ),
        license_feature="connector.microsoft_graph",
        configuration_fields=(
            "graph_tenant_id",
            "graph_client_id",
            "graph_drive_id",
            "graph_folder",
            "timeout_seconds",
            "max_response_bytes",
        ),
        secret_fields=("graph_client_secret",),
        factory=MicrosoftGraphConnector,
    ))
    return registry

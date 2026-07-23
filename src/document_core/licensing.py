import base64
import json
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


class EntitlementRequiredError(RuntimeError):
    pass


@dataclass(frozen=True)
class EntitlementService:
    enabled_features: frozenset[str] = frozenset()
    dynamic_features: Callable[[], frozenset[str]] | None = None

    @classmethod
    def from_csv(cls, value: str) -> "EntitlementService":
        return cls(frozenset(item.strip() for item in value.split(",") if item.strip()))

    def allows(self, feature: str | None) -> bool:
        current = self.enabled_features
        if self.dynamic_features is not None:
            current = current | self.dynamic_features()
        return feature is None or feature in current

    def require(self, feature: str | None) -> None:
        if not self.allows(feature):
            raise EntitlementRequiredError(f"Lizenzmerkmal nicht aktiviert: {feature}")


class LicenseValidationError(ValueError):
    pass


def _decode(value: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (ValueError, TypeError) as exc:
        raise LicenseValidationError("Lizenzschlüssel ist nicht korrekt kodiert") from exc


@dataclass(frozen=True)
class VerifiedLicense:
    customer: str
    features: frozenset[str]
    expires_at: datetime
    installation_id: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "customer": self.customer,
            "features": sorted(self.features),
            "expires_at": self.expires_at.isoformat(),
            "installation_id": self.installation_id,
        }


class LicenseVerifier:
    def __init__(self, public_key: str):
        self.public_key = public_key.strip()

    @property
    def configured(self) -> bool:
        return bool(self.public_key)

    def verify(self, license_key: str, installation_id: str) -> VerifiedLicense:
        if not self.configured:
            raise LicenseValidationError("Lizenzprüfung ist auf diesem System nicht konfiguriert")
        parts = license_key.strip().split(".")
        if len(parts) != 3 or parts[0] != "DC1":
            raise LicenseValidationError("Lizenzschlüssel hat ein unbekanntes Format")
        payload_bytes = _decode(parts[1])
        signature = _decode(parts[2])
        try:
            public_key = Ed25519PublicKey.from_public_bytes(_decode(self.public_key))
            public_key.verify(signature, f"DC1.{parts[1]}".encode("ascii"))
        except (InvalidSignature, ValueError) as exc:
            raise LicenseValidationError("Signatur des Lizenzschlüssels ist ungültig") from exc
        try:
            payload = json.loads(payload_bytes)
            customer = str(payload["customer"]).strip()
            features = frozenset(str(item).strip() for item in payload["features"] if item)
            expires_at = datetime.fromisoformat(str(payload["expires_at"]).replace("Z", "+00:00"))
            bound_installation = payload.get("installation_id")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise LicenseValidationError("Lizenzinhalt ist unvollständig") from exc
        if not customer or not features:
            raise LicenseValidationError("Kunde und mindestens ein Modul sind erforderlich")
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=UTC)
        if expires_at <= datetime.now(UTC):
            raise LicenseValidationError("Lizenz ist abgelaufen")
        if bound_installation and bound_installation != installation_id:
            raise LicenseValidationError("Lizenz gehört zu einer anderen Installation")
        return VerifiedLicense(customer, features, expires_at, bound_installation)

import base64
import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from document_core.licensing import LicenseValidationError, LicenseVerifier


def encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def license_data(
    *,
    installation_id: str | None = "installation-1",
    expires_at: datetime | None = None,
) -> tuple[str, str]:
    private_key = Ed25519PrivateKey.generate()
    public_key = encode(
        private_key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
    )
    payload = encode(
        json.dumps(
            {
                "customer": "Beispiel GmbH",
                "features": ["connector.microsoft_graph"],
                "expires_at": (
                    expires_at or datetime.now(UTC) + timedelta(days=30)
                ).isoformat(),
                "installation_id": installation_id,
            },
            separators=(",", ":"),
        ).encode()
    )
    signed = f"DC1.{payload}"
    return f"{signed}.{encode(private_key.sign(signed.encode()))}", public_key


def test_signed_license_is_verified():
    license_key, public_key = license_data()

    result = LicenseVerifier(public_key).verify(license_key, "installation-1")

    assert result.customer == "Beispiel GmbH"
    assert result.features == {"connector.microsoft_graph"}


def test_modified_license_is_rejected():
    license_key, public_key = license_data()
    prefix, payload, signature = license_key.split(".")
    replacement = "A" if payload[-1] != "A" else "B"
    modified = f"{prefix}.{payload[:-1]}{replacement}.{signature}"

    with pytest.raises(LicenseValidationError, match="Signatur"):
        LicenseVerifier(public_key).verify(modified, "installation-1")


def test_license_is_bound_to_installation():
    license_key, public_key = license_data()

    with pytest.raises(LicenseValidationError, match="anderen Installation"):
        LicenseVerifier(public_key).verify(license_key, "installation-2")


def test_expired_license_is_rejected():
    license_key, public_key = license_data(
        expires_at=datetime.now(UTC) - timedelta(days=1)
    )

    with pytest.raises(LicenseValidationError, match="abgelaufen"):
        LicenseVerifier(public_key).verify(license_key, "installation-1")

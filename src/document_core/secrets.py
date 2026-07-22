from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


ENCRYPTED_PREFIX = "enc:v1:"
REDACTED = "[REDACTED]"


class SecretConfigurationError(RuntimeError):
    pass


class SecretCipher:
    def __init__(self, keys: list[str] | None = None):
        try:
            self._fernets = [Fernet(key.encode("ascii")) for key in (keys or [])]
        except (ValueError, TypeError) as exc:
            raise SecretConfigurationError("Ungültiger Schlüssel für Connector-Secrets") from exc
        self._primary = self._fernets[0] if self._fernets else None
        self._cipher = MultiFernet(self._fernets) if self._fernets else None
        self._known_plaintexts: set[str] = set()

    @classmethod
    def from_csv(cls, value: str) -> "SecretCipher":
        return cls([item.strip() for item in value.split(",") if item.strip()])

    @property
    def available(self) -> bool:
        return self._cipher is not None

    @staticmethod
    def is_encrypted(value: str) -> bool:
        return value.startswith(ENCRYPTED_PREFIX)

    def encrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not self._cipher:
            raise SecretConfigurationError(
                "Connector-Secret vorhanden, aber DOCUMENT_CORE_CONNECTOR_SECRET_KEYS fehlt"
            )
        self._known_plaintexts.add(value)
        return ENCRYPTED_PREFIX + self._cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not self.is_encrypted(value):
            raise SecretConfigurationError("Unverschlüsseltes Connector-Secret erkannt")
        if not self._cipher:
            raise SecretConfigurationError(
                "Verschlüsseltes Connector-Secret vorhanden, aber Schlüssel fehlt"
            )
        try:
            plaintext = self._cipher.decrypt(value.removeprefix(ENCRYPTED_PREFIX).encode("ascii"))
        except InvalidToken as exc:
            raise SecretConfigurationError(
                "Connector-Secret kann mit den konfigurierten Schlüsseln nicht entschlüsselt werden"
            ) from exc
        result = plaintext.decode("utf-8")
        self._known_plaintexts.add(result)
        return result

    def migrate_or_rotate(self, value: str) -> str:
        if not self._cipher:
            raise SecretConfigurationError(
                "Connector-Secret vorhanden, aber DOCUMENT_CORE_CONNECTOR_SECRET_KEYS fehlt"
            )
        if not self.is_encrypted(value):
            return self.encrypt(value) or ""
        payload = value.removeprefix(ENCRYPTED_PREFIX).encode("ascii")
        try:
            plaintext = self._primary.decrypt(payload) if self._primary else b""
            self._known_plaintexts.add(plaintext.decode("utf-8"))
            return value
        except InvalidToken as exc:
            try:
                plaintext = self._cipher.decrypt(payload)
                rotated = self._cipher.rotate(payload)
            except InvalidToken:
                raise SecretConfigurationError(
                    "Connector-Secret kann mit den konfigurierten Schlüsseln nicht rotiert werden"
                ) from exc
            self._known_plaintexts.add(plaintext.decode("utf-8"))
        return ENCRYPTED_PREFIX + rotated.decode("ascii")

    def redact(self, value: Any) -> Any:
        if isinstance(value, str):
            redacted = value
            for secret in sorted(self._known_plaintexts, key=len, reverse=True):
                if secret:
                    redacted = redacted.replace(secret, REDACTED)
            return redacted
        if isinstance(value, dict):
            return {key: self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        return value

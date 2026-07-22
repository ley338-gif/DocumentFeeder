from pathlib import Path

import pytest
from sqlalchemy import select, update

from document_core.models import AuditEvent, TargetSystem
from document_core.secrets import ENCRYPTED_PREFIX, REDACTED, SecretCipher, SecretConfigurationError
from document_core.store import AuditEventRow, JobStore, TargetSystemRow


OLD_KEY = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
NEW_KEY = "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBA="


def database_url(tmp_path: Path) -> str:
    return f"sqlite:///{tmp_path / 'secrets.db'}"


def raw_token(store: JobStore, target_id: str) -> str:
    with store.sessions() as session:
        return session.scalar(
            select(TargetSystemRow.bearer_token).where(TargetSystemRow.id == target_id)
        )


def test_target_secret_is_encrypted_at_rest(tmp_path: Path):
    store = JobStore(database_url(tmp_path), secret_cipher=SecretCipher([OLD_KEY]))
    target = TargetSystem(name="HTTP", kind="http", bearer_token="super-secret")

    store.save_target_system(target)

    persisted = raw_token(store, target.id)
    assert persisted.startswith(ENCRYPTED_PREFIX)
    assert "super-secret" not in persisted
    assert store.get_target_system(target.id).bearer_token == "super-secret"


def test_keys_are_rotated_on_store_start(tmp_path: Path):
    url = database_url(tmp_path)
    initial = JobStore(url, secret_cipher=SecretCipher([OLD_KEY]))
    target = TargetSystem(name="HTTP", kind="http", bearer_token="rotate-me")
    initial.save_target_system(target)
    before = raw_token(initial, target.id)

    rotated = JobStore(url, secret_cipher=SecretCipher([NEW_KEY, OLD_KEY]))
    after = raw_token(rotated, target.id)

    assert after != before
    assert JobStore(url, secret_cipher=SecretCipher([NEW_KEY])).get_target_system(
        target.id
    ).bearer_token == "rotate-me"


def test_existing_plaintext_requires_key_and_is_migrated(tmp_path: Path):
    url = database_url(tmp_path)
    seeded = JobStore(url, secret_cipher=SecretCipher([OLD_KEY]))
    target = TargetSystem(name="Legacy", kind="http")
    seeded.save_target_system(target)
    with seeded.sessions.begin() as session:
        session.execute(
            update(TargetSystemRow)
            .where(TargetSystemRow.id == target.id)
            .values(bearer_token="legacy-secret")
        )
        session.add(AuditEventRow(
            **AuditEvent(
                actor_username="legacy",
                action="TEST",
                resource_type="target",
                outcome="failure",
                status_code=500,
                details={"error": "legacy-secret was echoed"},
            ).model_dump()
        ))

    with pytest.raises(SecretConfigurationError, match="fehlt"):
        JobStore(url, secret_cipher=SecretCipher())

    migrated = JobStore(url, secret_cipher=SecretCipher([OLD_KEY]))
    assert raw_token(migrated, target.id).startswith(ENCRYPTED_PREFIX)
    assert migrated.get_target_system(target.id).bearer_token == "legacy-secret"
    assert migrated.list_audit_events()[0].details["error"] == f"{REDACTED} was echoed"


def test_known_secrets_are_redacted_from_audit_details(tmp_path: Path):
    store = JobStore(database_url(tmp_path), secret_cipher=SecretCipher([OLD_KEY]))
    store.save_target_system(
        TargetSystem(name="HTTP", kind="http", bearer_token="do-not-log")
    )

    store.save_audit_event(AuditEvent(
        actor_username="admin",
        action="TEST",
        resource_type="target",
        outcome="failure",
        status_code=500,
        details={"error": "remote echoed do-not-log"},
    ))

    assert store.list_audit_events()[0].details["error"] == f"remote echoed {REDACTED}"

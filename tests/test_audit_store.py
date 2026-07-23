from datetime import UTC, datetime, timedelta

from sqlalchemy import update

from document_core.models import AuditEvent
from document_core.store import AuditEventRow, JobStore


def event(index: int, created_at: datetime) -> AuditEvent:
    return AuditEvent(
        actor_username="admin" if index < 4 else "viewer",
        action=f"UPDATE_{index}",
        resource_type="target",
        resource_id=f"target-{index}",
        outcome="success" if index % 2 == 0 else "failure",
        status_code=200,
        created_at=created_at,
    )


def test_audit_search_and_pagination_are_applied_by_store():
    store = JobStore("sqlite://")
    now = datetime.now(UTC)
    for index in range(6):
        store.save_audit_event(event(index, now + timedelta(seconds=index)))

    first, total = store.search_audit_events(q="admin", limit=2, offset=0)
    second, _ = store.search_audit_events(q="admin", limit=2, offset=2)

    assert total == 4
    assert [item.action for item in first] == ["UPDATE_3", "UPDATE_2"]
    assert [item.action for item in second] == ["UPDATE_1", "UPDATE_0"]


def test_audit_retention_deletes_only_expired_events():
    store = JobStore("sqlite://")
    now = datetime.now(UTC)
    store.save_audit_event(event(1, now - timedelta(days=400)))
    store.save_audit_event(event(2, now - timedelta(days=20)))

    deleted = store.delete_audit_events_before(now - timedelta(days=365))

    assert deleted == 1
    assert [item.action for item in store.list_audit_events()] == ["UPDATE_2"]
    assert store.verify_audit_chain()["status"] == "ok"


def test_audit_hash_chain_detects_modified_entry():
    store = JobStore("sqlite://")
    now = datetime.now(UTC)
    store.save_audit_event(event(1, now))
    store.save_audit_event(event(2, now + timedelta(seconds=1)))
    assert store.verify_audit_chain()["status"] == "ok"

    with store.sessions.begin() as session:
        session.execute(
            update(AuditEventRow)
            .where(AuditEventRow.chain_index == 1)
            .values(details={"modified": True})
        )

    result = store.verify_audit_chain()
    assert result["status"] == "invalid"
    assert result["first_invalid_index"] == 1

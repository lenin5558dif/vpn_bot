import pytest
from sqlmodel import select

from app.audit import record_audit
from app.models import AuditLog


@pytest.mark.asyncio
async def test_record_audit(session):
    await record_audit(
        session,
        action="test_action",
        target_type="peer",
        target_id=1,
        actor_id=42,
        ip="127.0.0.1",
        meta={"key": "value"},
    )
    await session.commit()

    result = await session.exec(select(AuditLog))
    logs = result.all()
    assert len(logs) == 1
    assert logs[0].action == "test_action"
    assert logs[0].ip == "127.0.0.1"
    assert logs[0].meta == {"key": "value"}
    assert logs[0].actor_id == 42


@pytest.mark.asyncio
async def test_record_audit_minimal(session):
    await record_audit(session, action="minimal")
    await session.commit()

    result = await session.exec(select(AuditLog))
    logs = result.all()
    assert len(logs) == 1
    assert logs[0].target_type is None
    assert logs[0].ip is None

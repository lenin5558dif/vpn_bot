import pytest
from app.models import AuditLog


@pytest.mark.asyncio
async def test_list_audit_empty(client, admin_headers):
    resp = await client.get("/audit", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_list_audit_with_data(client, admin_headers, session):
    log = AuditLog(action="test_action", target_type="user", target_id=1)
    session.add(log)
    await session.commit()
    resp = await client.get("/audit", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["action"] == "test_action"


@pytest.mark.asyncio
async def test_list_audit_limit(client, admin_headers, session):
    for i in range(5):
        session.add(AuditLog(action=f"act{i}"))
    await session.commit()
    resp = await client.get("/audit?limit=2", headers=admin_headers)
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_audit_no_auth(client):
    resp = await client.get("/audit")
    assert resp.status_code == 401

import pytest


@pytest.mark.asyncio
async def test_login_success(client):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "testpass"})
    assert resp.status_code == 200
    data = resp.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"


@pytest.mark.asyncio
async def test_login_wrong_password(client):
    resp = await client.post("/auth/login", data={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_login_wrong_username(client):
    resp = await client.post("/auth/login", data={"username": "nobody", "password": "testpass"})
    assert resp.status_code == 401

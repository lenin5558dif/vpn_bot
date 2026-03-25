import pytest


@pytest.mark.asyncio
async def test_create_user(client, bot_headers):
    resp = await client.post("/users", json={"name": "Test User", "contact": "test@mail.com", "tg_id": 111}, headers=bot_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Test User"
    assert data["tg_id"] == 111
    assert data["role"] == "user"


@pytest.mark.asyncio
async def test_create_user_no_api_key(client):
    resp = await client.post("/users", json={"name": "Test"})
    assert resp.status_code == 422  # missing header


@pytest.mark.asyncio
async def test_create_user_wrong_api_key(client):
    resp = await client.post("/users", json={"name": "Test"}, headers={"X-Bot-Api-Key": "wrong"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_users(client, admin_headers, bot_headers):
    await client.post("/users", json={"name": "User1"}, headers=bot_headers)
    await client.post("/users", json={"name": "User2"}, headers=bot_headers)
    resp = await client.get("/users", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_users_pagination(client, admin_headers, bot_headers):
    for i in range(5):
        await client.post("/users", json={"name": f"User{i}"}, headers=bot_headers)
    resp = await client.get("/users?limit=2&offset=0", headers=admin_headers)
    assert len(resp.json()) == 2
    resp2 = await client.get("/users?limit=2&offset=2", headers=admin_headers)
    assert len(resp2.json()) == 2


@pytest.mark.asyncio
async def test_list_users_no_auth(client):
    resp = await client.get("/users")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_get_user(client, admin_headers, bot_headers):
    create = await client.post("/users", json={"name": "GetMe"}, headers=bot_headers)
    uid = create.json()["id"]
    resp = await client.get(f"/users/{uid}", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["name"] == "GetMe"


@pytest.mark.asyncio
async def test_get_user_not_found(client, admin_headers):
    resp = await client.get("/users/999", headers=admin_headers)
    assert resp.status_code == 404

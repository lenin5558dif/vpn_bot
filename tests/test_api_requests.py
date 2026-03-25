import pytest


@pytest.mark.asyncio
async def test_create_request(client, bot_headers):
    user = await client.post("/users", json={"name": "Req User"}, headers=bot_headers)
    uid = user.json()["id"]
    resp = await client.post("/requests", json={"user_id": uid, "comment": "please"}, headers=bot_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "new"
    assert data["comment"] == "please"


@pytest.mark.asyncio
async def test_create_request_no_api_key(client):
    resp = await client.post("/requests", json={"user_id": 1})
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_list_requests(client, admin_headers, bot_headers):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    await client.post("/requests", json={"user_id": uid}, headers=bot_headers)
    await client.post("/requests", json={"user_id": uid, "comment": "c"}, headers=bot_headers)
    resp = await client.get("/requests", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_requests_filter_status(client, admin_headers, bot_headers):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    await client.post("/requests", json={"user_id": uid}, headers=bot_headers)
    resp = await client.get("/requests?status=new", headers=admin_headers)
    assert len(resp.json()) == 1
    resp2 = await client.get("/requests?status=approved", headers=admin_headers)
    assert len(resp2.json()) == 0


@pytest.mark.asyncio
async def test_list_requests_pagination(client, admin_headers, bot_headers):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    for _ in range(5):
        await client.post("/requests", json={"user_id": uid}, headers=bot_headers)
    resp = await client.get("/requests?limit=2", headers=admin_headers)
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_update_request(client, admin_headers, bot_headers):
    user = await client.post("/users", json={"name": "U"}, headers=bot_headers)
    uid = user.json()["id"]
    req = await client.post("/requests", json={"user_id": uid}, headers=bot_headers)
    rid = req.json()["id"]
    resp = await client.patch(f"/requests/{rid}", json={"status": "approved"}, headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["status"] == "approved"


@pytest.mark.asyncio
async def test_update_request_not_found(client, admin_headers):
    resp = await client.patch("/requests/999", json={"status": "approved"}, headers=admin_headers)
    assert resp.status_code == 404

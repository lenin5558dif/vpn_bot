from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
import jwt

from app.config import get_settings
from app.schemas import RequestStatus


class BackendClient:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = self.settings.backend_url
        self.token: str | None = None
        self._lock = asyncio.Lock()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(10.0, connect=5.0),
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._client

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    def _bot_key_headers(self) -> dict[str, str]:
        key = self.settings.bot_api_key
        if key:
            return {"X-Bot-Api-Key": key}
        return {}

    def _is_token_valid(self, token: str) -> bool:
        try:
            payload = jwt.decode(
                token, self.settings.jwt_secret, algorithms=[self.settings.jwt_alg],
                issuer="vpn-admin-api", audience="vpn-admin",
            )
        except jwt.InvalidTokenError:
            return False
        exp_ts = payload.get("exp")
        if not exp_ts:
            return True
        expires_at = datetime.fromtimestamp(exp_ts, tz=timezone.utc)
        return expires_at - timedelta(minutes=1) > datetime.now(timezone.utc)

    async def _get_token(self) -> str:
        async with self._lock:
            if self.token and self._is_token_valid(self.token):
                return self.token
            client = await self._get_client()
            resp = await client.post(
                "/auth/login",
                data={"username": self.settings.admin_username, "password": self.settings.admin_password},
            )
            resp.raise_for_status()
            data = resp.json()
            self.token = data["access_token"]
            return self.token

    async def _headers(self) -> dict[str, str]:
        bot_headers = self._bot_key_headers()
        if bot_headers:
            return bot_headers
        token = await self._get_token()
        return {"Authorization": f"Bearer {token}"}

    async def _request_with_auth(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        client = await self._get_client()
        resp = await client.request(method, path, headers={**headers, **await self._headers()}, **kwargs)
        if resp.status_code == 401:
            self.token = None
            resp = await client.request(method, path, headers={**headers, **await self._headers()}, **kwargs)
        resp.raise_for_status()
        return resp

    async def create_user(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post("/users", json=payload, headers=self._bot_key_headers())
        resp.raise_for_status()
        return resp.json()

    async def create_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.post("/requests", json=payload, headers=self._bot_key_headers())
        resp.raise_for_status()
        return resp.json()

    async def update_request(self, request_id: int, status: RequestStatus) -> dict[str, Any]:
        resp = await self._request_with_auth(
            "PATCH", f"/requests/{request_id}", json={"status": status.value}
        )
        return resp.json()

    async def create_peer(self, user_id: int, speed_limit_mbps: int | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"user_id": user_id}
        if speed_limit_mbps is not None:
            payload["speed_limit_mbps"] = speed_limit_mbps
        resp = await self._request_with_auth("POST", "/peers", json=payload)
        return resp.json()

    async def get_user(self, user_id: int) -> dict[str, Any]:
        resp = await self._request_with_auth("GET", f"/users/{user_id}")
        return resp.json()

    async def get_config(self, peer_id: int) -> str:
        resp = await self._request_with_auth("GET", f"/peers/{peer_id}/config/file")
        return resp.text

    async def list_users(self) -> list[dict[str, Any]]:
        return await self._paginated_get("/users")

    async def admin_user_list(
        self,
        query: str | None = None,
        *,
        limit: int = 8,
        offset: int = 0,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if query:
            params["query"] = query
        resp = await self._request_with_auth("GET", "/users/admin/list", params=params)
        return resp.json()

    async def admin_user_card(self, user_id: int) -> dict[str, Any]:
        resp = await self._request_with_auth("GET", f"/users/{user_id}/admin-card")
        return resp.json()

    async def list_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if status:
            params["status"] = status
        return await self._paginated_get("/requests", params=params)

    async def list_peers(self, user_id: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, Any] = {}
        if user_id is not None:
            params["user_id"] = user_id
        return await self._paginated_get("/peers", params=params)

    async def update_peer_status(
        self,
        peer_id: int,
        status: str,
        speed_limit_mbps: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if speed_limit_mbps is not None:
            payload["speed_limit_mbps"] = speed_limit_mbps
        resp = await self._request_with_auth("PATCH", f"/peers/{peer_id}", json=payload)
        return resp.json()

    async def bulk_update_user_peers(
        self,
        user_id: int,
        status: str,
        speed_limit_mbps: int | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"status": status}
        if speed_limit_mbps is not None:
            payload["speed_limit_mbps"] = speed_limit_mbps
        resp = await self._request_with_auth("PATCH", f"/peers/user/{user_id}/status", json=payload)
        return resp.json()

    async def reconcile_peers(self) -> dict[str, Any]:
        resp = await self._request_with_auth("GET", "/peers/reconcile")
        return resp.json()

    async def health(self) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def get_traffic_summary(self, hours: int = 24) -> list[dict[str, Any]]:
        resp = await self._request_with_auth("GET", "/traffic/summary", params={"hours": hours})
        return resp.json()

    async def get_online_peers(self) -> dict[str, Any]:
        resp = await self._request_with_auth("GET", "/peers/online")
        data = resp.json()
        return data[0] if data else {"total": 0, "online_count": 0, "peers": []}

    async def get_server_stats(self) -> dict[str, Any]:
        resp = await self._request_with_auth("GET", "/stats/server")
        return resp.json()

    async def get_user_by_tg_id(self, tg_id: int) -> dict[str, Any] | None:
        resp = await self._request_with_auth("GET", "/users", params={"tg_id": tg_id, "limit": 1})
        users = resp.json()
        return users[0] if users else None

    async def get_requests_by_user_id(self, user_id: int) -> list[dict[str, Any]]:
        return await self._paginated_get("/requests", params={"user_id": user_id})

    async def _paginated_get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        page_size: int = 500,
    ) -> list[dict[str, Any]]:
        merged = dict(params or {})
        offset = 0
        items: list[dict[str, Any]] = []
        while True:
            resp = await self._request_with_auth(
                "GET",
                path,
                params={**merged, "limit": page_size, "offset": offset},
            )
            page = resp.json()
            items.extend(page)
            if len(page) < page_size:
                return items
            offset += page_size

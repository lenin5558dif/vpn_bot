from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from jose import JWTError, jwt

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
            payload = jwt.decode(token, self.settings.jwt_secret, algorithms=[self.settings.jwt_alg])
        except JWTError:
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

    async def create_peer(self, user_id: int) -> dict[str, Any]:
        resp = await self._request_with_auth("POST", "/peers", json={"user_id": user_id})
        return resp.json()

    async def get_user(self, user_id: int) -> dict[str, Any]:
        resp = await self._request_with_auth("GET", f"/users/{user_id}")
        return resp.json()

    async def get_config(self, peer_id: int) -> str:
        resp = await self._request_with_auth("GET", f"/peers/{peer_id}/config/file")
        return resp.text

    async def list_users(self) -> list[dict[str, Any]]:
        resp = await self._request_with_auth("GET", "/users")
        return resp.json()

    async def list_requests(self, status: str | None = None) -> list[dict[str, Any]]:
        params = {}
        if status:
            params["status"] = status
        resp = await self._request_with_auth("GET", "/requests", params=params)
        return resp.json()

    async def list_peers(self) -> list[dict[str, Any]]:
        resp = await self._request_with_auth("GET", "/peers")
        return resp.json()

    async def update_peer_status(self, peer_id: int, status: str) -> dict[str, Any]:
        resp = await self._request_with_auth("PATCH", f"/peers/{peer_id}", json={"status": status})
        return resp.json()

    async def health(self) -> dict[str, Any]:
        client = await self._get_client()
        resp = await client.get("/health")
        resp.raise_for_status()
        return resp.json()

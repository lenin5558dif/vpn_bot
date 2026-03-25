from __future__ import annotations

import asyncio
import ipaddress
import logging
import secrets
from typing import Iterable

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WireGuardManager:
    def __init__(self, interface: str | None = None) -> None:
        self.interface = interface or settings.wg_interface

    async def generate_keys(self) -> tuple[str, str]:
        try:
            proc = await asyncio.create_subprocess_exec(
                "wg", "genkey",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            private_key = stdout.decode().strip()

            proc2 = await asyncio.create_subprocess_exec(
                "wg", "pubkey",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout2, _ = await proc2.communicate(input=private_key.encode())
            public_key = stdout2.decode().strip()
        except Exception:
            logger.warning("wg genkey unavailable, using random fallback")
            private_key = secrets.token_hex(32)
            public_key = secrets.token_hex(32)
        return private_key, public_key

    def allocate_ip(self, used_addresses: Iterable[str]) -> str:
        network = ipaddress.ip_network(settings.wg_network)
        used = set()
        for a in used_addresses:
            try:
                used.add(ipaddress.ip_address(a.split("/")[0]))
            except Exception:
                continue
        reserved = {next(network.hosts())}
        used |= reserved
        for host in network.hosts():
            if host not in used:
                return f"{host}/32"
        raise RuntimeError("No free IP addresses in pool")

    def render_peer_config(self, private_key: str, address: str) -> str:
        if not settings.server_public_key:
            raise ValueError("SERVER_PUBLIC_KEY is not set in configuration")

        return (
            "[Interface]\n"
            f"PrivateKey = {private_key}\n"
            f"Address = {address}\n"
            "DNS = 1.1.1.1\n"
            f"MTU = {settings.wg_mtu}\n\n"
            "[Peer]\n"
            f"PublicKey = {settings.server_public_key}\n"
            f"Endpoint = {settings.wg_endpoint}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            f"PersistentKeepalive = {settings.wg_keepalive}\n"
        )

    async def apply_peer(self, public_key: str, allowed_ips: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "wg", "set", self.interface,
                "peer", public_key,
                "allowed-ips", allowed_ips,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("wg set peer failed: %s", stderr.decode())
        except Exception:
            logger.exception("Failed to apply peer %s", public_key)

    async def remove_peer(self, public_key: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "wg", "set", self.interface,
                "peer", public_key, "remove",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error("wg remove peer failed: %s", stderr.decode())
        except Exception:
            logger.exception("Failed to remove peer %s", public_key)

    async def apply_speed_limit(self, address: str, mbit: int) -> None:
        _ = (address, mbit)

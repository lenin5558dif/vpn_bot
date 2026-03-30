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
                "awg", "genkey",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            private_key = stdout.decode().strip()

            proc2 = await asyncio.create_subprocess_exec(
                "awg", "pubkey",
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
            f"MTU = {settings.wg_mtu}\n"
            "Jc = 4\n"
            "Jmin = 40\n"
            "Jmax = 70\n"
            "S1 = 0\n"
            "S2 = 0\n"
            "H1 = 1\n"
            "H2 = 2\n"
            "H3 = 3\n"
            "H4 = 4\n\n"
            "[Peer]\n"
            f"PublicKey = {settings.server_public_key}\n"
            f"Endpoint = {settings.wg_endpoint}\n"
            "AllowedIPs = 0.0.0.0/0, ::/0\n"
            f"PersistentKeepalive = {settings.wg_keepalive}\n"
        )

    async def apply_peer(self, public_key: str, allowed_ips: str) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "awg", "set", self.interface,
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
                "awg", "set", self.interface,
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
        """Apply per-peer speed limit using tc (traffic control).

        Creates an HTB qdisc on the WG interface and adds a class + filter
        for the peer IP. Idempotent: deletes existing filter before adding.
        """
        if mbit <= 0:
            await self.remove_speed_limit(address)
            return
        try:
            # Ensure root qdisc exists (htb). Ignore error if already exists.
            await self._tc(
                "qdisc", "add", "dev", self.interface,
                "root", "handle", "1:", "htb", "default", "999",
            )
            # Create a class for this peer (use last octet as class id)
            class_id = self._class_id(address)
            # Delete existing class (ignore error if not exists)
            await self._tc("class", "del", "dev", self.interface, "classid", f"1:{class_id}")
            # Add class with rate limit
            await self._tc(
                "class", "add", "dev", self.interface,
                "parent", "1:", "classid", f"1:{class_id}",
                "htb", "rate", f"{mbit}mbit", "ceil", f"{mbit}mbit",
            )
            # Add filter to match peer IP to this class
            await self._tc(
                "filter", "add", "dev", self.interface,
                "parent", "1:", "protocol", "ip", "prio", "1",
                "u32", "match", "ip", "dst", f"{address}/32",
                "flowid", f"1:{class_id}",
            )
            logger.info("Speed limit %d mbit applied to %s (class 1:%s)", mbit, address, class_id)
        except Exception:
            logger.exception("Failed to apply speed limit for %s", address)

    async def remove_speed_limit(self, address: str) -> None:
        """Remove per-peer speed limit."""
        try:
            class_id = self._class_id(address)
            await self._tc("class", "del", "dev", self.interface, "classid", f"1:{class_id}")
            logger.info("Speed limit removed for %s", address)
        except Exception:
            logger.exception("Failed to remove speed limit for %s", address)

    async def get_latest_handshakes(self) -> dict[str, int]:
        """Return {public_key: unix_timestamp} from awg show latest-handshakes."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "awg", "show", self.interface, "latest-handshakes",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return {}
            result: dict[str, int] = {}
            for line in stdout.decode().splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    result[parts[0]] = int(parts[1])
            return result
        except Exception:
            logger.warning("Failed to get latest handshakes")
            return {}

    @staticmethod
    def _class_id(address: str) -> str:
        """Derive tc class id from IP address (last two octets as hex)."""
        parts = address.split(".")
        return format(int(parts[-1]), "x")

    async def _tc(self, *args: str) -> None:
        """Run a tc command, log errors but don't raise."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "tc", *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.debug("tc %s returned %d: %s", " ".join(args), proc.returncode, stderr.decode().strip())
        except Exception:
            logger.debug("tc command unavailable: tc %s", " ".join(args))

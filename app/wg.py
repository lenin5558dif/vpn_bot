from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
from typing import Iterable

from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


class WireGuardError(RuntimeError):
    """Required WireGuard/tc operation failed."""


class WireGuardManager:
    def __init__(self, interface: str | None = None) -> None:
        self.interface = interface or settings.wg_interface

    async def generate_keys(self) -> tuple[str, str]:
        private_key = (await self._run("awg", "genkey")).strip()
        if not private_key:
            raise WireGuardError("awg genkey returned an empty private key")
        public_key = (await self._run("awg", "pubkey", input_data=private_key.encode())).strip()
        if not public_key:
            raise WireGuardError("awg pubkey returned an empty public key")
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
        await self._run(
            "awg", "set", self.interface,
            "peer", public_key,
            "allowed-ips", allowed_ips,
        )

    async def remove_peer(self, public_key: str) -> None:
        await self._run("awg", "set", self.interface, "peer", public_key, "remove")

    async def apply_speed_limit(self, address: str, mbit: int) -> None:
        """Apply per-peer speed limit using tc (traffic control).

        Creates an HTB qdisc on the WG interface and adds a class + filter
        for the peer IP. Idempotent: deletes existing filter before adding.
        """
        if mbit <= 0:
            await self.remove_speed_limit(address)
            return
        # Ensure root qdisc exists (htb). Ignore error if already exists.
        await self._tc(
            "qdisc", "add", "dev", self.interface,
            "root", "handle", "1:", "htb", "default", "999",
            check=False,
        )
        class_id = self._class_id(address)
        # Remove the old per-address filter before replacing its class.
        await self._tc(
            "filter", "del", "dev", self.interface,
            "parent", "1:", "protocol", "ip", "prio", "1",
            "u32", "match", "ip", "dst", f"{address}/32",
            check=False,
        )
        await self._tc("class", "del", "dev", self.interface, "classid", f"1:{class_id}", check=False)
        await self._tc(
            "class", "add", "dev", self.interface,
            "parent", "1:", "classid", f"1:{class_id}",
            "htb", "rate", f"{mbit}mbit", "ceil", f"{mbit}mbit",
        )
        await self._tc(
            "filter", "add", "dev", self.interface,
            "parent", "1:", "protocol", "ip", "prio", "1",
            "u32", "match", "ip", "dst", f"{address}/32",
            "flowid", f"1:{class_id}",
        )
        logger.info("Speed limit %d mbit applied to %s (class 1:%s)", mbit, address, class_id)

    async def remove_speed_limit(self, address: str) -> None:
        """Remove per-peer speed limit."""
        class_id = self._class_id(address)
        await self._tc("class", "del", "dev", self.interface, "classid", f"1:{class_id}", check=False)
        logger.info("Speed limit removed for %s", address)

    async def get_latest_handshakes(self) -> dict[str, int]:
        """Return {public_key: unix_timestamp} from awg show latest-handshakes."""
        try:
            stdout = await self._run("awg", "show", self.interface, "latest-handshakes")
            result: dict[str, int] = {}
            for line in stdout.splitlines():
                parts = line.split()
                if len(parts) == 2 and parts[1].isdigit():
                    result[parts[0]] = int(parts[1])
            return result
        except Exception:
            logger.warning("Failed to get latest handshakes")
            return {}

    async def runtime_snapshot(self) -> dict:
        """Return sanitized live WireGuard peer state from `awg show <iface> dump`.

        The dump contains the interface private key on the first line; this
        method deliberately ignores that line and returns only peer public keys,
        allowed IPs, transfer counters, and handshake timestamps.
        """
        try:
            stdout = await self._run("awg", "show", self.interface, "dump")
        except WireGuardError:
            logger.warning("WireGuard runtime snapshot unavailable")
            return {"available": False, "error": "unavailable", "peers": {}}

        peers: dict[str, dict] = {}
        for line_no, line in enumerate(stdout.splitlines()):
            if line_no == 0:
                continue
            parts = line.split("\t")
            if len(parts) < 8:
                parts = line.split()
            if len(parts) < 8:
                continue
            public_key = parts[0]
            allowed_ips = parts[3] if parts[3] != "(none)" else ""
            latest_handshake = int(parts[4]) if parts[4].isdigit() else 0
            rx_bytes = int(parts[5]) if parts[5].isdigit() else 0
            tx_bytes = int(parts[6]) if parts[6].isdigit() else 0
            peers[public_key] = {
                "allowed_ips": allowed_ips,
                "latest_handshake": latest_handshake,
                "rx_bytes": rx_bytes,
                "tx_bytes": tx_bytes,
            }
        return {"available": True, "error": None, "peers": peers}

    @staticmethod
    def _class_id(address: str) -> str:
        """Derive tc class id from IP address (last two octets as hex)."""
        parts = address.split(".")
        return format(int(parts[-1]), "x")

    async def _tc(self, *args: str, check: bool = True) -> None:
        """Run a tc command with timeout. Raises on required failures."""
        await self._run("tc", *args, check=check)

    async def _run(
        self,
        *args: str,
        input_data: bytes | None = None,
        check: bool = True,
    ) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE if input_data is not None else None,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=input_data),
                timeout=settings.subprocess_timeout_sec,
            )
        except TimeoutError as exc:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(ProcessLookupError):
                await proc.wait()
            raise WireGuardError(f"Command timed out: {self._safe_command(args)}") from exc
        except OSError as exc:
            raise WireGuardError(f"Command unavailable: {args[0]}") from exc

        if proc.returncode != 0:
            message = stderr.decode(errors="replace").strip()
            if check:
                raise WireGuardError(
                    f"Command failed ({proc.returncode}): {self._safe_command(args)}"
                )
            logger.debug("%s returned %d: %s", " ".join(args), proc.returncode, message)
        return stdout.decode(errors="replace")

    @staticmethod
    def _safe_command(args: tuple[str, ...]) -> str:
        """Render a command for errors without exposing WireGuard peer keys."""
        safe: list[str] = []
        hide_next = False
        for arg in args:
            if hide_next:
                safe.append("<peer-key>")
                hide_next = False
                continue
            safe.append(arg)
            hide_next = arg == "peer"
        return " ".join(safe)

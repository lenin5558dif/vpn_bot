from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel import select

from app.models import Peer, TrafficStat

logger = logging.getLogger(__name__)
TRANSFER_RE = re.compile(r"transfer:\s+(\d+)\s+B received,\s+(\d+)\s+B sent")


class TrafficPoller:
    def __init__(self, session_factory: async_sessionmaker, interface: str) -> None:
        self.session_factory = session_factory
        self.interface = interface
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if not self._task:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        cycle = 0
        while True:
            try:
                await self.collect()
            except Exception:
                logger.exception("TrafficPoller.collect() failed")
            cycle += 1
            if cycle % 60 == 0:
                try:
                    await self.cleanup()
                except Exception:
                    logger.exception("TrafficPoller.cleanup() failed")
            await asyncio.sleep(60)

    async def collect(self) -> None:
        try:
            proc = await asyncio.create_subprocess_exec(
                "awg", "show", self.interface, "transfer",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode != 0:
                return
            output = stdout.decode()
        except Exception:
            logger.warning("wg show transfer unavailable")
            return

        lines = output.splitlines()
        stats: dict[str, tuple[int, int]] = {}
        current_peer: str | None = None
        for line in lines:
            if line.startswith("peer"):
                current_peer = line.split(":", 1)[1].strip()
                continue
            if "transfer" in line and current_peer:
                match = TRANSFER_RE.search(line)
                if match:
                    rx, tx = int(match.group(1)), int(match.group(2))
                    stats[current_peer] = (rx, tx)
                continue
            parts = line.split()
            if len(parts) == 3:
                pk, rx_s, tx_s = parts
                if rx_s.isdigit() and tx_s.isdigit():
                    stats[pk] = (int(rx_s), int(tx_s))

        if not stats:
            return

        async with self.session_factory() as session:
            peers_res = await session.exec(select(Peer.id, Peer.public_key))
            peers = peers_res.all()

            # Fetch all latest stats in ONE query (eliminates N+1)
            # Use subquery with MAX(ts) for SQLite/PostgreSQL compatibility
            latest_stats_result = await session.exec(
                text(
                    "SELECT t.peer_id, t.rx_bytes, t.tx_bytes "
                    "FROM trafficstat t "
                    "INNER JOIN (SELECT peer_id, MAX(ts) AS max_ts FROM trafficstat GROUP BY peer_id) g "
                    "ON t.peer_id = g.peer_id AND t.ts = g.max_ts"
                )
            )
            last_by_peer: dict[int, tuple[int, int]] = {}
            for row in latest_stats_result.all():
                last_by_peer[row[0]] = (row[1], row[2])

            now = datetime.utcnow()
            for peer_id, public_key in peers:
                if public_key not in stats:
                    continue
                rx, tx = stats[public_key]
                prev_rx, prev_tx = last_by_peer.get(peer_id, (0, 0))
                delta_rx = max(rx - prev_rx, 0)
                delta_tx = max(tx - prev_tx, 0)

                entry = TrafficStat(
                    peer_id=peer_id,
                    ts=now,
                    rx_bytes=rx,
                    tx_bytes=tx,
                    delta_rx=delta_rx,
                    delta_tx=delta_tx,
                )
                session.add(entry)
            await session.commit()

    async def cleanup(self) -> None:
        """Delete TrafficStat rows older than 7 days."""
        async with self.session_factory() as session:
            cutoff = datetime.utcnow() - timedelta(days=7)
            await session.exec(
                text("DELETE FROM trafficstat WHERE ts < :cutoff"),
                params={"cutoff": cutoff},
            )
            await session.commit()
            logger.info("TrafficStat cleanup: deleted rows older than %s", cutoff)

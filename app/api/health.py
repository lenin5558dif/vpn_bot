import asyncio
import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.api.deps import AdminDep
from app.database import engine

logger = logging.getLogger(__name__)
router = APIRouter()
settings = get_settings()


@router.get("/health")
async def health() -> dict:
    checks = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["db"] = "ok"
    except Exception as exc:
        logger.error("Health: DB check failed: %s", exc)
        checks["db"] = "error"

    try:
        proc = await asyncio.create_subprocess_exec(
            "awg", "show", settings.wg_interface,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        checks["wireguard"] = "ok" if proc.returncode == 0 else "error"
    except Exception:
        checks["wireguard"] = "unavailable"

    overall = "ok" if all(v == "ok" for v in checks.values()) else "degraded"
    return {"status": overall, "checks": checks}


@router.get("/stats/server")
async def server_stats(admin: AdminDep) -> dict:
    """Return server system stats."""
    import os
    import time
    _ = admin

    # CPU load
    try:
        load1, load5, load15 = os.getloadavg()
        cpu_count = os.cpu_count() or 1
        cpu_pct = round(load1 / cpu_count * 100, 1)
    except Exception:
        cpu_pct, cpu_count = 0, 1

    # Memory
    try:
        with open("/proc/meminfo") as f:
            lines = {l.split(":")[0]: int(l.split()[1]) for l in f if len(l.split()) >= 2}
        mem_total = lines.get("MemTotal", 0) // 1024
        mem_avail = lines.get("MemAvailable", 0) // 1024
        mem_used = mem_total - mem_avail
    except Exception:
        mem_total, mem_used = 0, 0

    # Disk
    try:
        st = os.statvfs("/")
        disk_total = st.f_blocks * st.f_frsize // (1024 ** 3)
        disk_free = st.f_bavail * st.f_frsize // (1024 ** 3)
        disk_used = disk_total - disk_free
    except Exception:
        disk_total, disk_used = 0, 0

    # Uptime
    try:
        with open("/proc/uptime") as f:
            uptime_sec = int(float(f.read().split()[0]))
        days, rem = divmod(uptime_sec, 86400)
        hours, rem = divmod(rem, 3600)
        uptime_str = f"{days}d {hours}h"
    except Exception:
        uptime_str = "unknown"

    # DB stats
    try:
        from sqlalchemy import text as sa_text
        async with engine.connect() as conn:
            peers = (await conn.execute(sa_text("SELECT COUNT(*) FROM peer"))).scalar()
            traffic = (await conn.execute(sa_text("SELECT COUNT(*) FROM trafficstat"))).scalar()
    except Exception:
        peers, traffic = 0, 0

    return {
        "cpu_pct": cpu_pct,
        "cpu_cores": cpu_count,
        "ram_used_mb": mem_used,
        "ram_total_mb": mem_total,
        "disk_used_gb": disk_used,
        "disk_total_gb": disk_total,
        "uptime": uptime_str,
        "peers_total": peers,
        "trafficstat_rows": traffic,
    }

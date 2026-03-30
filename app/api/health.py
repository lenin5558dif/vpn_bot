import asyncio
import logging

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
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

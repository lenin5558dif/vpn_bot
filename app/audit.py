from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def record_audit(
    session: AsyncSession,
    *,
    action: str,
    target_type: str | None = None,
    target_id: int | None = None,
    actor_id: int | None = None,
    ip: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    log = AuditLog(
        action=action,
        target_type=target_type,
        target_id=target_id,
        actor_id=actor_id,
        ip=ip,
        meta=meta,
    )
    session.add(log)
    await session.commit()

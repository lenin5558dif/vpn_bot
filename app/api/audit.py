from fastapi import APIRouter, Query
from sqlmodel import select

from app.api.deps import AdminDep, DBSession
from app.models import AuditLog
from app.schemas import AuditRead

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("", response_model=list[AuditRead])
async def list_audit(
    session: DBSession,
    admin: AdminDep,
    limit: int = Query(20, ge=1, le=200),
) -> list[AuditRead]:
    _ = admin
    res = await session.exec(select(AuditLog).order_by(AuditLog.ts.desc()).limit(limit))
    return [AuditRead.model_validate(r) for r in res.all()]

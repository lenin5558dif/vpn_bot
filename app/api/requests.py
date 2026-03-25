from datetime import datetime

from fastapi import APIRouter, HTTPException, Query, Request, status
from sqlmodel import select

from app.audit import record_audit
from app.api.deps import AdminDep, BotKeyDep, DBSession
from app.models import Request as RequestModel, RequestStatus
from app.schemas import RequestCreate, RequestRead, RequestUpdate

router = APIRouter(prefix="/requests", tags=["requests"])


@router.post("", response_model=RequestRead)
async def create_request(payload: RequestCreate, session: DBSession, _bot_key: BotKeyDep) -> RequestRead:
    req = RequestModel(user_id=payload.user_id, comment=payload.comment, status=RequestStatus.new)
    session.add(req)
    await session.commit()
    await session.refresh(req)
    return RequestRead.model_validate(req)


@router.get("", response_model=list[RequestRead])
async def list_requests(
    session: DBSession,
    admin: AdminDep,
    status_filter: RequestStatus | None = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[RequestRead]:
    _ = admin
    query = select(RequestModel)
    if status_filter:
        query = query.where(RequestModel.status == status_filter)
    result = await session.exec(query.order_by(RequestModel.created_at.desc()).offset(offset).limit(limit))
    return [RequestRead.model_validate(r) for r in result.all()]


@router.patch("/{request_id}", response_model=RequestRead)
async def update_request(
    request_id: int,
    payload: RequestUpdate,
    session: DBSession,
    admin: AdminDep,
    request: Request,
) -> RequestRead:
    _ = admin
    req = await session.get(RequestModel, request_id)
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    req.status = payload.status
    req.resolved_by = payload.resolved_by
    req.resolved_at = datetime.utcnow()
    session.add(req)
    await record_audit(
        session,
        action="request_update",
        target_type="request",
        target_id=req.id,
        actor_id=payload.resolved_by,
        ip=request.client.host if request.client else None,
        meta={"status": req.status.value},
    )
    await session.commit()
    await session.refresh(req)
    return RequestRead.model_validate(req)

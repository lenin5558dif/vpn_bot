from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlalchemy import func
from sqlmodel import select

from app.api.deps import AdminDep, DBSession
from app.models import Peer, TrafficStat, User
from app.schemas import TrafficRead

router = APIRouter(prefix="/traffic", tags=["traffic"])


@router.get("", response_model=list[TrafficRead])
async def list_traffic(
    session: DBSession,
    admin: AdminDep,
    hours: int | None = Query(None, ge=1, le=720),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
) -> list[TrafficRead]:
    _ = admin
    stmt = select(TrafficStat).order_by(TrafficStat.ts.desc())
    if hours:
        since = datetime.utcnow() - timedelta(hours=hours)
        stmt = stmt.where(TrafficStat.ts >= since)
    stmt = stmt.offset(offset).limit(limit)
    res = await session.exec(stmt)
    return [TrafficRead.model_validate(t) for t in res.all()]


@router.get("/summary")
async def traffic_summary(
    session: DBSession,
    admin: AdminDep,
    hours: int = Query(24, ge=1, le=720),
) -> list[dict]:
    _ = admin
    since = datetime.utcnow() - timedelta(hours=hours)
    res = await session.exec(
        select(
            TrafficStat.peer_id,
            Peer.user_id,
            Peer.address,
            Peer.status,
            User.name,
            func.sum(TrafficStat.delta_rx).label("rx"),
            func.sum(TrafficStat.delta_tx).label("tx"),
        )
        .join(Peer, Peer.id == TrafficStat.peer_id)
        .join(User, User.id == Peer.user_id)
        .where(TrafficStat.ts >= since)
        .group_by(TrafficStat.peer_id, Peer.user_id, Peer.address, Peer.status, User.name)
    )
    return [
        {
            "peer_id": row[0],
            "user_id": row[1],
            "address": row[2],
            "status": row[3],
            "name": row[4],
            "rx": row[5] or 0,
            "tx": row[6] or 0,
        }
        for row in res.all()
    ]

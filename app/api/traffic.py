from datetime import datetime, timedelta

from fastapi import APIRouter, Query
from sqlmodel import select

from app.api.deps import AdminDep, DBSession
from app.models import Peer, TrafficStat
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
            TrafficStat.ts,
            TrafficStat.delta_rx,
            TrafficStat.delta_tx,
        ).join(Peer, Peer.id == TrafficStat.peer_id)
    )
    rows = res.all()
    summary: dict[int, dict] = {}
    for peer_id, user_id, addr, status, ts, drx, dtx in rows:
        if ts < since:
            continue
        entry = summary.setdefault(
            peer_id,
            {"peer_id": peer_id, "user_id": user_id, "address": addr, "status": status, "rx": 0, "tx": 0},
        )
        entry["rx"] += drx
        entry["tx"] += dtx
    return list(summary.values())

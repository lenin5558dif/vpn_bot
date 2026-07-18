from datetime import datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import func, or_
from sqlmodel import select

from app.api.deps import AdminOrBotDep, BotKeyDep, DBSession
from app.models import Peer, Request as RequestModel, Role, TrafficStat, User
from app.schemas import UserCreate, UserRead
from app.wg import WireGuardManager

router = APIRouter(prefix="/users", tags=["users"])
wg = WireGuardManager()


@router.post("", response_model=UserRead)
async def create_user(payload: UserCreate, session: DBSession, _bot_key: BotKeyDep) -> UserRead:
    # Upsert: return existing user if tg_id already exists
    if payload.tg_id is not None:
        existing = await session.exec(select(User).where(User.tg_id == payload.tg_id))
        user = existing.first()
        if user:
            return UserRead.model_validate(user)

    user = User(name=payload.name, contact=payload.contact, tg_id=payload.tg_id, role=Role.user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return UserRead.model_validate(user)


@router.get("", response_model=list[UserRead])
async def list_users(
    session: DBSession,
    admin: AdminOrBotDep,
    tg_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[UserRead]:
    _ = admin
    query = select(User)
    if tg_id is not None:
        query = query.where(User.tg_id == tg_id)
    users = await session.exec(query.order_by(User.id).offset(offset).limit(limit))
    return [UserRead.model_validate(u) for u in users.all()]


def _user_search_filter(query_text: str):
    term = query_text.strip()
    if not term:
        return None
    filters = [
        func.lower(User.name).like(f"%{term.lower()}%"),
        func.lower(func.coalesce(User.contact, "")).like(f"%{term.lower()}%"),
    ]
    if term.isdigit():
        value = int(term)
        filters.extend([User.id == value, User.tg_id == value])
    return or_(*filters)


@router.get("/admin/list")
async def admin_user_list(
    session: DBSession,
    admin: AdminOrBotDep,
    query: str | None = Query(None, max_length=100),
    limit: int = Query(8, ge=1, le=50),
    offset: int = Query(0, ge=0),
) -> dict:
    """Return a paged user-centric admin list with peer/request/traffic aggregates."""
    _ = admin
    where_filter = _user_search_filter(query or "")

    count_stmt = select(func.count(User.id))
    users_stmt = select(User)
    if where_filter is not None:
        count_stmt = count_stmt.where(where_filter)
        users_stmt = users_stmt.where(where_filter)

    total = (await session.exec(count_stmt)).one()
    users = (await session.exec(users_stmt.order_by(User.id).offset(offset).limit(limit))).all()
    user_ids = [u.id for u in users if u.id is not None]

    peer_counts: dict[int, dict[str, int]] = {}
    traffic_by_user: dict[int, int] = {}
    latest_requests: dict[int, dict] = {}
    if user_ids:
        peer_rows = await session.exec(
            select(Peer.user_id, Peer.status, func.count(Peer.id))
            .where(Peer.user_id.in_(user_ids))
            .group_by(Peer.user_id, Peer.status)
        )
        for user_id, peer_status, count in peer_rows.all():
            peer_counts.setdefault(user_id, {"total": 0, "active": 0, "disabled": 0, "banned": 0})
            peer_counts[user_id]["total"] += count
            peer_counts[user_id][peer_status.value if hasattr(peer_status, "value") else peer_status] = count

        since = datetime.utcnow() - timedelta(hours=24)
        traffic_rows = await session.exec(
            select(Peer.user_id, func.sum(TrafficStat.delta_rx + TrafficStat.delta_tx))
            .join(TrafficStat, TrafficStat.peer_id == Peer.id)
            .where(Peer.user_id.in_(user_ids), TrafficStat.ts >= since)
            .group_by(Peer.user_id)
        )
        traffic_by_user = {user_id: int(total_bytes or 0) for user_id, total_bytes in traffic_rows.all()}

        req_rows = await session.exec(
            select(RequestModel)
            .where(RequestModel.user_id.in_(user_ids))
            .order_by(RequestModel.user_id, RequestModel.created_at.desc(), RequestModel.id.desc())
        )
        for req in req_rows.all():
            if req.user_id not in latest_requests:
                latest_requests[req.user_id] = {
                    "id": req.id,
                    "status": req.status.value,
                    "created_at": req.created_at.isoformat() if req.created_at else None,
                    "comment": req.comment,
                }

    items = []
    for user in users:
        counts = peer_counts.get(user.id, {"total": 0, "active": 0, "disabled": 0, "banned": 0})
        items.append({
            "id": user.id,
            "tg_id": user.tg_id,
            "name": user.name,
            "contact": user.contact,
            "created_at": user.created_at.isoformat() if user.created_at else None,
            "peer_counts": counts,
            "latest_request": latest_requests.get(user.id),
            "traffic_24h_bytes": traffic_by_user.get(user.id, 0),
        })
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.get("/{user_id}/admin-card")
async def admin_user_card(user_id: int, session: DBSession, admin: AdminOrBotDep) -> dict:
    """Return a complete admin card for one user and their peer devices."""
    _ = admin
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    reqs = (
        await session.exec(
            select(RequestModel)
            .where(RequestModel.user_id == user_id)
            .order_by(RequestModel.created_at.desc(), RequestModel.id.desc())
            .limit(1)
        )
    ).all()
    latest_request = None
    if reqs:
        req = reqs[0]
        latest_request = {
            "id": req.id,
            "status": req.status.value,
            "comment": req.comment,
            "created_at": req.created_at.isoformat() if req.created_at else None,
            "resolved_at": req.resolved_at.isoformat() if req.resolved_at else None,
        }

    peers = (await session.exec(select(Peer).where(Peer.user_id == user_id).order_by(Peer.id))).all()
    peer_ids = [p.id for p in peers if p.id is not None]
    since = datetime.utcnow() - timedelta(hours=24)
    traffic_by_peer: dict[int, dict[str, int]] = {}
    if peer_ids:
        traffic_rows = await session.exec(
            select(
                TrafficStat.peer_id,
                func.sum(TrafficStat.delta_rx),
                func.sum(TrafficStat.delta_tx),
            )
            .where(TrafficStat.peer_id.in_(peer_ids), TrafficStat.ts >= since)
            .group_by(TrafficStat.peer_id)
        )
        traffic_by_peer = {
            peer_id: {"rx": int(rx or 0), "tx": int(tx or 0)}
            for peer_id, rx, tx in traffic_rows.all()
        }

    snapshot = await wg.runtime_snapshot()
    runtime_peers = snapshot.get("peers", {}) if snapshot.get("available") else {}
    now_ts = int(datetime.utcnow().timestamp())
    peer_items = []
    for peer in peers:
        runtime = runtime_peers.get(peer.public_key, {})
        handshake_ts = int(runtime.get("latest_handshake") or 0)
        peer_items.append({
            "id": peer.id,
            "user_id": peer.user_id,
            "address": peer.address,
            "allowed_ips": peer.allowed_ips,
            "status": peer.status.value,
            "speed_limit_mbps": peer.speed_limit_mbps,
            "created_at": peer.created_at.isoformat() if peer.created_at else None,
            "updated_at": peer.updated_at.isoformat() if peer.updated_at else None,
            "last_handshake_at": (
                datetime.utcfromtimestamp(handshake_ts).isoformat()
                if handshake_ts > 0
                else (peer.last_handshake_at.isoformat() if peer.last_handshake_at else None)
            ),
            "online": handshake_ts > 0 and (now_ts - handshake_ts) < 180,
            "wg_present": peer.public_key in runtime_peers,
            "wg_allowed_ips": runtime.get("allowed_ips"),
            "traffic_24h": traffic_by_peer.get(peer.id, {"rx": 0, "tx": 0}),
        })

    return {
        "user": UserRead.model_validate(user).model_dump(mode="json"),
        "latest_request": latest_request,
        "peers": peer_items,
        "wg": {"available": bool(snapshot.get("available")), "error": snapshot.get("error")},
        "traffic_24h_bytes": sum(v["rx"] + v["tx"] for v in traffic_by_peer.values()),
    }


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: int, session: DBSession, admin: AdminOrBotDep) -> UserRead:
    _ = admin
    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return UserRead.model_validate(user)

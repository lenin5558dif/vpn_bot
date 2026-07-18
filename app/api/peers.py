import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from app.audit import record_audit
from app.api.deps import AdminOrBotDep, DBSession
from app.config import get_settings
from app.crypto import decrypt_private_key, encrypt_private_key
from app.models import Config, Peer, PeerStatus, TrafficStat, User
from app.schemas import ConfigRead, PeerCreate, PeerRead, PeerStatusUpdate
from app.wg import WireGuardError, WireGuardManager

router = APIRouter(prefix="/peers", tags=["peers"])
wg = WireGuardManager()
settings = get_settings()
logger = logging.getLogger(__name__)
_peer_mutation_lock = asyncio.Lock()


async def _serialize_peer_mutations() -> AsyncIterator[None]:
    """Serialize DB↔WireGuard mutations within this backend process."""
    async with _peer_mutation_lock:
        yield


async def _remove_peer_best_effort(public_key: str) -> bool:
    try:
        await wg.remove_peer(public_key)
    except Exception:
        logger.critical(
            "Failed to remove partially provisioned WireGuard peer %s; manual reconciliation required",
            _fingerprint_public_key(public_key),
            exc_info=True,
        )
        return False
    return True


async def _restore_peer_state(
    public_key: str,
    address: str,
    allowed_ips: str,
    status_before: PeerStatus,
    speed_before: int,
) -> bool:
    """Best-effort compensation after a DB failure following a WG state change."""
    try:
        if status_before == PeerStatus.active:
            await wg.apply_speed_limit(address.split("/")[0], speed_before)
            await wg.apply_peer(public_key, allowed_ips)
        elif status_before == PeerStatus.disabled:
            await wg.apply_speed_limit(address.split("/")[0], speed_before)
            await wg.apply_peer(public_key, allowed_ips="")
        else:
            await wg.remove_peer(public_key)
    except Exception:
        logger.critical(
            "Failed to restore WireGuard state for peer %s; manual reconciliation required",
            _fingerprint_public_key(public_key),
            exc_info=True,
        )
        return False
    return True


async def _apply_peer_runtime(peer: Peer, new_status: PeerStatus, new_speed: int) -> None:
    if new_status == PeerStatus.banned:
        await wg.remove_peer(peer.public_key)
    elif new_status == PeerStatus.disabled:
        await wg.apply_peer(peer.public_key, allowed_ips="")
    elif new_status == PeerStatus.active:
        await wg.apply_speed_limit(address=peer.address.split("/")[0], mbit=new_speed)
        await wg.apply_peer(peer.public_key, allowed_ips=peer.allowed_ips)


def _fingerprint_public_key(public_key: str) -> str:
    if len(public_key) <= 16:
        return public_key
    return f"{public_key[:10]}…{public_key[-6:]}"


def _split_allowed_ips(value: str | None) -> set[str]:
    if not value or value == "(none)":
        return set()
    return {part.strip() for part in value.split(",") if part.strip()}


@router.get("", response_model=list[PeerRead])
async def list_peers(
    session: DBSession,
    admin: AdminOrBotDep,
    user_id: int | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[PeerRead]:
    _ = admin
    query = select(Peer)
    if user_id is not None:
        query = query.where(Peer.user_id == user_id)
    res = await session.exec(query.order_by(Peer.id).offset(offset).limit(limit))
    return [PeerRead.model_validate(p) for p in res.all()]


@router.post("", response_model=PeerRead)
async def create_peer(
    payload: PeerCreate,
    session: DBSession,
    admin: AdminOrBotDep,
    request: Request,
    operation_lock: None = Depends(_serialize_peer_mutations),
) -> PeerRead:
    _ = admin, operation_lock
    user = await session.get(User, payload.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    addr_res = await session.exec(select(Peer.address).where(Peer.address.is_not(None)))
    used_addresses = [a for a in addr_res.all()]
    address = wg.allocate_ip(used_addresses)
    allowed_ips = payload.allowed_ips or address
    speed_limit_mbps = (
        payload.speed_limit_mbps
        if payload.speed_limit_mbps is not None
        else settings.default_speed_limit_mbit
    )

    public_key = ""
    try:
        private_key, public_key = await wg.generate_keys()
        await wg.apply_peer(public_key=public_key, allowed_ips=allowed_ips)
        try:
            await wg.apply_speed_limit(address=address.split("/")[0], mbit=speed_limit_mbps)
        except WireGuardError:
            if not await _remove_peer_best_effort(public_key):
                raise WireGuardError("Provisioning cleanup failed; manual reconciliation required")
            raise
    except WireGuardError as exc:
        logger.error("WireGuard peer provisioning failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WireGuard provisioning failed",
        ) from exc

    peer = Peer(
        user_id=payload.user_id,
        iface=wg.interface,
        public_key=public_key,
        private_key_enc=encrypt_private_key(private_key),
        address=address,
        allowed_ips=allowed_ips,
        status=PeerStatus.active,
        speed_limit_mbps=speed_limit_mbps,
    )
    try:
        session.add(peer)
        await session.flush()
        cfg = Config(
            peer_id=peer.id,
            download_token=secrets.token_urlsafe(16),
            expires_at=datetime.utcnow() + timedelta(days=2),
            qr_data=None,
        )
        session.add(cfg)
        await record_audit(
            session,
            action="peer_create",
            target_type="peer",
            target_id=peer.id,
            ip=request.client.host if request.client else None,
            meta={"user_id": peer.user_id},
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not await _remove_peer_best_effort(public_key):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Provisioning cleanup failed; manual reconciliation required",
            ) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Peer address or key already exists") from exc
    except Exception as exc:
        await session.rollback()
        if not await _remove_peer_best_effort(public_key):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Provisioning cleanup failed; manual reconciliation required",
            ) from exc
        raise
    await session.refresh(peer)
    return PeerRead.model_validate(peer)


@router.patch("/{peer_id}", response_model=PeerRead)
async def update_peer(
    peer_id: int,
    payload: PeerStatusUpdate,
    session: DBSession,
    admin: AdminOrBotDep,
    request: Request,
    operation_lock: None = Depends(_serialize_peer_mutations),
) -> PeerRead:
    _ = admin, operation_lock
    peer = await session.get(Peer, peer_id)
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")

    new_status = payload.status
    new_speed = payload.speed_limit_mbps if payload.speed_limit_mbps is not None else peer.speed_limit_mbps

    old_status = peer.status
    old_speed = peer.speed_limit_mbps
    old_public_key = peer.public_key
    old_address = peer.address
    old_allowed_ips = peer.allowed_ips
    try:
        await _apply_peer_runtime(peer, new_status, new_speed)
    except WireGuardError as exc:
        logger.error("WireGuard peer update failed for peer %s: %s", peer_id, exc)
        restored = await _restore_peer_state(
            old_public_key,
            old_address,
            old_allowed_ips,
            old_status,
            old_speed,
        )
        if not restored:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="WireGuard operation failed; manual reconciliation required",
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WireGuard operation failed",
        ) from exc

    peer.status = new_status
    if payload.speed_limit_mbps is not None:
        peer.speed_limit_mbps = payload.speed_limit_mbps
    peer.updated_at = datetime.utcnow()

    if peer.status == PeerStatus.banned:
        peer_snapshot = PeerRead.model_validate(peer)
        try:
            # Bulk delete child rows (FK constraint)
            await session.exec(sa_delete(TrafficStat).where(TrafficStat.peer_id == peer_id))  # type: ignore[arg-type]
            await session.exec(sa_delete(Config).where(Config.peer_id == peer_id))  # type: ignore[arg-type]
            # Record audit before deleting the peer
            await record_audit(
                session,
                action="peer_delete",
                target_type="peer",
                target_id=peer_id,
                ip=request.client.host if request.client else None,
                meta={"status": "banned"},
            )
            await session.delete(peer)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            restored = await _restore_peer_state(
                old_public_key,
                old_address,
                old_allowed_ips,
                old_status,
                old_speed,
            )
            if not restored:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="State update failed; manual reconciliation required",
                ) from exc
            raise
        return peer_snapshot

    try:
        session.add(peer)
        await record_audit(
            session,
            action="peer_update",
            target_type="peer",
            target_id=peer.id,
            ip=request.client.host if request.client else None,
            meta={"status": peer.status.value},
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        restored = await _restore_peer_state(
            old_public_key,
            old_address,
            old_allowed_ips,
            old_status,
            old_speed,
        )
        if not restored:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="State update failed; manual reconciliation required",
            ) from exc
        raise
    await session.refresh(peer)
    return PeerRead.model_validate(peer)


@router.patch("/user/{user_id}/status")
async def bulk_update_user_peers(
    user_id: int,
    payload: PeerStatusUpdate,
    session: DBSession,
    admin: AdminOrBotDep,
    request: Request,
    operation_lock: None = Depends(_serialize_peer_mutations),
) -> dict:
    """Bulk enable/disable all non-banned peers for a user with compensation."""
    _ = admin, operation_lock
    if payload.status not in {PeerStatus.active, PeerStatus.disabled}:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Only active/disabled bulk status is allowed",
        )

    user = await session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    peers = (
        await session.exec(
            select(Peer)
            .where(Peer.user_id == user_id, Peer.status != PeerStatus.banned)
            .order_by(Peer.id)
        )
    ).all()
    snapshots = [
        (p.public_key, p.address, p.allowed_ips, p.status, p.speed_limit_mbps)
        for p in peers
    ]
    changed: list[tuple[str, str, str, PeerStatus, int]] = []
    try:
        for peer, snapshot in zip(peers, snapshots, strict=True):
            new_speed = payload.speed_limit_mbps if payload.speed_limit_mbps is not None else peer.speed_limit_mbps
            changed.append(snapshot)
            await _apply_peer_runtime(peer, payload.status, new_speed)
    except WireGuardError as exc:
        logger.error("Bulk WireGuard update failed for user %s: %s", user_id, exc)
        restored = True
        for snapshot in reversed(changed):
            restored = await _restore_peer_state(*snapshot) and restored
        detail = (
            "WireGuard bulk operation failed; manual reconciliation required"
            if not restored
            else "WireGuard bulk operation failed"
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=detail) from exc

    updated = 0
    now = datetime.utcnow()
    try:
        for peer in peers:
            peer.status = payload.status
            if payload.speed_limit_mbps is not None:
                peer.speed_limit_mbps = payload.speed_limit_mbps
            peer.updated_at = now
            session.add(peer)
            updated += 1
        await record_audit(
            session,
            action="peer_bulk_update",
            target_type="user",
            target_id=user_id,
            ip=request.client.host if request.client else None,
            meta={"status": payload.status.value, "updated": updated},
        )
        await session.commit()
    except Exception as exc:
        await session.rollback()
        restored = True
        for snapshot in reversed(changed):
            restored = await _restore_peer_state(*snapshot) and restored
        if not restored:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="State update failed; manual reconciliation required",
            ) from exc
        raise

    return {"user_id": user_id, "status": payload.status.value, "updated": updated}


@router.get("/reconcile")
async def reconcile_peers(session: DBSession, admin: AdminOrBotDep) -> dict:
    """Compare DB peer state with live WireGuard state. Never mutates WG."""
    _ = admin
    snapshot = await wg.runtime_snapshot()
    empty_result = {
        "status": "wireguard_unavailable",
        "wg_available": False,
        "counts": {
            "unknown_wg_peers": 0,
            "missing_wg_peers": 0,
            "allowed_ips_mismatch": 0,
            "disabled_with_allowed_ips": 0,
        },
        "unknown_wg_peers": [],
        "missing_wg_peers": [],
        "allowed_ips_mismatch": [],
        "disabled_with_allowed_ips": [],
    }
    if not snapshot.get("available"):
        return empty_result

    runtime_peers: dict[str, dict] = snapshot.get("peers", {})
    db_peers = (await session.exec(select(Peer))).all()
    db_by_key = {peer.public_key: peer for peer in db_peers}

    unknown = [
        {
            "public_key_fingerprint": _fingerprint_public_key(public_key),
            "allowed_ips": runtime.get("allowed_ips") or "",
            "latest_handshake": runtime.get("latest_handshake") or 0,
        }
        for public_key, runtime in runtime_peers.items()
        if public_key not in db_by_key
    ]
    missing = []
    mismatch = []
    disabled_nonempty = []
    for peer in db_peers:
        runtime = runtime_peers.get(peer.public_key)
        if peer.status != PeerStatus.banned and runtime is None:
            missing.append({
                "peer_id": peer.id,
                "user_id": peer.user_id,
                "status": peer.status.value,
                "address": peer.address,
            })
            continue
        if runtime is None:
            continue
        actual_allowed = _split_allowed_ips(runtime.get("allowed_ips"))
        expected_allowed = set() if peer.status == PeerStatus.disabled else _split_allowed_ips(peer.allowed_ips)
        if peer.status == PeerStatus.disabled and actual_allowed:
            disabled_nonempty.append({
                "peer_id": peer.id,
                "user_id": peer.user_id,
                "actual_allowed_ips": sorted(actual_allowed),
            })
        elif peer.status != PeerStatus.banned and actual_allowed != expected_allowed:
            mismatch.append({
                "peer_id": peer.id,
                "user_id": peer.user_id,
                "status": peer.status.value,
                "expected_allowed_ips": sorted(expected_allowed),
                "actual_allowed_ips": sorted(actual_allowed),
            })

    counts = {
        "unknown_wg_peers": len(unknown),
        "missing_wg_peers": len(missing),
        "allowed_ips_mismatch": len(mismatch),
        "disabled_with_allowed_ips": len(disabled_nonempty),
    }
    return {
        "status": "drift" if sum(counts.values()) else "ok",
        "wg_available": True,
        "counts": counts,
        "unknown_wg_peers": unknown,
        "missing_wg_peers": missing,
        "allowed_ips_mismatch": mismatch,
        "disabled_with_allowed_ips": disabled_nonempty,
    }


@router.get("/online")
async def online_peers(session: DBSession, admin: AdminOrBotDep) -> list[dict]:
    """Return peers with recent handshake (< 3 minutes)."""
    _ = admin
    import time
    handshakes = await wg.get_latest_handshakes()
    now = int(time.time())
    peers_res = await session.exec(select(Peer))
    peers = peers_res.all()

    # Get user names
    from app.models import User
    users_res = await session.exec(select(User))
    users_map = {u.id: u.name for u in users_res.all()}

    total = len(peers)
    online = []
    for peer in peers:
        ts = handshakes.get(peer.public_key, 0)
        if ts > 0 and (now - ts) < 180:  # 3 minutes
            online.append({
                "peer_id": peer.id,
                "user_id": peer.user_id,
                "name": users_map.get(peer.user_id, "?"),
                "address": peer.address,
                "seconds_ago": now - ts,
            })
    online.sort(key=lambda x: x["seconds_ago"])
    return [{"total": total, "online_count": len(online), "peers": online}]


@router.get("/{peer_id}/config", response_model=ConfigRead)
async def get_config(peer_id: int, session: DBSession, admin: AdminOrBotDep) -> ConfigRead:
    _ = admin
    peer = await session.get(Peer, peer_id)
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")

    cfg_res = await session.exec(select(Config).where(Config.peer_id == peer_id))
    cfg = cfg_res.first()
    if not cfg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

    return ConfigRead.model_validate(cfg)


@router.get("/{peer_id}/config/file")
async def download_config(peer_id: int, session: DBSession, admin: AdminOrBotDep) -> Response:
    _ = admin
    peer = await session.get(Peer, peer_id)
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")

    private_key = decrypt_private_key(peer.private_key_enc)
    config_body = wg.render_peer_config(private_key=private_key, address=peer.address)
    return Response(content=config_body, media_type="text/plain")

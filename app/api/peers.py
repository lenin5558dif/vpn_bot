from datetime import datetime, timedelta
import secrets

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from sqlmodel import select

from app.audit import record_audit
from app.api.deps import AdminDep, DBSession
from app.crypto import decrypt_private_key, encrypt_private_key
from app.models import Config, Peer, PeerStatus, TrafficStat
from app.schemas import ConfigRead, PeerCreate, PeerRead, PeerStatusUpdate
from app.wg import WireGuardManager

router = APIRouter(prefix="/peers", tags=["peers"])
wg = WireGuardManager()


@router.get("", response_model=list[PeerRead])
async def list_peers(
    session: DBSession,
    admin: AdminDep,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[PeerRead]:
    _ = admin
    res = await session.exec(select(Peer).offset(offset).limit(limit))
    return [PeerRead.model_validate(p) for p in res.all()]


@router.post("", response_model=PeerRead)
async def create_peer(
    payload: PeerCreate,
    session: DBSession,
    admin: AdminDep,
    request: Request,
) -> PeerRead:
    _ = admin
    existing_peers = await session.exec(select(Peer))
    used_addresses = [p.address for p in existing_peers.all() if p.address]
    address = wg.allocate_ip(used_addresses)
    private_key, public_key = await wg.generate_keys()
    allowed_ips = payload.allowed_ips or address

    peer = Peer(
        user_id=payload.user_id,
        iface=wg.interface,
        public_key=public_key,
        private_key_enc=encrypt_private_key(private_key),
        address=address,
        allowed_ips=allowed_ips,
        status=PeerStatus.active,
        speed_limit_mbps=payload.speed_limit_mbps if payload.speed_limit_mbps is not None else 20,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)

    await wg.apply_peer(public_key=public_key, allowed_ips=allowed_ips)
    await wg.apply_speed_limit(address=address.split("/")[0], mbit=peer.speed_limit_mbps)

    download_token = secrets.token_urlsafe(16)
    cfg = Config(
        peer_id=peer.id,
        download_token=download_token,
        expires_at=datetime.utcnow() + timedelta(days=2),
        qr_data=None,
    )
    session.add(cfg)
    await session.commit()

    await record_audit(
        session,
        action="peer_create",
        target_type="peer",
        target_id=peer.id,
        ip=request.client.host if request.client else None,
        meta={"user_id": peer.user_id},
    )
    return PeerRead.model_validate(peer)


@router.patch("/{peer_id}", response_model=PeerRead)
async def update_peer(
    peer_id: int,
    payload: PeerStatusUpdate,
    session: DBSession,
    admin: AdminDep,
    request: Request,
) -> PeerRead:
    _ = admin
    peer = await session.get(Peer, peer_id)
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")

    peer.status = payload.status
    if payload.speed_limit_mbps is not None:
        peer.speed_limit_mbps = payload.speed_limit_mbps
    peer.updated_at = datetime.utcnow()

    if peer.status == PeerStatus.banned:
        peer_snapshot = PeerRead.model_validate(peer)
        # Delete TrafficStat rows first (FK constraint)
        ts_res = await session.exec(select(TrafficStat).where(TrafficStat.peer_id == peer_id))
        for ts in ts_res.all():
            await session.delete(ts)
        # Delete Config rows
        cfg_res = await session.exec(select(Config).where(Config.peer_id == peer_id))
        for cfg in cfg_res.all():
            await session.delete(cfg)
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
        # Remove from WireGuard after successful DB commit
        await wg.remove_peer(peer_snapshot.public_key)
        return peer_snapshot
    elif peer.status == PeerStatus.disabled:
        await wg.apply_peer(peer.public_key, allowed_ips="")
    elif peer.status == PeerStatus.active:
        await wg.apply_peer(peer.public_key, allowed_ips=peer.allowed_ips)
        await wg.apply_speed_limit(address=peer.address.split("/")[0], mbit=peer.speed_limit_mbps)

    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    await record_audit(
        session,
        action="peer_update",
        target_type="peer",
        target_id=peer.id,
        ip=request.client.host if request.client else None,
        meta={"status": peer.status.value},
    )
    return PeerRead.model_validate(peer)


@router.get("/{peer_id}/config", response_model=ConfigRead)
async def get_config(peer_id: int, session: DBSession, admin: AdminDep) -> ConfigRead:
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
async def download_config(peer_id: int, session: DBSession, admin: AdminDep) -> Response:
    _ = admin
    peer = await session.get(Peer, peer_id)
    if not peer:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Peer not found")

    private_key = decrypt_private_key(peer.private_key_enc)
    config_body = wg.render_peer_config(private_key=private_key, address=peer.address)
    return Response(content=config_body, media_type="text/plain")

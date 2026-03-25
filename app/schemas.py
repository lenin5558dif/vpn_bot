from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models import PeerStatus, RequestStatus, Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    tg_id: Optional[int] = None
    name: str = Field(max_length=100)
    contact: Optional[str] = Field(default=None, max_length=200)


class UserRead(BaseModel):
    id: int
    tg_id: Optional[int]
    name: str
    contact: Optional[str]
    role: Role
    created_at: datetime
    last_login_at: Optional[datetime]

    model_config = {"from_attributes": True}


class RequestCreate(BaseModel):
    user_id: int
    comment: Optional[str] = Field(default=None, max_length=500)


class RequestRead(BaseModel):
    id: int
    user_id: int
    status: RequestStatus
    comment: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
    resolved_by: Optional[int]

    model_config = {"from_attributes": True}


class RequestUpdate(BaseModel):
    status: RequestStatus
    resolved_by: Optional[int] = None


class PeerCreate(BaseModel):
    user_id: int
    speed_limit_mbps: Optional[int] = None
    allowed_ips: Optional[str] = Field(default=None, max_length=50)


class PeerRead(BaseModel):
    id: int
    user_id: int
    iface: str
    public_key: str
    address: str
    allowed_ips: str
    status: PeerStatus
    speed_limit_mbps: int
    created_at: datetime
    updated_at: datetime
    last_handshake_at: Optional[datetime]

    model_config = {"from_attributes": True}


class PeerStatusUpdate(BaseModel):
    status: PeerStatus
    speed_limit_mbps: Optional[int] = None


class ConfigRead(BaseModel):
    id: int
    peer_id: int
    download_token: str
    expires_at: Optional[datetime]
    file_path: Optional[str]
    qr_data: Optional[str]

    model_config = {"from_attributes": True}


class TrafficRead(BaseModel):
    peer_id: int
    ts: datetime
    rx_bytes: int
    tx_bytes: int
    delta_rx: int
    delta_tx: int

    model_config = {"from_attributes": True}


class AuditRead(BaseModel):
    id: int
    action: str
    target_type: Optional[str]
    target_id: Optional[int]
    actor_id: Optional[int]
    ts: datetime
    ip: Optional[str]
    meta: Optional[dict]

    model_config = {"from_attributes": True}

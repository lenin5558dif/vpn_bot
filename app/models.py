from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import Index
from sqlmodel import Column, DateTime, Enum as PgEnum, Field, JSON, SQLModel


class Role(str, Enum):
    user = "user"
    admin = "admin"


class RequestStatus(str, Enum):
    new = "new"
    approved = "approved"
    rejected = "rejected"


class PeerStatus(str, Enum):
    pending = "pending"
    active = "active"
    disabled = "disabled"
    banned = "banned"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    tg_id: Optional[int] = Field(default=None, index=True)
    name: str
    contact: Optional[str] = Field(default=None)
    role: Role = Field(sa_column=Column(PgEnum(Role), nullable=False), default=Role.user)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False)))
    last_login_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=False)))


class Request(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    status: RequestStatus = Field(sa_column=Column(PgEnum(RequestStatus), nullable=False), default=RequestStatus.new)
    comment: Optional[str] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False)))
    resolved_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=False)))
    resolved_by: Optional[int] = Field(default=None, foreign_key="user.id")


class Peer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.id", index=True)
    iface: str = Field(default="wg0")
    public_key: str
    private_key_enc: str
    address: str
    allowed_ips: str
    status: PeerStatus = Field(sa_column=Column(PgEnum(PeerStatus), nullable=False), default=PeerStatus.pending)
    speed_limit_mbps: int = Field(default=20)
    created_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False)))
    updated_at: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False)))
    last_handshake_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=False)))


class Config(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    peer_id: int = Field(foreign_key="peer.id", index=True)
    download_token: str
    expires_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=False)))
    file_path: Optional[str] = None
    qr_data: Optional[str] = None


class TrafficStat(SQLModel, table=True):
    __table_args__ = (
        Index("ix_trafficstat_peer_ts", "peer_id", "ts"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    peer_id: int = Field(foreign_key="peer.id", index=True)
    ts: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False)))
    rx_bytes: int = Field(default=0)
    tx_bytes: int = Field(default=0)
    delta_rx: int = Field(default=0)
    delta_tx: int = Field(default=0)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_id: Optional[int] = Field(default=None, foreign_key="user.id")
    action: str
    target_type: Optional[str] = None
    target_id: Optional[int] = None
    ts: datetime = Field(default_factory=datetime.utcnow, sa_column=Column(DateTime(timezone=False)))
    ip: Optional[str] = None
    meta: Optional[dict] = Field(default=None, sa_column=Column(JSON))

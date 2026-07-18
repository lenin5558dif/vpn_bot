import pytest
from pydantic import ValidationError

from app.schemas import (
    UserCreate,
    UserRead,
    RequestCreate,
    RequestRead,
    RequestUpdate,
    PeerCreate,
    PeerRead,
    PeerStatusUpdate,
    ConfigRead,
    TrafficRead,
    AuditRead,
    TokenResponse,
    LoginRequest,
)
from app.models import PeerStatus, RequestStatus, Role


def test_user_create_valid():
    u = UserCreate(name="Test User", contact="test@mail.com", tg_id=123)
    assert u.name == "Test User"
    assert u.tg_id == 123


def test_user_create_name_max_length():
    with pytest.raises(ValidationError):
        UserCreate(name="x" * 101)


def test_user_create_contact_max_length():
    with pytest.raises(ValidationError):
        UserCreate(name="Test", contact="x" * 201)


def test_request_create_comment_max_length():
    with pytest.raises(ValidationError):
        RequestCreate(user_id=1, comment="x" * 501)


def test_request_create_valid():
    r = RequestCreate(user_id=1, comment="please")
    assert r.user_id == 1


def test_peer_create_valid():
    p = PeerCreate(user_id=1, speed_limit_mbps=10)
    assert p.speed_limit_mbps == 10


def test_peer_create_allowed_ips_max_length():
    with pytest.raises(ValidationError):
        PeerCreate(user_id=1, allowed_ips="x" * 201)


def test_peer_create_allowed_ips_rejects_non_cidr_value():
    with pytest.raises(ValidationError):
        PeerCreate(user_id=1, allowed_ips="not-a-network")


def test_peer_create_allowed_ips_normalizes_comma_separated_cidrs():
    p = PeerCreate(user_id=1, allowed_ips="10.10.0.2/32,  192.168.1.0/24")

    assert p.allowed_ips == "10.10.0.2/32, 192.168.1.0/24"


def test_peer_create_rejects_speed_limit_above_maximum():
    with pytest.raises(ValidationError):
        PeerCreate(user_id=1, speed_limit_mbps=1001)


def test_peer_status_update_rejects_negative_speed_limit():
    with pytest.raises(ValidationError):
        PeerStatusUpdate(status=PeerStatus.active, speed_limit_mbps=-1)


def test_peer_status_update():
    u = PeerStatusUpdate(status=PeerStatus.active, speed_limit_mbps=50)
    assert u.status == PeerStatus.active


def test_request_update():
    u = RequestUpdate(status=RequestStatus.approved, resolved_by=1)
    assert u.status == RequestStatus.approved


def test_token_response():
    t = TokenResponse(access_token="abc")
    assert t.token_type == "bearer"


def test_login_request():
    l = LoginRequest(username="admin", password="pass")
    assert l.username == "admin"

from app.config import get_settings, Settings, AppContext


def test_settings_loaded():
    s = get_settings()
    assert s.admin_username == "admin"
    assert s.jwt_alg == "HS256"
    assert s.wg_interface == "wg0"
    assert s.wg_mtu == 1420
    assert s.wg_keepalive == 25
    assert s.default_speed_limit_mbit == 20


def test_settings_fields():
    s = get_settings()
    assert s.backend_host == "0.0.0.0"
    assert s.backend_port == 8000
    assert s.cors_origins == "http://localhost:3000"


def test_app_context():
    s = get_settings()
    ctx = AppContext(settings=s)
    assert ctx.settings.admin_username == "admin"

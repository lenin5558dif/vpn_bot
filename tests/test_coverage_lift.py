import builtins
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest


def _callback(data: str, user_id: int = 123456789) -> AsyncMock:
    callback = AsyncMock()
    callback.from_user = MagicMock()
    callback.from_user.id = user_id
    callback.data = data
    callback.message = AsyncMock()
    callback.answer = AsyncMock()
    return callback


def _message(user_id: int | None = 111) -> AsyncMock:
    message = AsyncMock()
    message.answer = AsyncMock()
    message.from_user = None if user_id is None else MagicMock(id=user_id)
    return message


@pytest.mark.asyncio
async def test_cmd_start_returns_existing_new_request_status():
    from bot.main import cmd_start

    message = _message(777)
    state = AsyncMock()
    with patch("bot.main.backend") as backend:
        backend.get_user_by_tg_id = AsyncMock(return_value={"id": 5})
        backend.get_requests_by_user_id = AsyncMock(return_value=[{"id": 9, "status": "new"}])

        await cmd_start(message, state)

    message.answer.assert_called_once()
    assert "активная заявка" in message.answer.call_args.args[0]
    state.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_start_returns_existing_approved_request_status():
    from bot.main import cmd_start

    message = _message(777)
    state = AsyncMock()
    with patch("bot.main.backend") as backend:
        backend.get_user_by_tg_id = AsyncMock(return_value={"id": 5})
        backend.get_requests_by_user_id = AsyncMock(return_value=[{"id": 9, "status": "approved"}])

        await cmd_start(message, state)

    assert "конфиг" in message.answer.call_args.args[0]
    state.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_start_ignores_lookup_failure_and_starts_flow():
    from bot.main import RequestAccess, cmd_start

    message = _message(777)
    state = AsyncMock()
    with patch("bot.main.backend") as backend:
        backend.get_user_by_tg_id = AsyncMock(side_effect=Exception("backend down"))

        await cmd_start(message, state)

    message.answer.assert_called_with("Привет! Введи, пожалуйста, своё имя и фамилию.")
    state.set_state.assert_called_once_with(RequestAccess.waiting_name)


@pytest.mark.asyncio
async def test_cmd_start_returns_without_sender():
    from bot.main import cmd_start

    message = _message(None)
    state = AsyncMock()

    await cmd_start(message, state)

    message.answer.assert_not_called()
    state.set_state.assert_not_called()


@pytest.mark.asyncio
async def test_cmd_newrequest_resets_state():
    from bot.main import RequestAccess, cmd_newrequest

    message = _message()
    state = AsyncMock()

    await cmd_newrequest(message, state)

    state.clear.assert_called_once()
    message.answer.assert_called_once_with("Введи своё имя и фамилию.")
    state.set_state.assert_called_once_with(RequestAccess.waiting_name)


@pytest.mark.asyncio
async def test_cmd_status_reports_missing_user():
    from bot.main import cmd_status

    message = _message(777)
    with patch("bot.main.backend") as backend:
        backend.get_user_by_tg_id = AsyncMock(return_value=None)

        await cmd_status(message)

    assert "Заявок не найдено" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_status_reports_latest_status():
    from bot.main import cmd_status

    message = _message(777)
    with patch("bot.main.backend") as backend:
        backend.get_user_by_tg_id = AsyncMock(return_value={"id": 5})
        backend.get_requests_by_user_id = AsyncMock(return_value=[
            {"id": 1, "status": "new"},
            {"id": 2, "status": "rejected"},
        ])

        await cmd_status(message)

    assert "отклонена" in message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_cmd_status_handles_backend_error():
    from bot.main import cmd_status

    message = _message(777)
    with patch("bot.main.backend") as backend:
        backend.get_user_by_tg_id = AsyncMock(side_effect=Exception("boom"))

        await cmd_status(message)

    message.answer.assert_called_once_with("Не удалось получить статус. Попробуй позже.")


@pytest.mark.asyncio
async def test_skip_comment_submits_empty_comment_and_clears_keyboard():
    from bot.main import skip_comment

    callback = _callback("skip_comment", user_id=777)
    state = AsyncMock()
    with patch("bot.main._submit_request", new=AsyncMock()) as submit:
        await skip_comment(callback, state)

    callback.message.edit_reply_markup.assert_called_once_with(reply_markup=None)
    submit.assert_called_once_with(callback.message, state, comment="", tg_id=777)
    callback.answer.assert_called_once()


@pytest.mark.asyncio
async def test_handle_comment_without_sender_returns_error():
    from bot.main import handle_comment

    message = _message(None)
    message.text = "comment"
    state = AsyncMock()

    await handle_comment(message, state)

    message.answer.assert_called_once_with("Не удалось определить отправителя.")


@pytest.mark.asyncio
async def test_submit_request_handles_backend_failure():
    from bot.main import _submit_request

    message = _message(777)
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"name": "N", "contact": "C"})
    with patch("bot.main.backend") as backend:
        backend.create_user = AsyncMock(side_effect=Exception("db"))

        await _submit_request(message, state, "hello", 777)

    message.answer.assert_called_once_with("Ошибка при отправке заявки. Попробуй ещё раз.")
    state.clear.assert_not_called()


@pytest.mark.asyncio
async def test_submit_request_ignores_admin_notification_failure():
    from bot.main import _submit_request

    message = _message(777)
    state = AsyncMock()
    state.get_data = AsyncMock(return_value={"name": "N", "contact": "C"})
    with patch("bot.main.ADMIN_IDS", {1, 2}):
        with patch("bot.main.backend") as backend:
            backend.create_user = AsyncMock(return_value={"id": 7})
            backend.create_request = AsyncMock(return_value={"id": 8})
            with patch("bot.main.bot") as bot:
                bot.send_message = AsyncMock(side_effect=[Exception("blocked"), None])

                await _submit_request(message, state, "hello", 777)

    message.answer.assert_called_once_with("Заявка отправлена. Админ скоро её рассмотрит.")
    state.clear.assert_called_once()
    assert bot.send_message.call_count == 2


@pytest.mark.asyncio
async def test_approve_request_instruction_failure_still_marks_approved():
    from bot.main import RequestStatus, approve_request

    callback = _callback("approve:1:2:333")
    with patch("bot.main.backend") as backend:
        backend.list_peers = AsyncMock(return_value=[])
        backend.create_peer = AsyncMock(return_value={"id": 10})
        backend.get_config = AsyncMock(return_value="[Interface]\nPrivateKey=x")
        backend.get_user = AsyncMock(return_value={"name": "User"})
        backend.update_request = AsyncMock()
        with patch("bot.main.bot") as bot:
            bot.send_message = AsyncMock(side_effect=[None, Exception("telegram")])
            bot.send_document = AsyncMock()

            await approve_request(callback)

    backend.update_request.assert_called_once_with(1, RequestStatus.approved)
    callback.answer.assert_called_with("Одобрено")


@pytest.mark.asyncio
async def test_approve_request_status_update_failure_reports_reusable_peer():
    from bot.main import approve_request

    callback = _callback("approve:1:2:333")
    with patch("bot.main.backend") as backend:
        backend.list_peers = AsyncMock(return_value=[{"id": 10, "status": "disabled"}])
        backend.update_peer_status = AsyncMock(
            return_value={"id": 10, "user_id": 2, "status": "active"}
        )
        backend.create_peer = AsyncMock()
        backend.get_config = AsyncMock(return_value="[Interface]\nPrivateKey=x")
        backend.get_user = AsyncMock(return_value={"name": "User"})
        backend.update_request = AsyncMock(side_effect=Exception("db"))
        with patch("bot.main.bot") as bot:
            bot.send_message = AsyncMock()
            bot.send_document = AsyncMock()

            await approve_request(callback)

    backend.create_peer.assert_not_called()
    callback.answer.assert_called_with("Выдано, статус не обновлён", show_alert=True)


@pytest.mark.asyncio
async def test_reject_request_bad_data_returns_alert():
    from bot.main import reject_request

    callback = _callback("reject:bad")

    await reject_request(callback)

    callback.answer.assert_called_once_with("Некорректные данные", show_alert=True)


@pytest.mark.asyncio
async def test_reject_request_backend_error_returns_alert():
    from bot.main import reject_request

    callback = _callback("reject:1:2:333")
    with patch("bot.main.backend") as backend:
        backend.update_request = AsyncMock(side_effect=Exception("db"))

        await reject_request(callback)

    callback.answer.assert_called_once_with("Ошибка отказа", show_alert=True)


@pytest.mark.asyncio
async def test_user_names_returns_empty_when_backend_fails():
    from bot.main import _user_names

    with patch("bot.main.backend") as backend:
        backend.list_users = AsyncMock(side_effect=Exception("db"))

        assert await _user_names() == {}


@pytest.mark.asyncio
async def test_admin_actions_online_traffic_top_and_server_branches():
    from bot.main import admin_actions

    cases = [
        (
            "admin:online",
            {
                "get_online_peers": AsyncMock(return_value={
                    "online_count": 1,
                    "total": 2,
                    "peers": [{"name": "U", "address": "10.0.0.2", "seconds_ago": 90}],
                })
            },
            "Онлайн",
        ),
        (
            "admin:traffic",
            {"get_traffic_summary": AsyncMock(return_value=[{"user_id": 1, "name": "U", "rx": 1024 ** 3, "tx": 0}])},
            "Трафик",
        ),
        (
            "admin:top",
            {"get_traffic_summary": AsyncMock(return_value=[{"user_id": 1, "name": "U", "rx": 1, "tx": 2}])},
            "Топ-5",
        ),
        (
            "admin:server",
            {"get_server_stats": AsyncMock(return_value={
                "cpu_pct": 1,
                "cpu_cores": 2,
                "ram_used_mb": 3,
                "ram_total_mb": 4,
                "disk_used_gb": 5,
                "disk_total_gb": 6,
                "uptime": "7d 8h",
                "peers_total": 9,
                "trafficstat_rows": 10,
            })},
            "Сервер",
        ),
    ]
    for data, attrs, expected in cases:
        callback = _callback(data)
        with patch("bot.main.backend") as backend:
            for name, value in attrs.items():
                setattr(backend, name, value)

            await admin_actions(callback)

        assert expected in callback.message.answer.call_args.args[0]
        callback.answer.assert_called_once()


@pytest.mark.asyncio
async def test_admin_actions_online_and_traffic_empty_branches():
    from bot.main import admin_actions

    callback = _callback("admin:online")
    with patch("bot.main.backend") as backend:
        backend.get_online_peers = AsyncMock(return_value={"online_count": 0, "total": 1, "peers": []})
        await admin_actions(callback)
    assert "Никого нет" in callback.message.answer.call_args.args[0]

    callback = _callback("admin:traffic")
    with patch("bot.main.backend") as backend:
        backend.get_traffic_summary = AsyncMock(return_value=[])
        await admin_actions(callback)
    assert "Нет данных" in callback.message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_admin_actions_users_with_peers_adds_bulk_controls():
    from bot.main import admin_actions

    callback = _callback("admin:users")
    with patch("bot.main.backend") as backend:
        backend.list_users = AsyncMock(return_value=[{"id": 1, "name": "U", "contact": None}])
        backend.list_peers = AsyncMock(return_value=[{"id": 5, "user_id": 1, "status": "active"}])

        await admin_actions(callback)

    assert callback.message.answer.call_count == 2
    assert callback.message.answer.call_args.kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_admin_ban_ask_confirm_cancel_and_error_branches():
    from bot.main import admin_ban_ask, admin_ban_cancel, admin_ban_confirm

    bad = _callback("admin:peer:ban_ask:bad")
    await admin_ban_ask(bad)
    bad.answer.assert_called_once_with("Некорректный запрос", show_alert=True)

    ask = _callback("admin:peer:ban_ask:5")
    await admin_ban_ask(ask)
    ask.message.answer.assert_called_once()
    ask.answer.assert_called_once()

    confirm = _callback("admin:peer:ban_ok:5")
    with patch("bot.main.backend") as backend:
        backend.update_peer_status = AsyncMock()
        await admin_ban_confirm(confirm)
    confirm.message.answer.assert_called_with("⛔ Peer #5 забанен.")

    failed = _callback("admin:peer:ban_ok:5")
    with patch("bot.main.backend") as backend:
        backend.update_peer_status = AsyncMock(side_effect=Exception("wg"))
        await admin_ban_confirm(failed)
    assert "Ошибка при бане" in failed.message.answer.call_args.args[0]

    cancel = _callback("admin:peer:ban_cancel:5")
    await admin_ban_cancel(cancel)
    cancel.message.answer.assert_called_once_with("Бан отменён.")


@pytest.mark.asyncio
async def test_admin_user_toggle_validation_empty_partial_and_backend_error_branches():
    from bot.main import admin_user_toggle

    bad = _callback("admin:user:bad")
    await admin_user_toggle(bad)
    bad.answer.assert_called_once_with("Некорректный запрос", show_alert=True)

    invalid_status = _callback("admin:user:1:banned")
    await admin_user_toggle(invalid_status)
    invalid_status.answer.assert_called_once_with("Недопустимый статус", show_alert=True)

    empty = _callback("admin:user:1:disabled")
    with patch("bot.main.backend") as backend:
        backend.list_peers = AsyncMock(return_value=[{"id": 9, "user_id": 1, "status": "banned"}])
        await admin_user_toggle(empty)
    assert "нет управляемых" in empty.message.answer.call_args.args[0]

    partial = _callback("admin:user:1:disabled")
    with patch("bot.main.backend") as backend:
        backend.list_peers = AsyncMock(return_value=[
            {"id": 1, "user_id": 1, "status": "active"},
            {"id": 2, "user_id": 1, "status": "disabled"},
        ])
        backend.update_peer_status = AsyncMock(side_effect=[None, Exception("fail")])
        await admin_user_toggle(partial)
    assert "1/2" in partial.message.answer.call_args.args[0]

    failed = _callback("admin:user:1:disabled")
    with patch("bot.main.backend") as backend:
        backend.list_peers = AsyncMock(side_effect=Exception("db"))
        await admin_user_toggle(failed)
    assert "Ошибка при обновлении" in failed.message.answer.call_args.args[0]


@pytest.mark.asyncio
async def test_bot_main_closes_backend_after_polling():
    from bot.main import main

    with patch("bot.main.dp") as dp:
        dp.start_polling = AsyncMock(side_effect=Exception("stop"))
        with patch("bot.main.backend") as backend:
            backend.close = AsyncMock()
            with pytest.raises(Exception, match="stop"):
                await main()

    backend.close.assert_called_once()


@pytest.mark.asyncio
async def test_health_reports_wireguard_timeout_and_kills_process(client):
    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=TimeoutError)
    proc.kill = MagicMock()
    proc.wait = AsyncMock()
    with patch("app.api.health.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        resp = await client.get("/health")

    assert resp.json()["checks"]["wireguard"] == "timeout"
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_health_reports_wireguard_error_returncode(client):
    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"", b"bad"))
    proc.returncode = 1
    with patch("app.api.health.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        resp = await client.get("/health")

    data = resp.json()
    assert data["status"] == "degraded"
    assert data["checks"]["wireguard"] == "error"


@pytest.mark.asyncio
async def test_health_reports_db_error_and_awg_unavailable():
    from app.api import health as health_module

    class BrokenConnect:
        async def __aenter__(self):
            raise RuntimeError("db")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    fake_engine = SimpleNamespace(connect=lambda: BrokenConnect())
    with patch.object(health_module, "engine", fake_engine):
        with patch("app.api.health.asyncio.create_subprocess_exec", new=AsyncMock(side_effect=OSError("no awg"))):
            result = await health_module.health()

    assert result == {"status": "degraded", "checks": {"db": "error", "wireguard": "unavailable"}}


@pytest.mark.asyncio
async def test_server_stats_reads_system_and_db_values():
    from app.api import health as health_module

    class Stat:
        f_blocks = 10
        f_frsize = 1024 ** 3
        f_bavail = 4

    class Result:
        def __init__(self, value):
            self.value = value

        def scalar(self):
            return self.value

    class Conn:
        def __init__(self):
            self.values = [Result(3), Result(11)]

        async def execute(self, _stmt):
            return self.values.pop(0)

    class ConnManager:
        async def __aenter__(self):
            return Conn()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def fake_open(path, *args, **kwargs):
        if path == "/proc/meminfo":
            return mock_open(read_data="MemTotal: 4096 kB\nMemAvailable: 1024 kB\n")()
        if path == "/proc/uptime":
            return mock_open(read_data="90000.00 1.00\n")()
        raise FileNotFoundError(path)

    with patch("os.getloadavg", return_value=(1.0, 0.0, 0.0)):
        with patch("os.cpu_count", return_value=2):
            with patch("os.statvfs", return_value=Stat()):
                with patch.object(builtins, "open", side_effect=fake_open):
                    fake_engine = SimpleNamespace(connect=lambda: ConnManager())
                    with patch.object(health_module, "engine", fake_engine):
                        stats = await health_module.server_stats(admin=object())

    assert stats["cpu_pct"] == 50.0
    assert stats["ram_used_mb"] == 3
    assert stats["disk_used_gb"] == 6
    assert stats["uptime"] == "1d 1h"
    assert stats["peers_total"] == 3
    assert stats["trafficstat_rows"] == 11


@pytest.mark.asyncio
async def test_server_stats_falls_back_on_system_errors():
    from app.api import health as health_module

    class BrokenConnect:
        async def __aenter__(self):
            raise RuntimeError("db")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch("os.getloadavg", side_effect=OSError):
        with patch("os.statvfs", side_effect=OSError):
            with patch.object(builtins, "open", side_effect=OSError):
                fake_engine = SimpleNamespace(connect=lambda: BrokenConnect())
                with patch.object(health_module, "engine", fake_engine):
                    stats = await health_module.server_stats(admin=object())

    assert stats["cpu_pct"] == 0
    assert stats["ram_total_mb"] == 0
    assert stats["disk_total_gb"] == 0
    assert stats["uptime"] == "unknown"
    assert stats["peers_total"] == 0


@pytest.mark.asyncio
async def test_request_size_middleware_rejects_invalid_and_large_lengths(client):
    invalid = await client.get("/", headers={"content-length": "abc"})
    large = await client.get("/", headers={"content-length": "1000001"})

    assert invalid.status_code == 400
    assert large.status_code == 413


@pytest.mark.asyncio
async def test_security_headers_middleware_adds_headers(client):
    resp = await client.get("/")

    assert resp.headers["X-Content-Type-Options"] == "nosniff"
    assert resp.headers["X-Frame-Options"] == "DENY"
    assert resp.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"


def test_validate_config_reports_all_missing_required_values():
    from app import main as app_main

    original = {
        "encryption_key": app_main.settings.encryption_key,
        "server_public_key": app_main.settings.server_public_key,
        "admin_password_hash": app_main.settings.admin_password_hash,
        "bot_api_key": app_main.settings.bot_api_key,
        "jwt_secret": app_main.settings.jwt_secret,
    }
    try:
        app_main.settings.encryption_key = ""
        app_main.settings.server_public_key = ""
        app_main.settings.admin_password_hash = ""
        app_main.settings.bot_api_key = ""
        app_main.settings.jwt_secret = "change_me"
        with pytest.raises(RuntimeError) as exc:
            app_main._validate_config()
    finally:
        for key, value in original.items():
            setattr(app_main.settings, key, value)

    message = str(exc.value)
    assert "ENCRYPTION_KEY" in message
    assert "SERVER_PUBLIC_KEY" in message
    assert "JWT_SECRET" in message


@pytest.mark.asyncio
async def test_lifespan_starts_and_stops_poller():
    from app import main as app_main

    calls = {"init": 0, "stop": 0}

    async def fake_init_db():
        calls["init"] += 1

    async def fake_stop():
        calls["stop"] += 1

    with patch.object(app_main, "_validate_config") as validate:
        with patch.object(app_main, "init_db", fake_init_db):
            with patch.object(app_main.poller, "start") as start:
                with patch.object(app_main.poller, "stop", fake_stop):
                    async with app_main.lifespan(app_main.app):
                        validate.assert_called_once()
                        assert calls["init"] == 1
                        start.assert_called_once()

    assert calls["stop"] == 1


@pytest.mark.asyncio
async def test_traffic_poller_run_logs_collect_and_cleanup_errors():
    from app.tasks import TrafficPoller

    poller = TrafficPoller(MagicMock(), "wg0")
    poller.collect = AsyncMock(side_effect=[Exception("collect"), None])
    poller.cleanup = AsyncMock(side_effect=Exception("cleanup"))

    async def fake_sleep(_seconds):
        raise asyncio.CancelledError

    import asyncio

    with patch("app.tasks.asyncio.sleep", new=AsyncMock(side_effect=fake_sleep)):
        with pytest.raises(asyncio.CancelledError):
            poller._run.__globals__["cycle"] = 59
            await poller._run()

    poller.collect.assert_called_once()


@pytest.mark.asyncio
async def test_traffic_poller_collect_timeout_kills_process():
    from app.tasks import TrafficPoller

    proc = MagicMock()
    proc.communicate = AsyncMock(side_effect=TimeoutError)
    proc.kill = MagicMock()
    with patch("app.tasks.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        poller = TrafficPoller(MagicMock(), "wg0")
        await poller.collect()

    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_traffic_poller_collect_parses_native_transfer_format(session):
    from app.database import SessionLocal
    from app.models import Peer, PeerStatus, Role, TrafficStat, User
    from app.tasks import TrafficPoller
    from sqlmodel import select

    user = User(name="Traffic Native", role=Role.user)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    peer = Peer(
        user_id=user.id,
        iface="wg0",
        public_key="pub-native",
        private_key_enc="enc",
        address="10.10.0.9/32",
        allowed_ips="10.10.0.9/32",
        status=PeerStatus.active,
    )
    session.add(peer)
    await session.commit()
    await session.refresh(peer)
    session.add(TrafficStat(peer_id=peer.id, rx_bytes=5000, tx_bytes=5000, delta_rx=0, delta_tx=0))
    await session.commit()

    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"peer: pub-native\n  transfer: 4000 B received, 8000 B sent\n", b""))
    proc.returncode = 0
    with patch("app.tasks.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        await TrafficPoller(SessionLocal, "wg0").collect()

    result = await session.exec(select(TrafficStat).where(TrafficStat.peer_id == peer.id).order_by(TrafficStat.id))
    latest = result.all()[-1]
    assert latest.delta_rx == 0
    assert latest.delta_tx == 3000


@pytest.mark.asyncio
async def test_wg_generate_keys_rejects_empty_key_outputs():
    from app.wg import WireGuardError, WireGuardManager

    wg = WireGuardManager()
    with patch.object(wg, "_run", new=AsyncMock(return_value="")):
        with pytest.raises(WireGuardError, match="empty private"):
            await wg.generate_keys()

    with patch.object(wg, "_run", new=AsyncMock(side_effect=["priv\n", ""])):
        with pytest.raises(WireGuardError, match="empty public"):
            await wg.generate_keys()


def test_wg_allocate_ip_raises_when_pool_is_exhausted():
    from app import wg as wg_module
    from app.wg import WireGuardManager

    old_network = wg_module.settings.wg_network
    wg_module.settings.wg_network = "10.10.0.0/30"
    try:
        with pytest.raises(RuntimeError, match="No free IP"):
            WireGuardManager().allocate_ip(["10.10.0.2/32"])
    finally:
        wg_module.settings.wg_network = old_network


def test_wg_render_peer_config_requires_server_public_key():
    from app import wg as wg_module
    from app.wg import WireGuardManager

    old_key = wg_module.settings.server_public_key
    wg_module.settings.server_public_key = ""
    try:
        with pytest.raises(ValueError, match="SERVER_PUBLIC_KEY"):
            WireGuardManager().render_peer_config("priv", "10.10.0.2/32")
    finally:
        wg_module.settings.server_public_key = old_key


@pytest.mark.asyncio
async def test_wg_get_latest_handshakes_parses_valid_lines_and_ignores_invalid():
    from app.wg import WireGuardManager

    wg = WireGuardManager()
    with patch.object(wg, "_run", new=AsyncMock(return_value="pk1 123\npk2 nope\nbad line extra\npk3 456\n")):
        result = await wg.get_latest_handshakes()

    assert result == {"pk1": 123, "pk3": 456}


@pytest.mark.asyncio
async def test_wg_get_latest_handshakes_returns_empty_on_failure():
    from app.wg import WireGuardManager

    wg = WireGuardManager()
    with patch.object(wg, "_run", new=AsyncMock(side_effect=Exception("awg"))):
        assert await wg.get_latest_handshakes() == {}


@pytest.mark.asyncio
async def test_wg_run_non_check_failure_returns_stdout():
    from app.wg import WireGuardManager

    proc = MagicMock()
    proc.communicate = AsyncMock(return_value=(b"out", b"warn"))
    proc.returncode = 2
    with patch("app.wg.asyncio.create_subprocess_exec", new=AsyncMock(return_value=proc)):
        result = await WireGuardManager()._run("tc", "qdisc", check=False)

    assert result == "out"

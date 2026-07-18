import json
import os
from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings
from bot.alerts import AlertManager


class FakeBackend:
    def __init__(self) -> None:
        self.health = AsyncMock(return_value={"status": "ok", "checks": {"wireguard": "ok"}})
        self.get_server_stats = AsyncMock(return_value={"disk_used_pct": 10, "disk_used_gb": 1, "disk_total_gb": 10})
        self.reconcile_peers = AsyncMock(return_value={
            "status": "ok",
            "wg_available": True,
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
        })
        self.get_traffic_summary = AsyncMock(return_value=[])


def make_manager(tmp_path, backend=None, *, admin_ids=None) -> AlertManager:
    settings = Settings(
        alerts_state_file=str(tmp_path / "alerts.json"),
        alerts_failure_threshold=3,
        alerts_diagnostic_interval_sec=0,
        alerts_repeat_hours=6,
        alerts_disk_warn_pct=80,
        alerts_disk_recovery_pct=75,
        alerts_traffic_24h_threshold_gb=1,
    )
    bot = AsyncMock()
    return AlertManager(bot=bot, backend=backend or FakeBackend(), admin_ids=admin_ids or {1, 2}, settings=settings)


@pytest.mark.asyncio
async def test_repeating_alert_respects_cooldown_until_fingerprint_changes(tmp_path):
    backend = FakeBackend()
    backend.reconcile_peers = AsyncMock(return_value={
        "status": "drift",
        "wg_available": True,
        "counts": {"unknown_wg_peers": 1, "missing_wg_peers": 0, "allowed_ips_mismatch": 0, "disabled_with_allowed_ips": 0},
        "unknown_wg_peers": [{"public_key_fingerprint": "one"}],
    })
    second_path = tmp_path / "wireguard"
    second_path.mkdir()
    manager = make_manager(second_path, backend)

    await manager.run_once()
    first_count = manager.bot.send_message.await_count
    await manager.run_once()
    same_fingerprint_count = manager.bot.send_message.await_count
    backend.reconcile_peers = AsyncMock(return_value={
        "status": "drift",
        "wg_available": True,
        "counts": {"unknown_wg_peers": 1, "missing_wg_peers": 0, "allowed_ips_mismatch": 0, "disabled_with_allowed_ips": 0},
        "unknown_wg_peers": [{"public_key_fingerprint": "two"}],
    })
    await manager.run_once()

    assert first_count == 2
    assert same_fingerprint_count == first_count
    assert manager.bot.send_message.await_count == first_count + 2


@pytest.mark.asyncio
async def test_failed_alert_delivery_is_retried_per_admin(tmp_path):
    manager = make_manager(tmp_path, admin_ids={1, 2})
    manager.bot.send_message.side_effect = [RuntimeError("telegram"), None, None]

    await manager._send_repeating_alert("backend_down", "🚨 Backend недоступен", "down")
    first_deliveries = dict(manager.state["deliveries"]["backend_down"])
    await manager._send_repeating_alert("backend_down", "🚨 Backend недоступен", "down")

    assert len(first_deliveries) == 1
    assert len(manager.state["deliveries"]["backend_down"]) == 2
    assert manager.bot.send_message.await_count == 3


@pytest.mark.asyncio
async def test_recovery_waits_until_all_admins_receive_message(tmp_path):
    manager = make_manager(tmp_path, admin_ids={1, 2})
    manager.state["events"] = {"db_wg_drift": {"active": True}}
    manager.bot.send_message.side_effect = [RuntimeError("telegram"), None, None]

    await manager._send_recovery("db_wg_drift", "✅ recovered")
    assert manager.state["events"]["db_wg_drift"]["active"] is True

    await manager._send_recovery("db_wg_drift", "✅ recovered")
    assert manager.state["events"]["db_wg_drift"]["active"] is False


@pytest.mark.asyncio
async def test_disk_alert_uses_recovery_hysteresis(tmp_path):
    backend = FakeBackend()
    wireguard_path = tmp_path / "wireguard-threshold"
    wireguard_path.mkdir()
    manager = make_manager(wireguard_path, backend)

    backend.get_server_stats = AsyncMock(return_value={"disk_used_pct": 81, "disk_used_gb": 81, "disk_total_gb": 100})
    await manager.run_once()
    assert manager.state["events"]["disk_high"]["active"] is True

    backend.get_server_stats = AsyncMock(return_value={"disk_used_pct": 77, "disk_used_gb": 77, "disk_total_gb": 100})
    await manager.run_once()
    assert manager.state["events"]["disk_high"]["active"] is True

    backend.get_server_stats = AsyncMock(return_value={"disk_used_pct": 74, "disk_used_gb": 74, "disk_total_gb": 100})
    await manager.run_once()
    assert manager.state["events"]["disk_high"]["active"] is False


@pytest.mark.asyncio
async def test_reconcile_unavailable_does_not_recover_existing_unknown_or_drift_incidents(tmp_path):
    backend = FakeBackend()
    backend.reconcile_peers = AsyncMock(return_value={
        "status": "wireguard_unavailable",
        "wg_available": False,
        "counts": {
            "unknown_wg_peers": 0,
            "missing_wg_peers": 0,
            "allowed_ips_mismatch": 0,
            "disabled_with_allowed_ips": 0,
        },
    })
    wireguard_path = tmp_path / "wireguard-threshold"
    wireguard_path.mkdir()
    manager = make_manager(wireguard_path, backend)
    manager.state["events"] = {
        "unknown_wg_peer": {"active": True},
        "db_wg_drift": {"active": True},
    }

    await manager.run_once()

    assert manager.state["events"]["unknown_wg_peer"]["active"] is True
    assert manager.state["events"]["db_wg_drift"]["active"] is True
    recovery_texts = [call.args[1] for call in manager.bot.send_message.await_args_list]
    assert not any("снова согласованы" in text or "больше нет" in text for text in recovery_texts)


@pytest.mark.asyncio
async def test_traffic_alert_is_sent_once_per_admin_per_day(tmp_path):
    backend = FakeBackend()
    backend.get_traffic_summary = AsyncMock(return_value=[
        {"user_id": 7, "name": "Alice", "rx": 2 * 1024 ** 3, "tx": 0},
    ])
    second_path = tmp_path / "wireguard-threshold"
    second_path.mkdir()
    manager = make_manager(second_path, backend)

    await manager.run_once()
    await manager.run_once()

    traffic_calls = [
        call for call in manager.bot.send_message.await_args_list
        if "Аномально большой трафик" in call.args[1]
    ]
    assert len(traffic_calls) == 2


def test_state_loads_existing_dict_and_rejects_non_dict(tmp_path):
    path = tmp_path / "alerts.json"
    path.write_text(json.dumps({"events": {"x": {"active": True}}}), encoding="utf-8")
    manager = make_manager(tmp_path)
    assert manager.state["events"]["x"]["active"] is True

    path.write_text(json.dumps(["not", "dict"]), encoding="utf-8")
    manager = make_manager(tmp_path)
    assert manager.state == {}


@pytest.mark.asyncio
async def test_save_state_creates_0600_file(tmp_path):
    manager = make_manager(tmp_path)
    manager.state = {"deliveries": {"x": {"1": 1}}}

    manager._save_state()

    path = tmp_path / "alerts.json"
    assert json.loads(path.read_text(encoding="utf-8")) == manager.state
    assert oct(os.stat(path).st_mode & 0o777) == "0o600"


@pytest.mark.asyncio
async def test_backend_and_wireguard_alert_after_threshold_three(tmp_path):
    backend = FakeBackend()
    wg_path = tmp_path / "wireguard-only"
    wg_path.mkdir()
    manager = make_manager(wg_path, backend)

    backend.health = AsyncMock(side_effect=RuntimeError("down"))
    await manager.run_once()
    await manager.run_once()
    assert manager.bot.send_message.await_count == 0
    await manager.run_once()
    assert manager.bot.send_message.await_count == 2

    manager = make_manager(tmp_path, backend)
    backend.health = AsyncMock(return_value={"status": "degraded", "checks": {"wireguard": "error"}})
    await manager.run_once()
    await manager.run_once()
    assert manager.bot.send_message.await_count == 0
    await manager.run_once()
    assert manager.bot.send_message.await_count == 2

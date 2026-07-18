from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from aiogram import Bot

from app.config import Settings
from bot.backend import BackendClient

logger = logging.getLogger(__name__)


class AlertManager:
    def __init__(
        self,
        *,
        bot: Bot,
        backend: BackendClient,
        admin_ids: set[int],
        settings: Settings,
    ) -> None:
        self.bot = bot
        self.backend = backend
        self.admin_ids = admin_ids
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._last_diagnostics_at = 0.0
        self.state: dict[str, Any] = self._load_state()

    def start(self) -> None:
        if not self.settings.alerts_enabled or self._task:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="bot-alert-manager")

    async def stop(self) -> None:
        if not self._task:
            return
        self._stop.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None
            self._save_state()

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self.run_once()
            except Exception:
                logger.exception("Alert check iteration failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(),
                    timeout=max(1, self.settings.alerts_health_interval_sec),
                )
            except TimeoutError:
                pass

    async def run_once(self) -> None:
        if not self.settings.alerts_enabled:
            return
        backend_available, health = await self._check_backend()
        if not backend_available:
            self._save_state()
            return

        await self._check_wireguard(health)
        now = time.time()
        if now - self._last_diagnostics_at >= self.settings.alerts_diagnostic_interval_sec:
            self._last_diagnostics_at = now
            await self._check_diagnostics()
        self._save_state()

    async def _check_backend(self) -> tuple[bool, dict[str, Any] | None]:
        try:
            health = await self.backend.health()
        except Exception as exc:
            logger.warning("Backend health check failed: %s", exc)
            failures = self._counter_inc("backend_failures")
            if failures >= self.settings.alerts_failure_threshold:
                await self._send_repeating_alert(
                    "backend_down",
                    "🚨 Backend недоступен",
                    f"Backend не отвечает {failures} проверок подряд.",
                )
            return False, None

        self._counter_reset("backend_failures")
        await self._send_recovery("backend_down", "✅ Backend снова доступен")
        return True, health

    async def _check_wireguard(self, health: dict[str, Any] | None) -> None:
        wg_status = (health or {}).get("checks", {}).get("wireguard")
        if wg_status != "ok":
            failures = self._counter_inc("wg_failures")
            if failures >= self.settings.alerts_failure_threshold:
                await self._send_repeating_alert(
                    "wireguard_down",
                    "🚨 WireGuard недоступен",
                    f"WireGuard status={wg_status or 'unknown'} уже {failures} проверок подряд.",
                )
            return
        self._counter_reset("wg_failures")
        await self._send_recovery("wireguard_down", "✅ WireGuard снова доступен")

    async def _check_diagnostics(self) -> None:
        stats = await self.backend.get_server_stats()
        disk_pct = float(stats.get("disk_used_pct") or 0)
        if disk_pct >= self.settings.alerts_disk_warn_pct:
            await self._send_repeating_alert(
                "disk_high",
                "🚨 Диск заполнен",
                f"Занято {disk_pct:.1f}% диска. Порог: {self.settings.alerts_disk_warn_pct:.1f}%.",
            )
        elif disk_pct < self.settings.alerts_disk_recovery_pct:
            await self._send_recovery("disk_high", f"✅ Диск снова в норме: {disk_pct:.1f}%")

        reconcile = await self.backend.reconcile_peers()
        if not reconcile.get("wg_available", False):
            # A failed runtime snapshot must not close existing reconciliation
            # incidents: absence of evidence is not evidence of recovery.
            await self._check_traffic()
            return
        counts = reconcile.get("counts", {})
        unknown_count = int(counts.get("unknown_wg_peers") or 0)
        drift_count = (
            int(counts.get("missing_wg_peers") or 0)
            + int(counts.get("allowed_ips_mismatch") or 0)
            + int(counts.get("disabled_with_allowed_ips") or 0)
        )
        if unknown_count:
            unknown_fingerprint = self._fingerprint(reconcile.get("unknown_wg_peers", []))
            await self._send_repeating_alert(
                "unknown_wg_peer",
                "🚨 В WireGuard появился неизвестный peer",
                f"Неизвестных WG peer-ов: {unknown_count}. Автоудаление не выполнялось.",
                fingerprint=unknown_fingerprint,
            )
        else:
            await self._send_recovery("unknown_wg_peer", "✅ Неизвестных WG peer-ов больше нет")
        if drift_count:
            drift_fingerprint = self._fingerprint({
                "missing": reconcile.get("missing_wg_peers", []),
                "mismatch": reconcile.get("allowed_ips_mismatch", []),
                "disabled": reconcile.get("disabled_with_allowed_ips", []),
            })
            await self._send_repeating_alert(
                "db_wg_drift",
                "🚨 БД и WireGuard расходятся",
                (
                    f"missing={counts.get('missing_wg_peers', 0)}, "
                    f"allowed_ips mismatch={counts.get('allowed_ips_mismatch', 0)}, "
                    f"disabled nonempty={counts.get('disabled_with_allowed_ips', 0)}"
                ),
                fingerprint=drift_fingerprint,
            )
        else:
            await self._send_recovery("db_wg_drift", "✅ БД и WireGuard снова согласованы")

        await self._check_traffic()

    async def _check_traffic(self) -> None:
        items = await self.backend.get_traffic_summary(hours=24)
        by_user: dict[int, dict[str, Any]] = {}
        for item in items:
            user_id = int(item.get("user_id") or 0)
            if not user_id:
                continue
            bucket = by_user.setdefault(user_id, {"name": item.get("name"), "bytes": 0})
            bucket["bytes"] += int(item.get("rx") or 0) + int(item.get("tx") or 0)

        threshold = self.settings.alerts_traffic_24h_threshold_gb * 1024 ** 3
        day = datetime.utcnow().strftime("%Y-%m-%d")
        deliveries = self.state.setdefault("deliveries", {})
        for key in list(deliveries):
            if key.startswith("traffic_24h:") and not key.endswith(f":{day}"):
                deliveries.pop(key, None)
        for user_id, data in by_user.items():
            total = int(data["bytes"])
            if total < threshold:
                continue
            event_key = f"traffic_24h:{user_id}:{day}"
            gb = total / (1024 ** 3)
            await self._deliver(
                event_key,
                (
                    "🚨 Аномально большой трафик за 24ч\n"
                    f"Пользователь #{user_id} {data.get('name') or ''}: {gb:.1f} ГБ. "
                    f"Порог: {self.settings.alerts_traffic_24h_threshold_gb} ГБ."
                ),
                skip_delivered=True,
            )

    def _counter_inc(self, key: str) -> int:
        counters = self.state.setdefault("counters", {})
        counters[key] = int(counters.get(key, 0)) + 1
        return counters[key]

    def _counter_reset(self, key: str) -> None:
        self.state.setdefault("counters", {})[key] = 0

    async def _send_repeating_alert(
        self,
        key: str,
        title: str,
        body: str,
        *,
        fingerprint: str | None = None,
    ) -> None:
        event = self.state.setdefault("events", {}).setdefault(key, {})
        was_active = bool(event.get("active"))
        fingerprint_changed = bool(
            fingerprint is not None
            and event.get("fingerprint") is not None
            and event.get("fingerprint") != fingerprint
        )
        event["active"] = True
        if fingerprint is not None:
            event["fingerprint"] = fingerprint
        if not was_active:
            self.state.setdefault("deliveries", {}).pop(f"{key}:recovery", None)
        if fingerprint_changed:
            self.state.setdefault("deliveries", {}).pop(key, None)
        await self._deliver(key, f"{title}\n{body}", repeat=True)

    async def _send_recovery(self, key: str, text: str) -> None:
        event = self.state.setdefault("events", {}).setdefault(key, {})
        if not event.get("active"):
            return
        recovery_key = f"{key}:recovery"
        await self._deliver(recovery_key, text, skip_delivered=True)
        delivered = self.state.setdefault("deliveries", {}).get(recovery_key, {})
        if all(str(admin_id) in delivered for admin_id in self.admin_ids):
            event["active"] = False
            event.pop("fingerprint", None)
            self.state.setdefault("deliveries", {}).pop(key, None)
            self.state.setdefault("deliveries", {}).pop(recovery_key, None)

    async def _deliver(
        self,
        key: str,
        text: str,
        *,
        repeat: bool = False,
        skip_delivered: bool = False,
    ) -> set[int]:
        now = int(time.time())
        repeat_after = self.settings.alerts_repeat_hours * 3600
        deliveries = self.state.setdefault("deliveries", {}).setdefault(key, {})
        successful: set[int] = set()
        for admin_id in self.admin_ids:
            admin_key = str(admin_id)
            last_sent = int(deliveries.get(admin_key, 0) or 0)
            if skip_delivered and last_sent:
                successful.add(admin_id)
                continue
            if repeat and last_sent and now - last_sent < repeat_after:
                successful.add(admin_id)
                continue
            try:
                await self.bot.send_message(admin_id, text)
            except Exception as exc:
                logger.error("Failed to send alert %s to admin %s: %s", key, admin_id, exc)
                continue
            deliveries[admin_key] = now
            successful.add(admin_id)
        return successful

    @staticmethod
    def _fingerprint(value: Any) -> str:
        payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _load_state(self) -> dict[str, Any]:
        path = Path(self.settings.alerts_state_file)
        try:
            with path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except FileNotFoundError:
            return {}
        except Exception:
            logger.warning("Failed to read alert state file %s", path)
            return {}

    def _save_state(self) -> None:
        path = Path(self.settings.alerts_state_file)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self.state, f, ensure_ascii=False, sort_keys=True)
                os.chmod(tmp_name, 0o600)
                os.replace(tmp_name, path)
                os.chmod(path, 0o600)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
        except Exception:
            logger.exception("Failed to write alert state file %s", path)

# Instructions for AI agents working on VPN_TG_APP

## Architecture
- **Backend**: FastAPI (async) + SQLModel + SQLite + PyJWT + Fernet encryption
- **Bot**: aiogram 3 + httpx (shared client with connection pooling)
- **WireGuard**: managed via async subprocess (`asyncio.create_subprocess_exec`)
- **Deploy**: systemd services on Ubuntu VPS, no Docker
- **Target**: 50-150 users on single server

## Do
- Keep server safety: никогда не выкладывайте ключи WireGuard, BOT_TOKEN, пароли и содержимое `.env`.
- При деплое: используйте `deploy.sh` или systemd сервисы (`vpn-backend`, `vpn-bot`).
- **Безопасность**:
  - WG ключи шифруются Fernet (`app/crypto.py`).
  - JWT через PyJWT (не python-jose!) с claims: `exp`, `sub`, `iss`, `aud`.
  - `ADMIN_PASSWORD_HASH` обязателен — plaintext fallback удалён.
  - Bot API Key проверяется через `hmac.compare_digest`.
  - Frontend: все данные экранируются через `esc()`.
- **Качество кода**:
  - `record_audit()` только добавляет запись — commit делает вызывающий код.
  - Upsert пользователей по tg_id.
  - Все callback_data парсятся в try/except.
  - FSM-хэндлеры проверяют `message.text` и `message.from_user` на None.
  - Backend-вызовы из бота обёрнуты в try/except.
- **Производительность**:
  - Column projection вместо `select(Model)`.
  - SQL GROUP BY для агрегаций.
  - Bulk DELETE через `sqlalchemy.delete()`.
  - Все subprocess — async.

## Don't
- Не используйте `python-jose` — заменён на `PyJWT` из-за CVE.
- Не используйте `subprocess.check_output` — только `asyncio.create_subprocess_exec`.
- Не добавляйте `session.commit()` в `record_audit`.
- Не используйте `innerHTML` без `esc()` во frontend.
- Не храните plaintext пароли.
- Не публикуйте секреты в коде или логах.

## Testing
- 181 тест, 90% покрытие.
- Запуск: `pytest tests/ -v --cov=app --cov=bot --cov=scripts`
- SQLite для тестов, WireGuard мокается.
- При добавлении кода — добавляйте тесты.

## Key files
| Файл | Роль |
|---|---|
| `deploy.sh` | Автоматический деплой на Ubuntu |
| `app/security.py` | JWT (PyJWT) + bcrypt, iss/aud claims |
| `app/crypto.py` | Fernet encrypt/decrypt для WG ключей |
| `app/api/deps.py` | DI: DBSession, AdminDep, BotKeyDep |
| `app/tasks.py` | TrafficPoller: async, N+1-free, cleanup |
| `app/wg.py` | WireGuardManager: async subprocess + tc |
| `app/logging_config.py` | Structured JSON logging |
| `app/api/peers.py` | CRUD пиров: projection, bulk delete, Fernet |
| `bot/backend.py` | HTTP-клиент: shared httpx, retry on 401 |
| `bot/main.py` | FSM, админ-меню, error handling |

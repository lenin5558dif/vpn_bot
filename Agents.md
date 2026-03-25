# Instructions for AI agents working on VPN_TG_APP

## Architecture
- **Backend**: FastAPI (async) + SQLModel + PostgreSQL + PyJWT + Fernet encryption
- **Bot**: aiogram 3 + httpx (shared client with connection pooling)
- **WireGuard**: managed via async subprocess (`asyncio.create_subprocess_exec`)
- **Docker**: 3 services (db, backend, bot), hardened (cap_drop ALL, read_only, non-root)

## Do
- Keep server safety: никогда не выкладывайте ключи WireGuard, BOT_TOKEN, пароли и содержимое `.env` в ответы.
- При деплое на сервер (`/root/VPN_TG_APP`): используйте systemd сервисы (`vpn-backend`, `vpn-bot`); после правок перезапускайте их через `systemctl restart`.
- **Безопасность**:
  - Все приватные ключи WireGuard шифруются Fernet (`app/crypto.py`) перед записью в БД.
  - JWT используют PyJWT (не python-jose!) с обязательными claims: `exp`, `sub`, `iss`, `aud`.
  - `ADMIN_PASSWORD_HASH` обязателен — plaintext fallback удалён.
  - Bot API Key проверяется через `hmac.compare_digest` (timing-safe).
  - Все пользовательские данные в frontend экранируются через `esc()`.
- **Качество кода**:
  - `record_audit()` только добавляет запись — commit делает вызывающий код.
  - Upsert для пользователей: при повторном tg_id возвращается существующий пользователь.
  - Все callback_data парсятся в try/except.
  - FSM-хэндлеры проверяют `message.text` и `message.from_user` на None.
  - Backend-вызовы из бота обёрнуты в try/except с уведомлением пользователя.
- **Производительность**:
  - Используйте column projection (`select(Model.field)`) вместо `select(Model)` где нужны не все поля.
  - SQL GROUP BY для агрегаций, не Python-циклы.
  - Bulk DELETE через `sqlalchemy.delete()`, не ORM-циклы.
  - Все subprocess-вызовы — async (`asyncio.create_subprocess_exec`).
- Бот:
  - Админ-меню доступно только ID из `ADMIN_IDS`.
  - Кнопки «Отключить/Активировать/Забанить» вызывают PATCH на `/peers/{id}`.
  - При выдаче конфига отправляется файл `VPN_<имя_фамилия_транслитом>.conf`.
- Сохраняйте настройки и пути:
  - Рабочая директория на сервере: `/root/VPN_TG_APP`.
  - WG конфиг: `/etc/wireguard/wg0.conf`.

## Don't
- Не публикуйте секреты (.env, ключи wg, токены) в сообщениях/логах.
- Не используйте `python-jose` — заменён на `PyJWT` из-за CVE.
- Не используйте `subprocess.check_output` / `subprocess.check_call` — только `asyncio.create_subprocess_exec`.
- Не добавляйте `session.commit()` в `record_audit` — commit управляется вызывающим кодом.
- Не используйте `innerHTML` без экранирования через `esc()` во frontend.
- Не храните plaintext пароли — только bcrypt-хэши.
- Не меняйте серверный адрес WG подсети на адрес клиента.
- Не отключайте MASQUERADE/forward правила без явной задачи.
- Не запускайте destructive команды (reset, rm -rf) в /root вне проекта.

## Testing
- 174 теста, 90% покрытие.
- Запуск: `pytest tests/ -v --cov=app --cov=bot --cov=scripts`
- Тесты используют SQLite (aiosqlite), WireGuard-вызовы мокаются.
- conftest.py автоматически создаёт/дропает таблицы для каждого теста.
- При добавлении нового кода — добавляйте тесты.

## Key files
| Файл | Роль |
|---|---|
| `app/security.py` | JWT (PyJWT) + bcrypt auth, iss/aud claims |
| `app/crypto.py` | Fernet encrypt/decrypt для WG private keys |
| `app/api/deps.py` | DI: DBSession, AdminDep, BotKeyDep (hmac.compare_digest) |
| `app/tasks.py` | TrafficPoller: async subprocess, N+1-free, cleanup |
| `app/wg.py` | WireGuardManager: async subprocess |
| `app/api/peers.py` | CRUD пиров: column projection, bulk delete, Fernet |
| `bot/backend.py` | HTTP-клиент: shared httpx, token refresh, retry on 401 |
| `bot/main.py` | FSM-хэндлеры, админ-меню, error handling |

## Tips
- Если кнопки в боте не работают, проверьте callback данные и хэндлеры.
- При сетевых проблемах клиента: порт 51820/udp, peer != 10.10.0.1, MASQUERADE на eth0.
- При добавлении новой логики — обновляйте DOCS.md и тесты.
- `ENV=production` отключает /docs, /redoc, /openapi.json.

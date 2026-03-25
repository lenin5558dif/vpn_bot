# VPN_TG_APP Documentation

## Overview
- Purpose: Telegram бот + FastAPI backend для выдачи WireGuard-конфигов, учёта заявок и управления пирами (активация/отключение/бан).
- Стек: FastAPI, aiogram 3, SQLModel (PostgreSQL в проде, SQLite для тестов), WireGuard (`wg`), Docker Compose.
- Сетевые параметры по умолчанию: `WG_INTERFACE=wg0`, подсеть `10.10.0.0/24`, сервер слушает `51820/udp`, адрес сервера `10.10.0.1/24` (зарезервирован, клиенты получают адреса начиная с .2).

## Архитектура

```
┌──────────────┐     HTTP/JSON     ┌──────────────┐     SQL      ┌──────────┐
│  Telegram    │◄──────────────────│   Bot        │─────────────►│          │
│  Users/Admin │                   │  (aiogram 3) │              │ PostgreSQL│
└──────────────┘                   └──────┬───────┘              │          │
                                          │ HTTP (X-Bot-Api-Key) │          │
                                          ▼                      │          │
                                   ┌──────────────┐             │          │
                                   │   Backend    │─────────────►│          │
                                   │  (FastAPI)   │              └──────────┘
                                   └──────┬───────┘
                                          │ async subprocess
                                          ▼
                                   ┌──────────────┐
                                   │  WireGuard   │
                                   │  (wg CLI)    │
                                   └──────────────┘
```

## Структура проекта
```
app/                    # Backend (API, модели, WG-менеджер, фоновые задачи)
├── api/                # FastAPI роутеры
│   ├── auth.py         # POST /auth/login (JWT, rate limited 5/мин)
│   ├── users.py        # CRUD пользователей (upsert по tg_id)
│   ├── requests.py     # Заявки на VPN
│   ├── peers.py        # Управление WireGuard пирами
│   ├── traffic.py      # Статистика трафика (SQL GROUP BY)
│   ├── audit.py        # Аудит-лог
│   ├── health.py       # Deep health check (DB + WireGuard)
│   └── deps.py         # Зависимости (DBSession, AdminDep, BotKeyDep)
├── config.py           # Pydantic Settings (из .env)
├── crypto.py           # Fernet шифрование приватных ключей
├── database.py         # Async engine + session factory (connection pooling)
├── models.py           # SQLModel модели (User, Request, Peer, Config, TrafficStat, AuditLog)
├── schemas.py          # Pydantic схемы с валидацией (max_length)
├── security.py         # JWT (PyJWT) + bcrypt auth + iss/aud claims
├── tasks.py            # TrafficPoller (async, N+1-free, с cleanup)
├── wg.py               # WireGuardManager (async subprocess)
└── audit.py            # record_audit helper

bot/                    # Telegram-бот
├── main.py             # Хэндлеры, FSM, админ-меню
└── backend.py          # HTTP-клиент к backend (shared httpx pool)

frontend/
└── index.html          # Админ-панель (XSS-safe, все данные экранированы)

tests/                  # 174 теста, 90% покрытие
scripts/
└── migrate_encrypt_keys.py  # Миграция plaintext ключей → Fernet

docker-compose.yml      # PostgreSQL + Backend + Bot (hardened)
Dockerfile              # Python 3.11, non-root user
.dockerignore           # Исключает .env, .git, tests
```

## Переменные окружения (.env)

### Обязательные
| Переменная | Описание |
|---|---|
| `DATABASE_URL` | PostgreSQL: `postgresql+asyncpg://user:pass@host:5432/db` |
| `JWT_SECRET` | Секрет для JWT (мин. 32 байта, `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `ADMIN_USERNAME` | Логин администратора |
| `ADMIN_PASSWORD_HASH` | Bcrypt-хэш пароля (`python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('password'))"`) |
| `ENCRYPTION_KEY` | Fernet-ключ для шифрования WG-ключей (`python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`) |
| `BOT_API_KEY` | Shared secret между ботом и backend (`python3 -c "import secrets; print(secrets.token_urlsafe(32))"`) |
| `BOT_TOKEN` | Telegram Bot Token (от BotFather) |
| `ADMIN_IDS` | Telegram user_id админов через запятую |
| `SERVER_PUBLIC_KEY` | Публичный ключ WireGuard-сервера |

### Опциональные
| Переменная | По умолчанию | Описание |
|---|---|---|
| `ENV` | `development` | `production` отключает /docs, /redoc |
| `WG_INTERFACE` | `wg0` | Интерфейс WireGuard |
| `WG_ENDPOINT` | `example.com:51820` | Адрес сервера для клиентских конфигов |
| `WG_NETWORK` | `10.10.0.0/24` | Подсеть VPN |
| `WG_MTU` | `1420` | MTU |
| `WG_KEEPALIVE` | `25` | Persistent keepalive (сек) |
| `DEFAULT_SPEED_LIMIT_MBIT` | `20` | Лимит скорости по умолчанию |
| `CORS_ORIGINS` | `http://localhost:3000` | Разрешённые origins (через запятую) |

## Установка и запуск

### Docker Compose (рекомендуется)
```bash
cp .env.example .env  # заполнить все обязательные переменные
docker-compose up --build
```

### Локально
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить значения

# Backend
uvicorn app.main:app --reload --port 8000

# Бот (в отдельном терминале)
python -m bot.main
```

### Тесты
```bash
pytest tests/ -v --cov=app --cov=bot --cov=scripts
```

## Безопасность

### Реализовано
- **Шифрование ключей**: WireGuard private keys зашифрованы Fernet (AES-128-CBC) в БД
- **Аутентификация**: JWT с PyJWT, bcrypt-хэшированные пароли, iss/aud claims, обязательный exp
- **Авторизация**: Admin JWT для управления, Bot API Key (hmac.compare_digest) для пользовательских эндпоинтов
- **Rate limiting**: 5 запросов/мин на `/auth/login` (slowapi)
- **CORS**: Ограничен конкретными origins
- **Security headers**: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy
- **XSS protection**: Все пользовательские данные экранированы в frontend через `esc()`
- **Request size limit**: 1MB максимум
- **Docker**: non-root user, cap_drop ALL + cap_add NET_ADMIN, read_only, no-new-privileges, mem/pids limits
- **Docs**: `/docs`, `/redoc`, `/openapi.json` отключены при `ENV=production`
- **Audit log**: Все действия с пирами и заявками логируются с IP и actor_id
- **.dockerignore**: Исключает .env и секреты из образа

### Миграция существующих ключей
```bash
python scripts/migrate_encrypt_keys.py
```

## API Reference

### Аутентификация
- `POST /auth/login` — JWT-токен (rate limited: 5/мин)
  - Body: `username`, `password` (form-data)
  - Response: `{ "access_token": "...", "token_type": "bearer" }`

### Пользователи (требуют `X-Bot-Api-Key` для создания, JWT для чтения)
- `POST /users` — создание/upsert по tg_id (Header: `X-Bot-Api-Key`)
- `GET /users?limit=100&offset=0` — список (JWT)
- `GET /users/{id}` — детали (JWT)

### Заявки (требуют `X-Bot-Api-Key` для создания, JWT для управления)
- `POST /requests` — создание заявки (Header: `X-Bot-Api-Key`)
- `GET /requests?status=new&limit=100&offset=0` — список (JWT)
- `PATCH /requests/{id}` — обновление статуса (JWT)

### Пиры (JWT)
- `POST /peers` — создание пира (генерация ключей, IP, конфига)
- `GET /peers?limit=100&offset=0` — список
- `PATCH /peers/{id}` — смена статуса (`active`/`disabled`/`banned`), лимита скорости
- `GET /peers/{id}/config` — метаданные конфига
- `GET /peers/{id}/config/file` — текст .conf файла

### Трафик (JWT)
- `GET /traffic?hours=24&limit=100&offset=0` — сырые записи
- `GET /traffic/summary?hours=24` — агрегат по пирам (SQL GROUP BY)

### Аудит (JWT)
- `GET /audit?limit=20` — последние записи аудит-лога

### Здоровье (публичный)
- `GET /health` — `{ "status": "ok|degraded", "checks": { "db": "ok", "wireguard": "ok|error|unavailable" } }`

## Пользовательский поток (бот)
1. `/start` → имя/фамилия → контакт (тел/email) → комментарий (опц.)
2. Создаётся пользователь (upsert по tg_id) и заявка
3. Админ получает уведомление с кнопками «Одобрить» / «Отказать»
4. При одобрении: создаётся peer, генерируются ключи/IP, применяется в WG, отправляется `.conf` файл
5. При отказе: уведомление пользователю
6. Защита: валидация текста (max_length), guard для non-text сообщений и from_user=None, error handling при сбоях backend

## Админ-меню в боте
- `/admin` — доступно только ID из `ADMIN_IDS`
- Кнопки:
  - «Новые заявки» / «Все заявки» — списки
  - «Пиры» — первые 20 пиров с кнопками управления
  - «Пользователи» — список
  - «Health» — состояние API

## Производительность (целевая нагрузка: 200 пользователей)
- **Async**: все subprocess-вызовы через `asyncio.create_subprocess_exec`
- **N+1 fix**: TrafficPoller использует один SQL-запрос с `MAX(ts)` subquery
- **Cleanup**: TrafficStat старше 7 дней удаляется каждый час
- **Пагинация**: все list-эндпоинты с `limit`/`offset`
- **Connection pool**: `pool_size=10`, `max_overflow=20`, `pool_pre_ping=True`
- **Shared HTTP client**: Bot использует один `httpx.AsyncClient` с keep-alive
- **Column projection**: поллер загружает только `(id, public_key)`, create_peer — только `address`
- **SQL aggregation**: `traffic_summary` использует `GROUP BY` вместо Python-цикла
- **Bulk operations**: DELETE при бане через SQL, не ORM-цикл
- **Индексы**: `(peer_id, ts)` на TrafficStat, `ts` на AuditLog

## Деплой на сервере (prod)
- Код: `/root/VPN_TG_APP`
- Виртуальное окружение: `/root/VPN_TG_APP/.venv`
- Systemd-сервисы: `vpn-backend.service`, `vpn-bot.service`
- WireGuard: `/etc/wireguard/wg0.conf`, ключи в `/etc/wireguard/`
- IP forward/NAT: `/etc/sysctl.d/99-wg-forward.conf`, MASQUERADE на eth0

```bash
systemctl status vpn-backend vpn-bot
systemctl restart vpn-backend vpn-bot
journalctl -u vpn-backend -f
journalctl -u vpn-bot -f
```

## Обслуживание
- Бэкап БД: `pg_dump`
- Бэкап WireGuard: `/etc/wireguard/wg0.conf`, ключи
- Ротация секретов: обновить `.env`, перезапустить сервисы
- Миграция ключей: `python scripts/migrate_encrypt_keys.py`
- Проверка здоровья: `curl http://localhost:8000/health`

## Типовые проблемы
| Проблема | Решение |
|---|---|
| Клиент не выходит в интернет | Проверить: peer получил адрес != 10.10.0.1, порт 51820/udp открыт, MASQUERADE на eth0, AllowedIPs=0.0.0.0/0 |
| Бот не отвечает | `journalctl -u vpn-bot -f`, проверить BOT_TOKEN, интернет на сервере |
| 401/403 | Проверить ADMIN_IDS, JWT токен, ADMIN_PASSWORD_HASH |
| 503 на POST /users | BOT_API_KEY не настроен или не совпадает |
| Аудит пуст | Убедиться что ADMIN_PASSWORD_HASH задан (без него auth не работает) |

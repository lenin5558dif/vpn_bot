# VPN_TG_APP Documentation

## Overview
Telegram бот + FastAPI backend для выдачи WireGuard-конфигов, учёта заявок и управления пирами. Рассчитан на 50-150 пользователей на одном VPS.

**Стек:** FastAPI, aiogram 3, SQLModel + SQLite, WireGuard (wg CLI), systemd.

## Быстрый старт

### Деплой на чистый Ubuntu (2 минуты)
```bash
scp -r . root@your-server:/root/VPN_TG_APP
ssh root@your-server "bash /root/VPN_TG_APP/deploy.sh"
```
Скрипт спросит 3 вещи: **BOT_TOKEN**, **ADMIN_IDS**, **пароль админа**. Остальное сгенерирует автоматически.

### Локальная разработка
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env  # заполнить значения
uvicorn app.main:app --reload --port 8000  # backend
python -m bot.main                          # бот (отдельный терминал)
```

### Тесты
```bash
pytest tests/ -v --cov=app --cov=bot --cov=scripts
# 181 тест, 90% покрытие
```

## Архитектура

```
Telegram ◄──► Bot (aiogram 3) ──HTTP──► Backend (FastAPI) ──► SQLite
                                  │          │
                            X-Bot-Api-Key    │ async subprocess
                                             ▼
                                        WireGuard (wg CLI)
                                             │
                                        tc (speed limits)
```

- **Backend** слушает на `127.0.0.1:8000` (только localhost)
- **Bot** общается с Backend по HTTP, с пользователями через Telegram API
- **SQLite** — файл `vpnapp.sqlite` в директории проекта
- **WireGuard** управляется через async subprocess (`wg set`, `wg show`)
- **Systemd** запускает `vpn-backend` и `vpn-bot`

## Структура проекта
```
app/
├── api/
│   ├── auth.py         POST /auth/login (JWT, rate limited 5/мин)
│   ├── users.py        CRUD пользователей (upsert по tg_id)
│   ├── requests.py     Заявки на VPN
│   ├── peers.py        Управление WireGuard пирами
│   ├── traffic.py      Статистика трафика (SQL GROUP BY)
│   ├── audit.py        Аудит-лог
│   ├── health.py       Deep health check (DB + WireGuard)
│   └── deps.py         DI: DBSession, AdminDep, BotKeyDep
├── config.py           Pydantic Settings (из .env)
├── crypto.py           Fernet шифрование приватных ключей
├── database.py         Async SQLite engine + session factory
├── logging_config.py   Structured JSON logging
├── models.py           SQLModel модели
├── schemas.py          Pydantic схемы с валидацией
├── security.py         JWT (PyJWT) + bcrypt + iss/aud claims
├── tasks.py            TrafficPoller (async, cleanup 7 дней)
├── wg.py               WireGuardManager (async subprocess + tc)
└── audit.py            record_audit helper

bot/
├── main.py             Хэндлеры, FSM, админ-меню
└── backend.py          HTTP-клиент (shared httpx pool)

frontend/index.html     Админ-панель (XSS-safe)
tests/                  181 тест, 90% покрытие
scripts/migrate_encrypt_keys.py   Миграция plaintext → Fernet
deploy.sh               Автоматический деплой на Ubuntu
```

## Переменные окружения (.env)

`deploy.sh` генерирует все секреты автоматически. При ручной настройке:

### Обязательные
| Переменная | Описание | Как получить |
|---|---|---|
| `BOT_TOKEN` | Telegram Bot Token | @BotFather |
| `ADMIN_IDS` | Telegram ID админов (через запятую) | @userinfobot |
| `ADMIN_PASSWORD` | Пароль админа (для бота) | Придумать |
| `ADMIN_PASSWORD_HASH` | Bcrypt-хэш пароля | `python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('пароль'))"` |
| `ENCRYPTION_KEY` | Fernet-ключ | `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `BOT_API_KEY` | Shared secret бот↔backend | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `JWT_SECRET` | Секрет JWT (мин. 32 байта) | `python3 -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `SERVER_PUBLIC_KEY` | Публичный ключ WG-сервера | `wg show wg0 public-key` |

### Опциональные
| Переменная | По умолчанию | Описание |
|---|---|---|
| `DATABASE_URL` | `sqlite+aiosqlite:///./vpnapp.sqlite` | Путь к БД |
| `WG_INTERFACE` | `wg0` | Интерфейс WireGuard |
| `WG_ENDPOINT` | `example.com:51820` | Адрес сервера для клиентских конфигов |
| `WG_NETWORK` | `10.10.0.0/24` | Подсеть VPN (макс 253 пира) |
| `CORS_ORIGINS` | `http://localhost:3000` | Разрешённые CORS origins |
| `LOG_LEVEL` | `INFO` | Уровень логирования |

### Startup-валидация
Приложение **не запустится** без: `ENCRYPTION_KEY`, `SERVER_PUBLIC_KEY`, `ADMIN_PASSWORD_HASH`, `BOT_API_KEY`. Ошибка будет понятной.

## Безопасность
- **WG ключи** зашифрованы Fernet (AES-128-CBC) в SQLite
- **JWT** через PyJWT с обязательными claims: exp, sub, iss, aud
- **Пароль** — только bcrypt-хэш, plaintext fallback удалён
- **Bot API Key** — hmac.compare_digest (timing-safe)
- **Rate limiting** — 5/мин на /auth/login
- **XSS** — все данные экранированы через `esc()` в frontend
- **Security headers** — X-Content-Type-Options, X-Frame-Options, Referrer-Policy
- **Request size limit** — 1MB
- **Input validation** — max_length на всех строковых полях
- **Audit log** — все действия с IP и actor_id

## API Reference

| Метод | Endpoint | Auth | Описание |
|---|---|---|---|
| POST | `/auth/login` | — | JWT-токен (rate limited) |
| POST | `/users` | Bot API Key | Создание/upsert пользователя |
| GET | `/users` | JWT | Список пользователей |
| GET | `/users/{id}` | JWT | Детали пользователя |
| POST | `/requests` | Bot API Key | Создание заявки |
| GET | `/requests?status=new` | JWT | Список заявок |
| PATCH | `/requests/{id}` | JWT | Одобрить/отклонить |
| POST | `/peers` | JWT | Создание пира |
| GET | `/peers` | JWT | Список пиров |
| PATCH | `/peers/{id}` | JWT | Статус/скорость пира |
| GET | `/peers/{id}/config/file` | JWT | Скачать .conf |
| GET | `/traffic?hours=24` | JWT | Статистика трафика |
| GET | `/traffic/summary?hours=24` | JWT | Агрегат по пирам |
| GET | `/audit?limit=20` | JWT | Аудит-лог |
| GET | `/health` | — | Статус DB + WireGuard |

## Пользовательский поток
1. `/start` → имя → контакт → комментарий
2. Бот создаёт пользователя (upsert по tg_id) и заявку
3. Админ получает уведомление → «Одобрить» / «Отказать»
4. При одобрении: генерация ключей → IP → `wg set` → `.conf` файл в чат
5. При отказе: уведомление пользователю

## Управление (на сервере)
```bash
# Статус
systemctl status vpn-backend vpn-bot

# Перезапуск
systemctl restart vpn-backend vpn-bot

# Логи
journalctl -u vpn-backend -f
journalctl -u vpn-bot -f

# Бэкап
cp vpnapp.sqlite vpnapp.sqlite.bak
cp /etc/wireguard/wg0.conf /etc/wireguard/wg0.conf.bak

# Миграция ключей (при обновлении со старой версии)
source .venv/bin/activate && python scripts/migrate_encrypt_keys.py

# Health check
curl http://localhost:8000/health
```

## Типовые проблемы
| Проблема | Решение |
|---|---|
| Приложение не стартует | Проверить что все обязательные переменные в .env заполнены |
| Клиент не выходит в интернет | peer != 10.10.0.1, порт 51820/udp открыт, MASQUERADE на eth0 |
| Бот не отвечает | `journalctl -u vpn-bot -f`, проверить BOT_TOKEN |
| 401/403 | Проверить ADMIN_IDS и что ADMIN_PASSWORD_HASH соответствует ADMIN_PASSWORD |
| 503 на POST /users | BOT_API_KEY не настроен или не совпадает |

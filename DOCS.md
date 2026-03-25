# VPN_TG_APP Documentation

## Overview
- Purpose: Telegram бот + FastAPI backend для выдачи WireGuard-конфигов, учёта заявок и управления пирами (активация/отключение/бан).
- Стек: FastAPI, aiogram, SQLModel (sqlite по умолчанию), WireGuard (`wg`, `wg-quick`), systemd-сервисы.
- Сетевые параметры по умолчанию: `WG_INTERFACE=wg0`, подсеть `10.10.0.0/24`, сервер слушает `51820/udp`, адрес сервера в подсети `10.10.0.1/24` (зарезервирован, клиенты получают адреса начиная с .2).

## Репозиторий/структура
- `app/` — backend (API, модели, wg-менеджер, фоновые задачи).
- `bot/` — Telegram-бот (пользовательский поток, админ-меню).
- `tests/` — базовый тест здоровья API.
- `Dockerfile`, `docker-compose.yml` — контейнерный запуск (postgres+backend+bot).
- `.env.example` — шаблон переменных.
- `TZ.MD` — ТЗ, `DOCS.md` — эта документация.

## Переменные окружения (.env)
Ключевые:
- `DATABASE_URL` — sqlite по умолчанию `sqlite+aiosqlite:///./vpnapp.sqlite` или Postgres `postgresql+asyncpg://user:pass@host:5432/db`.
- `BACKEND_HOST`, `BACKEND_PORT`, `BACKEND_URL` (для бота).
- `JWT_SECRET`, `JWT_ALG`, `ADMIN_USERNAME`, `ADMIN_PASSWORD`.
- `BOT_TOKEN`, `ADMIN_IDS` (через запятую, Telegram user_id админов).
- WireGuard: `WG_INTERFACE`, `WG_ENDPOINT` (`host:port`), `WG_NETWORK`, `WG_MTU`, `WG_KEEPALIVE`, `DEFAULT_SPEED_LIMIT_MBIT`, `SERVER_PUBLIC_KEY`.

## Установка локально
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить значения
```

### Запуск локально
- Backend: `uvicorn app.main:app --reload --port 8000`
- Бот: `python -m bot.main`
- Тесты: `PYTHONPATH=. pytest -q`

### Через docker-compose (при наличии Docker)
```bash
docker-compose up --build
```

## Деплой на сервере (prod)
- Код размещён в `/root/VPN_TG_APP`.
- Виртуальное окружение: `/root/VPN_TG_APP/.venv`.
- Systemd-сервисы:
  - `vpn-backend.service` — FastAPI на `:8000`
  - `vpn-bot.service` — aiogram бот
- Управление:
```bash
systemctl status vpn-backend.service
systemctl status vpn-bot.service
systemctl restart vpn-backend.service vpn-bot.service
journalctl -u vpn-backend.service -f
journalctl -u vpn-bot.service -f
```
- WireGuard конфиг: `/etc/wireguard/wg0.conf` (серверный ключи в `/etc/wireguard/server_private.key`, `/etc/wireguard/server_public.key`).
- IP forward/NAT: sysctl в `/etc/sysctl.d/99-wg-forward.conf`, NAT-правила ставит wg-quick (MASQUERADE на eth0).
- Открыть порт `51820/udp` на фаерволе/панели провайдера, при необходимости `8000/tcp` для API/доков.

## Пользовательский поток (бот)
- `/start` → имя/фамилия → контакт (тел/email) → комментарий (опц.).
- Создаётся заявка, админ получает уведомление с кнопками Одобрить/Отказать.
- При одобрении: создаётся peer, генерится ключи/IP, применяется в wg, отправляется файл `.conf` (имя `VPN_<имя_фамилия_транслитом>.conf`) в чат.
- При отказе: уведомление пользователю.

## Админ-меню в боте
- `/admin` доступно только ID из `ADMIN_IDS`.
- Кнопки:
  - «Новые заявки» / «Все заявки» — списки заявок.
  - «Пиры» — вывод первых 20 пиров; для каждого кнопки:
    - «Отключить» → status=disabled (AllowedIPs очищены).
    - «Активировать» → status=active, применяется AllowedIPs и лимит.
    - «Забанить» → status=banned, удаляет peer из wg и БД, чистит конфиг.
  - «Пользователи» — список users.
  - «Health» — состояние API.

## Ограничение на число конфигов
- Сейчас один пользователь может получить несколько пиров (каждый клик «Одобрить»). При необходимости можно добавить проверку и запрещать новые пиров для user_id, если уже есть активный/disabled.

## API (сжатый reference)
- Auth: `POST /auth/login` (form username/password) → `access_token`.
- Users: `POST /users`, `GET /users`, `GET /users/{id}`.
- Requests: `POST /requests` (user_id, comment), `GET /requests?status=...`, `PATCH /requests/{id}` (status=approved/rejected).
- Peers: `POST /peers` (user_id) создаёт peer + config запись; `GET /peers`; `PATCH /peers/{id}` (status=active/disabled/banned, optional speed_limit_mbps).
- Config: `GET /peers/{id}/config/file` — текст .conf.
- Traffic: `GET /traffic` — сырые записи (если включён сбор).
- Health: `GET /health`.
- Auth заголовок: `Authorization: Bearer <token>`.

## WireGuard детали
- Подсеть: `WG_NETWORK` (по умолчанию `10.10.0.0/24`), серверный адрес `10.10.0.1/24` (резервируется), клиенты — начиная с .2.
- Создание peer: `wg set <iface> peer <pub> allowed-ips <ip>/32`; лимит скорости пока заглушка (функция `apply_speed_limit` требует доработки `tc`).
- Бан: удаление peer из wg, запись и конфиг удаляются из БД.
- Disable: очищает AllowedIPs, peer остаётся в списке (можно активировать позже).

## Сбор трафика
- `app/tasks.py` опрашивает `wg show <iface> transfer` раз в минуту (фон в lifespan), пишет `TrafficStat`. Логика минимальная; для прод-мониторинга лучше поставить node_exporter/Prometheus.

## Тесты
- `tests/test_health.py` — проверка `/health`.
- Запуск: `PYTHONPATH=. pytest -q`.

## Обслуживание/бэкапы
- Бэкап БД: для sqlite — файл `vpnapp.sqlite`; для Postgres — `pg_dump`.
- Бэкап WireGuard: `/etc/wireguard/wg0.conf`, ключи.
- После правок .env или кода — `systemctl restart vpn-backend vpn-bot`.

## Типовые проблемы
- Клиент не выходит в интернет: убедиться, что peer получил адрес ≠ 10.10.0.1, порт 51820/udp открыт, есть MASQUERADE на eth0, сверить `AllowedIPs=0.0.0.0/0, ::/0`.
- Бот не отвечает: проверить `journalctl -u vpn-bot -f`, валиден ли `BOT_TOKEN`, есть ли интернет на сервере.
- 401/403 в админ-функциях: проверить `ADMIN_IDS`, токен (/auth/login) и `ADMIN_USERNAME/PASSWORD`.


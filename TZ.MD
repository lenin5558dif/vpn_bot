# ТЗ: VPN-сервис с управлением через Telegram-бот

## Цель
- Автоматизировать выдачу и управление WireGuard-доступом для сотрудников на Ubuntu-сервере с каналом 100 Мбит/с.
- Управление только через бота и админ-панель (логин+пароль), без WebApp для пользователей.

## Компоненты и стек
- WireGuard на хосте (`wg`, `wg-quick`).
- Backend API: FastAPI (Python) + Postgres; alembic для миграций.
- Бот: aiogram.
- Админка: React + Ant Design или сервер-рендер в FastAPI (минимум фронта).
- Фоновый воркер/cron: сбор статистики, применение rate-limit.
- Nginx (HTTPS/реверс-прокси), systemd/docker-compose для запуска сервисов.

## Пользовательский поток (бот)
1) `/start` → собрать имя/контакт (телефон/email), отдел/комментарий.
2) Кнопка «Запросить VPN» → создаётся заявка `request` со статусом `new`.
3) Админ получает уведомление в боте: «User X запросил VPN (коммент) [Одобрить]/[Отказать]».
4) При одобрении:
   - Генерируются ключи/peer, выделяется IP.
   - Применяется `wg set` и rate-limit 20 Мбит/с.
   - Статус заявки `approved`, peer `active`.
   - Пользователь получает .conf + QR + краткую инструкцию.
5) При отказе: статус `rejected`, пользователю уведомление.
6) Пользователь может запросить отзыв/проблему → тикет в журнале.

## Админка (веб)
- Аутентификация: логин+пароль (опционально TOTP), IP allowlist если возможно.
- Раздел «Заявки»: список `new/approved/rejected`, кнопки approve/reject.
- Раздел «Пиры»: поиск/фильтры по статусу `active/disabled/banned`, просмотр последнего handshake, трафика.
- Действия: отключить/включить (disable/active), бан (удалить peer из WG), регенерировать ключи, задать лимит скорости (по умолчанию 20 Мбит/с).
- Раздел «Трафик»: таблица/график по пользователю/peer, суммарная загрузка.
- Журнал действий (audit).

## API (черновик)
- Auth: JWT с ролями `admin/operator`.
- `POST /auth/login` (логин/пароль) → токен.
- `POST /users` (из бота).
- `POST /requests` (создать заявку), `GET /requests?status=...`, `PATCH /requests/{id}` (approve/reject).
- `POST /peers` (создать peer при approve), `PATCH /peers/{id}` (status: active/disabled/banned, speed_limit), `GET /peers` (фильтры).
- `GET /peers/{id}/config` (одноразовый токен/TTL).
- `GET /traffic` (агрегаты по peer и диапазону дат).
- `POST /alerts/test` (для уведомлений в админ-бот).

## Модели данных (Postgres)
- users: id, tg_id (nullable), name, contact, role (user/admin), created_at, last_login_at.
- requests: id, user_id, status (`new/approved/rejected`), comment, created_at, resolved_at, resolved_by.
- peers: id, user_id, iface, public_key, private_key_enc, address (10.10.0.x/32), allowed_ips, status (`pending/active/disabled/banned`), speed_limit_mbps (default 20), created_at, updated_at, last_handshake_at.
- configs: id, peer_id, download_token, expires_at, file_path/hash, qr_data.
- traffic_stats: id, peer_id, ts, rx_bytes, tx_bytes, delta_rx, delta_tx.
- audit_logs: id, actor_id, action, target_type, target_id, ts, ip, meta.

## WireGuard и сеть
- Пул: приватная подсеть, например `10.10.0.0/24`; каждому peer — /32.
- Применение peer: `wg set <iface> peer <pubkey> allowed-ips <ip>/32 endpoint <server:port> persistent-keepalive 25`.
- Rate-limit 20 Мбит/с per peer: `tc` (htb/tbf) с классом на IP или по fwmark. Профиль хранить в БД, применять/снимать при смене статуса.
- Ротация ключей: регенерация → `wg set` → новая конфигурация пользователю.
- Бан: `wg set <iface> peer <pubkey> remove` + очистка правил `tc`; статус `banned`.
- Disable: очистка `AllowedIPs` или iptables drop, без удаления peer.

## Сбор статистики
- Каждые 30–60 с: `wg show <iface> transfer` → дифф по байтам → запись в `traffic_stats`, обновление `last_handshake_at`.
- Обработка переполнения/рестартов (baseline).
- Опционально nft/iptables counters для точности.

## Безопасность и эксплуатация
- HTTPS (nginx + Let’s Encrypt или свой сертификат).
- Секреты в .env, приватные ключи peers в БД в шифре/с на диске с ограниченными правами.
- Бэкапы: `pg_dump` + `/etc/wireguard/*.conf`.
- Логи: действия админов, выдачи/отзывы, ошибки бота, системные события.
- Мониторинг: node_exporter/Prometheus (опционально), алерты по недоступности API и превышению нагрузки.

## Приёмка (MVP)
- Создание заявки через бота, одобрение через админ-бот/панель, успешное подключение по выданному .conf/QR.
- Бан/disable приводит к немедленной блокировке трафика.
- В панели отображается трафик и последний handshake по каждому peer.
- Rate-limit 20 Мбит/с применяется и снимается при смене статуса.
- После рестарта сервисов и WG состояния peers сохраняются, конфиги актуальны.

## Этапы реализации (пример)
1) Инфраструктура: базовый WG, подсеть, nginx/HTTPS, Postgres.
2) Backend + миграции, модели выше; базовые эндпоинты users/requests/peers.
3) WG-менеджер (создание/удаление peer, tc лимиты), интеграция с API.
4) Бот: заявки, уведомления админам, approve/reject, выдача .conf/QR.
5) Админка: заявки, список peers, toggle/ban, просмотр трафика.
6) Воркер статистики и отображение метрик.
7) Тесты/приёмка, бэкапы, документация по деплою.

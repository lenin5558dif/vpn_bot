# VPN_TG_APP

Telegram-бот для управления VPN-доступом на базе AmneziaWG (обход DPI).

- Пользователи запрашивают доступ через бота → админ одобряет/отклоняет
- При одобрении генерируется конфиг AmneziaWG и отправляется пользователю
- Администрирование через бота: пиры, трафик, бан, лимит скорости

---

## Быстрый старт

### Требования к серверу

| | Минимум | Рекомендуется |
|---|---|---|
| ОС | Ubuntu 22.04 LTS | Ubuntu 22.04 / 24.04 LTS |
| CPU | 1 vCPU | 1 vCPU |
| RAM | 512 MB | **2 GB** |
| Диск | 10 GB SSD | 20 GB SSD |
| Сеть | 100 Mbps | 1 Gbps, 2+ TB/мес |

Рекомендуемые провайдеры:
- **[Cloudzy](https://cloudzy.com)** — локация USA, международные карты и крипта
- **[RUVDS.com](https://ruvds.com)** — российские карты/СБП, локации в Европе и США

### Что нужно заранее
- SSH-доступ к серверу (логин `root`)
- Telegram Bot Token — [@BotFather](https://t.me/BotFather)
- Ваш Telegram ID — [@userinfobot](https://t.me/userinfobot)
- Придуманный пароль администратора

### Установка

```bash
git clone https://github.com/lenin5558dif/vpn_bot.git VPN_TG_APP
cd VPN_TG_APP
bash deploy.sh
```

Скрипт задаст 4 вопроса и автоматически настроит всё остальное.

Подробная пошаговая инструкция — в **[INSTALL.md](INSTALL.md)**.

---

## Стек

| Компонент | Технология |
|---|---|
| VPN | AmneziaWG (WireGuard с обходом DPI) |
| Backend API | FastAPI + SQLite (aiosqlite) |
| Telegram-бот | aiogram 3 |
| Шифрование ключей | Fernet (AES-128-CBC) |
| Аутентификация | JWT (PyJWT) + bcrypt |
| Запуск | systemd (без Docker) |
| Файрвол | UFW |
| Защита SSH | fail2ban (прогрессивный бан) |

---

## Архитектура

```
Telegram ◄──► Bot (aiogram 3) ──HTTP──► Backend (FastAPI) ──► SQLite
                                  │
                            X-Bot-Api-Key
                                             │ async subprocess
                                             ▼
                                       AmneziaWG (awg CLI)
                                             │
                                        tc (speed limits)
```

- Backend слушает только на `127.0.0.1:8000`
- Бот общается с Backend по HTTP через shared httpx-пул
- WireGuard-ключи пиров зашифрованы Fernet в SQLite
- Трафик собирается каждые 30–60 сек через `awg show transfer`

---

## Что делает `deploy.sh`

- Устанавливает AmneziaWG из PPA
- Генерирует ключи сервера, настраивает IP-forwarding и NAT
- Создаёт Python venv, устанавливает зависимости
- Генерирует все секреты (JWT, Fernet, Bot API Key) и записывает в `.env` (chmod 600)
- Создаёт и запускает systemd-сервисы `vpn-backend` и `vpn-bot`
- Настраивает UFW: открыты только 22/tcp (SSH) и 443/udp (VPN)
- Настраивает fail2ban с 4-уровневым прогрессивным баном SSH:
  - 3 ошибки за 10 мин → **20 минут**
  - 2 бана за 1 ч → **3 часа**
  - 3 бана за 12 ч → **24 часа**
  - 4 бана за 2 дня → **навсегда**

---

## Переменные окружения

`deploy.sh` генерирует все секреты автоматически. При ручной настройке скопируйте `.env.example` в `.env` и заполните:

| Переменная | Описание |
|---|---|
| `BOT_TOKEN` | Токен бота от @BotFather |
| `ADMIN_IDS` | Telegram ID администраторов (через запятую) |
| `ADMIN_PASSWORD` | Пароль администратора |
| `ADMIN_PASSWORD_HASH` | Bcrypt-хэш пароля |
| `ENCRYPTION_KEY` | Fernet-ключ для шифрования WG-ключей |
| `BOT_API_KEY` | Shared secret бот ↔ backend |
| `JWT_SECRET` | Секрет JWT (мин. 32 байта) |
| `SERVER_PUBLIC_KEY` | Публичный ключ WG-сервера |
| `WG_ENDPOINT` | Адрес сервера для клиентских конфигов (`ip:443`) |

> Приложение не запустится без: `ENCRYPTION_KEY`, `SERVER_PUBLIC_KEY`, `ADMIN_PASSWORD_HASH`, `BOT_API_KEY`.

---

## Управление

```bash
# Статус сервисов
systemctl status vpn-backend vpn-bot

# Перезапуск
systemctl restart vpn-backend vpn-bot

# Логи
journalctl -u vpn-backend -f
journalctl -u vpn-bot -f

# Health check
curl http://localhost:8000/health

# Файрвол
ufw status verbose

# Заблокированные IP (fail2ban)
fail2ban-client status sshd
fail2ban-client status recidive

# Разблокировать IP вручную
fail2ban-client set sshd unbanip <IP>
```

---

## Безопасность

- WG-ключи пиров зашифрованы Fernet в SQLite — plaintext нигде не хранится
- JWT с обязательными claims: `exp`, `sub`, `iss`, `aud`
- Bot API Key проверяется через `hmac.compare_digest` (timing-safe)
- Rate limiting: 5 запросов/мин на `/auth/login`
- Аудит-лог всех действий с IP и actor_id
- `python-jose` не используется — заменён на `PyJWT` (CVE)

---

## API

| Метод | Endpoint | Описание |
|---|---|---|
| POST | `/auth/login` | JWT-токен (rate limited) |
| POST | `/users` | Создание/upsert пользователя |
| GET | `/users` | Список пользователей |
| POST | `/requests` | Создание заявки |
| GET | `/requests?status=new` | Список заявок |
| PATCH | `/requests/{id}` | Одобрить/отклонить |
| POST | `/peers` | Создание пира |
| GET | `/peers` | Список пиров |
| PATCH | `/peers/{id}` | Статус/скорость |
| GET | `/peers/{id}/config/file` | Скачать `.conf` |
| GET | `/traffic?hours=24` | Статистика трафика |
| GET | `/audit` | Аудит-лог |
| GET | `/health` | Статус DB + WireGuard |

---

## Тесты

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
pytest tests/ -v --cov=app --cov=bot --cov=scripts
```

181 тест, покрытие ~90%.

---

## Бэкап

```bash
# База данных
cp vpnapp.sqlite "vpnapp.sqlite.bak.$(date +%Y%m%d_%H%M%S)"

# WireGuard конфиг
cp /etc/wireguard/awg0.conf /etc/wireguard/awg0.conf.bak
```

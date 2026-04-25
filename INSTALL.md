# Установка VPN_TG_APP

Telegram-бот + VPN-сервер (AmneziaWG) на Ubuntu 22.04.  
Полная установка занимает ~5 минут после выполнения предварительных шагов.

---

## Содержание

1. [Предварительные требования](#1-предварительные-требования)
2. [Создание Telegram-бота](#2-создание-telegram-бота)
3. [Подключение к серверу](#3-подключение-к-серверу)
4. [Клонирование репозитория](#4-клонирование-репозитория)
5. [Запуск установки](#5-запуск-установки)
6. [Проверка работы](#6-проверка-работы)
7. [Управление и обслуживание](#7-управление-и-обслуживание)
8. [Типовые проблемы](#8-типовые-проблемы)
9. [Инструкция для ИИ-агента (Claude / Codex)](#9-инструкция-для-ии-агента-claude--codex)

---

## 1. Предварительные требования

### Сервер
| Параметр | Минимум | Рекомендуется |
|---|---|---|
| ОС | Ubuntu 22.04 LTS | Ubuntu 22.04 / 24.04 LTS |
| RAM | 512 MB | 1 GB |
| Диск | 5 GB | 10 GB |
| CPU | 1 vCPU | 1–2 vCPU |
| Сеть | Публичный IP | Публичный IP |

> Проект рассчитан на 50–150 пользователей на одном VPS.

### Что нужно заранее
- **SSH-доступ к серверу** — логин `root` (или пользователь с `sudo`)
- **Telegram Bot Token** — получить у @BotFather (шаг 2)
- **Ваш Telegram ID** — узнать у @userinfobot

---

## 2. Создание Telegram-бота

1. Откройте Telegram, найдите **@BotFather**
2. Отправьте `/newbot`
3. Введите имя бота (например: `MyVPN Bot`)
4. Введите username бота (например: `my_vpn_bot`) — должен заканчиваться на `bot`
5. Скопируйте полученный **токен** вида `7123456789:AAH...`

Узнайте свой Telegram ID:
1. Найдите **@userinfobot**
2. Отправьте `/start`
3. Скопируйте число в поле `Id:` — это ваш **ADMIN_IDS**

---

## 3. Подключение к серверу

```bash
ssh root@YOUR_SERVER_IP
```

Если используете SSH-ключ:
```bash
ssh -i ~/.ssh/your_key root@YOUR_SERVER_IP
```

---

## 4. Клонирование репозитория

На сервере выполните:

```bash
cd /root
git clone https://github.com/lenin5558dif/vpn_bot.git VPN_TG_APP
cd VPN_TG_APP
```

---

## 5. Запуск установки

```bash
bash deploy.sh
```

Скрипт задаст **4 вопроса**:

| Вопрос | Что вводить |
|---|---|
| `BOT_TOKEN` | Токен от @BotFather (шаг 2) |
| `ADMIN_IDS` | Ваш Telegram ID (шаг 2) |
| `Пароль админа` | Придумайте надёжный пароль для веб-панели |
| `Имя пользователя [admin]` | Enter — оставить `admin`, или ввести своё |

Скрипт автоматически выполнит:

- [x] Установку AmneziaWG (VPN с защитой от DPI)
- [x] Генерацию ключей WireGuard
- [x] Настройку IP-forwarding и NAT (MASQUERADE)
- [x] Установку Python-окружения и зависимостей
- [x] Генерацию всех секретов (JWT, Fernet, Bot API Key)
- [x] Создание `.env` с правами `600`
- [x] Запуск сервисов `vpn-backend` и `vpn-bot` через systemd
- [x] Настройку файрвола UFW (порты 22/tcp и 443/udp)
- [x] Настройку fail2ban — постоянный бан SSH после 5 неудачных попыток

> После установки `.env` содержит все секреты. Никогда не публикуйте его содержимое.

---

## 6. Проверка работы

### Статус сервисов
```bash
systemctl status vpn-backend vpn-bot
```

### Health check API
```bash
curl http://localhost:8000/health
```
Ожидаемый ответ: `{"status":"ok","db":"ok","wireguard":"ok"}`

### Статус файрвола
```bash
ufw status verbose
```

### Статус fail2ban
```bash
fail2ban-client status sshd
```

### Проверка WireGuard
```bash
awg show awg0
```

### Тест бота
1. Откройте вашего бота в Telegram
2. Отправьте `/start`
3. Бот должен ответить и запросить имя

---

## 7. Управление и обслуживание

### Сервисы
```bash
# Статус
systemctl status vpn-backend vpn-bot

# Перезапуск
systemctl restart vpn-backend vpn-bot

# Логи в реальном времени
journalctl -u vpn-backend -f
journalctl -u vpn-bot -f
```

### Файрвол (UFW)
```bash
ufw status verbose

# Разрешить дополнительный порт
ufw allow 80/tcp

# Заблокировать IP вручную
ufw deny from 1.2.3.4
```

### fail2ban
```bash
# Список заблокированных IP
fail2ban-client status sshd

# Разблокировать IP вручную
fail2ban-client set sshd unbanip 1.2.3.4

# Посмотреть лог
journalctl -u fail2ban -f
```

### Бэкап
```bash
# База данных
cp /root/VPN_TG_APP/vpnapp.sqlite /root/VPN_TG_APP/vpnapp.sqlite.bak

# WireGuard конфиг
cp /etc/wireguard/awg0.conf /etc/wireguard/awg0.conf.bak

# .env (хранить в безопасном месте!)
cp /root/VPN_TG_APP/.env /root/VPN_TG_APP/.env.bak
```

### Обновление кода
```bash
cd /root/VPN_TG_APP
# Бэкап БД
cp vpnapp.sqlite "vpnapp.sqlite.bak.$(date +%Y%m%d_%H%M%S)"
# Обновление
git pull
# Зависимости
source .venv/bin/activate && pip install -r requirements.txt
# Перезапуск
systemctl restart vpn-backend vpn-bot
```

---

## 8. Типовые проблемы

| Проблема | Что проверить |
|---|---|
| Приложение не стартует | `journalctl -u vpn-backend -f` — обычно незаполненный `.env` |
| Бот не отвечает | `journalctl -u vpn-bot -f`, проверить `BOT_TOKEN` |
| Клиент не выходит в интернет | Порт 443/udp открыт (`ufw status`), включён ip_forward |
| 401/403 в API | `ADMIN_IDS` указан верно, `ADMIN_PASSWORD_HASH` совпадает с паролем |
| 503 на POST /users | `BOT_API_KEY` не настроен или не совпадает |
| fail2ban заблокировал вас | `fail2ban-client set sshd unbanip <ваш_IP>` через консоль провайдера |
| WireGuard не стартует | `systemctl status awg-quick@awg0`, проверить `/etc/wireguard/awg0.conf` |

---

## 9. Инструкция для ИИ-агента (Claude / Codex)

> Этот блок предназначен для передачи ИИ-агенту, у которого есть SSH-доступ к чистому Ubuntu 22.04 серверу.

---

### Контекст

Репозиторий: `https://github.com/lenin5558dif/vpn_bot`

Проект: Telegram-бот + FastAPI backend + AmneziaWG VPN на одном Ubuntu VPS.  
Стек: Python 3, aiogram 3, FastAPI, SQLite, AmneziaWG, systemd.

### Что нужно от пользователя перед началом

Попроси пользователя предоставить:
1. `BOT_TOKEN` — токен Telegram-бота от @BotFather
2. `ADMIN_IDS` — Telegram ID администратора (число, узнать у @userinfobot)
3. `ADMIN_PASSWORD` — пароль для веб-панели администратора

### Шаги установки

Выполни на сервере последовательно:

```bash
# 1. Клонировать репозиторий
cd /root
git clone https://github.com/lenin5558dif/vpn_bot.git VPN_TG_APP
cd VPN_TG_APP
```

```bash
# 2. Запустить автоматическую установку
# deploy.sh задаёт 4 интерактивных вопроса — передай значения через expect или heredoc:
BOT_TOKEN="<BOT_TOKEN_ОТ_ПОЛЬЗОВАТЕЛЯ>"
ADMIN_IDS="<TELEGRAM_ID_ОТ_ПОЛЬЗОВАТЕЛЯ>"
ADMIN_PASSWORD="<ПАРОЛЬ_ОТ_ПОЛЬЗОВАТЕЛЯ>"
ADMIN_USERNAME="admin"

# Используй expect для неинтерактивного запуска:
apt-get install -y expect > /dev/null

expect << 'EXPECTEOF'
set timeout 300
spawn bash /root/VPN_TG_APP/deploy.sh
expect "BOT_TOKEN"
send "$env(VPN_BOT_TOKEN)\r"
expect "ADMIN_IDS"
send "$env(VPN_ADMIN_IDS)\r"
expect "Пароль"
send "$env(VPN_ADMIN_PASSWORD)\r"
expect "Имя пользователя"
send "admin\r"
expect eof
EXPECTEOF
```

```bash
# 3. Проверить результат
systemctl status vpn-backend vpn-bot --no-pager
curl -sf http://localhost:8000/health
ufw status verbose
fail2ban-client status sshd
awg show awg0
```

### Что делает deploy.sh автоматически

- Устанавливает AmneziaWG (WireGuard с защитой от DPI) на порту 443/udp
- Генерирует ключи сервера, настраивает IP-forwarding и NAT
- Создаёт Python venv, устанавливает зависимости
- Генерирует все секреты (JWT_SECRET, ENCRYPTION_KEY, BOT_API_KEY)
- Создаёт `.env` с правами 600
- Запускает systemd-сервисы `vpn-backend` и `vpn-bot`
- Настраивает UFW: разрешает 22/tcp (SSH) и 443/udp (WireGuard)
- Настраивает fail2ban: постоянный бан SSH после 5 неудачных попыток за 10 минут

### Проверка успеха

Установка считается успешной, если:
- `curl http://localhost:8000/health` возвращает `{"status":"ok","db":"ok","wireguard":"ok"}`
- `systemctl is-active vpn-backend vpn-bot` возвращает `active` для обоих
- `awg show awg0` показывает интерфейс с ключом сервера
- `ufw status` показывает `Status: active` с правилами на 22/tcp и 443/udp
- `fail2ban-client status sshd` показывает jail как активный

### Важные файлы после установки

| Файл | Назначение |
|---|---|
| `/root/VPN_TG_APP/.env` | Все секреты (chmod 600) |
| `/root/VPN_TG_APP/vpnapp.sqlite` | База данных |
| `/etc/wireguard/awg0.conf` | Конфиг WireGuard |
| `/etc/wireguard/server_public.key` | Публичный ключ сервера |
| `/etc/fail2ban/jail.d/sshd-permanent.conf` | Конфиг fail2ban |

### Команды управления

```bash
# Перезапуск
systemctl restart vpn-backend vpn-bot

# Логи
journalctl -u vpn-backend --no-pager -n 50
journalctl -u vpn-bot --no-pager -n 50

# Разблокировать IP в fail2ban
fail2ban-client set sshd unbanip <IP>
```

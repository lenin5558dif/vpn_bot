# Установка VPN_TG_APP

Telegram-бот + VPN-сервер (AmneziaWG) на Ubuntu 22.04 / 24.04.  
Полная установка занимает ~5 минут после выполнения предварительных шагов.

---

## Содержание

1. [Предварительные требования](#1-предварительные-требования)
2. [Три вещи, которые нужно подготовить](#2-три-вещи-которые-нужно-подготовить)
3. [Подключение к серверу](#3-подключение-к-серверу)
4. [Клонирование репозитория](#4-клонирование-репозитория)
5. [Запуск установки](#5-запуск-установки)
6. [Проверка работы](#6-проверка-работы)
7. [Управление и обслуживание](#7-управление-и-обслуживание)
8. [Типовые проблемы](#8-типовые-проблемы)
9. [Инструкция для ИИ-агента (Claude / Codex)](#9-инструкция-для-ии-агента-claude--codex)

---

## 1. Предварительные требования

### Конфигурация сервера

| Параметр | Минимум | Рекомендуется |
|---|---|---|
| ОС | Ubuntu 22.04 LTS | Ubuntu 22.04 / 24.04 LTS |
| CPU | 1 vCPU | 1 vCPU |
| RAM | 512 MB | **2 GB** |
| Диск | 10 GB SSD | 20 GB SSD |
| Сеть | 100 Mbps | 1 Gbps, 2+ TB/мес |

> Проект рассчитан на 50–150 пользователей на одном VPS.  
> Поддерживается Ubuntu 22.04 и 24.04 (разница в путях AmneziaWG обрабатывается автоматически).  
> 2 GB RAM — рекомендуется: оставляет запас под пиковую нагрузку и системные процессы.

### Где купить сервер

**Вариант 1 — [Cloudzy](https://cloudzy.com)** (международные карты, крипта) — локация **США**:

- Принимает Visa/Mastercard и крипту
- Локация USA подходит для большинства сценариев обхода блокировок
- Ubuntu 22.04 / 24.04 доступны из коробки
- Тариф: **1 vCPU / 2 GB RAM / 20 GB SSD**

**Параметры при заказе Cloudzy:**
- OS: `Ubuntu 22.04 LTS` или `Ubuntu 24.04 LTS`
- Location: `United States`
- Root-доступ по SSH включён по умолчанию

---

**Вариант 2 — [RUVDS.com](https://ruvds.com)** (российские карты, СБП, крипта):

- Принимает российские карты, СБП, крипту
- Локации за рубежом: Нидерланды, Германия, Финляндия, США и другие
- Ubuntu 22.04 / 24.04 доступны
- Тариф: **1 vCPU / 2 GB RAM / 20 GB SSD** (линейка «Стандарт»)

**Параметры при заказе RUVDS:**
- ОС: `Ubuntu 22.04 LTS` или `Ubuntu 24.04 LTS`
- Локация: любая за пределами РФ (например, Нидерланды или США)
- Root-доступ включён по умолчанию

### Что нужно знать для подключения к серверу
Когда будете давать доступ к серверу (себе или ИИ-агенту), понадобится:
- **IP сервера** — публичный IPv4, выдаётся провайдером VPS
- **SSH логин** — обычно `root` (у большинства провайдеров по умолчанию)
- **Способ входа** — пароль или SSH-ключ (зависит от настроек сервера)
- **SSH порт** — по умолчанию `22`, если не меняли

---

## 2. Три вещи, которые нужно подготовить

Перед запуском установки нужно получить три значения. Без них скрипт не запустится.

---

### A. BOT_TOKEN — токен Telegram-бота

1. Откройте Telegram на телефоне или компьютере
2. В поиске найдите **@BotFather** (официальный бот Telegram, синяя галочка)
3. Нажмите **Start** или отправьте `/start`
4. Отправьте команду `/newbot`
5. BotFather спросит **имя бота** — это отображаемое имя, можно любое:
   ```
   MyCompany VPN
   ```
6. Затем спросит **username** — уникальный адрес бота, должен заканчиваться на `bot`:
   ```
   mycompany_vpn_bot
   ```
7. BotFather пришлёт сообщение с токеном вида:
   ```
   7123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw
   ```
8. Скопируйте этот токен целиком — это ваш **BOT_TOKEN**

> Токен — это пароль от вашего бота. Никому не передавайте.

---

### B. ADMIN_IDS — ваш Telegram ID

Это числовой идентификатор вашего аккаунта в Telegram. Именно с вашего аккаунта вы будете одобрять заявки на VPN.

1. В поиске Telegram найдите **@userinfobot**
2. Нажмите **Start** или отправьте `/start`
3. Бот ответит примерно так:
   ```
   Id: 123456789
   First: Иван
   Last: Петров
   ```
4. Скопируйте число после `Id:` — это ваш **ADMIN_IDS**

> Если администраторов несколько — укажите их ID через запятую: `123456789,987654321`

---

### C. ADMIN_PASSWORD — пароль для веб-панели

Это пароль, которым вы будете входить в веб-интерфейс управления. Придумайте надёжный пароль (мин. 8 символов, желательно с цифрами и спецсимволами).

Можно сгенерировать случайный прямо в терминале:
```bash
openssl rand -base64 16
```
Пример результата: `K7mPx2vQnR8sLwYj`

> Сохраните этот пароль в надёжном месте — восстановить его без доступа к серверу нельзя.

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

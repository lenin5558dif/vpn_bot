# DEPLOY_AGENT — инструкция для AI-агента

Ты AI-агент с SSH-доступом к серверу Ubuntu 22.04+.  
Твоя задача: развернуть VPN-сервис с Telegram-ботом за ~5 минут.  
Следуй шагам строго по порядку.

---

## Шаг 0. Запроси у пользователя три вещи

Прежде чем что-либо делать на сервере — спроси эти три значения и объясни, где их взять:

---

**1. BOT_TOKEN** — токен Telegram-бота.

Если у пользователя ещё нет бота, скажи ему:
> Открой Telegram → найди @BotFather → отправь `/newbot` → придумай имя и username (должен заканчиваться на `bot`) → скопируй токен вида `7123456789:AAH...`

---

**2. ADMIN_IDS** — числовой Telegram ID администратора.

Скажи пользователю:
> Открой Telegram → найди @userinfobot → отправь `/start` → скопируй число после `Id:`

Если администраторов несколько — ID через запятую: `123456789,987654321`

---

**3. ADMIN_PASSWORD** — пароль для веб-панели администратора.

Скажи пользователю:
> Придумай надёжный пароль (мин. 8 символов) или сгенерируй: `openssl rand -base64 16`
> Сохрани его — восстановить без доступа к серверу нельзя.

---

Без этих трёх значений установка невозможна. Не продолжай до получения ответов.

---

## Шаг 1. Клонировать репозиторий

```bash
cd /root
git clone https://github.com/lenin5558dif/vpn_bot.git VPN_TG_APP
```

---

## Шаг 2. Запустить установку (неинтерактивно)

Подставь реальные значения в переменные и выполни весь блок целиком:

```bash
export VPN_BOT_TOKEN="СЮДА_BOT_TOKEN"
export VPN_ADMIN_IDS="СЮДА_ADMIN_IDS"
export VPN_ADMIN_PASSWORD="СЮДА_ADMIN_PASSWORD"

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

> `expect << 'EXPECTEOF'` — одинарные кавычки, bash не интерполирует.  
> Переменные читаются через `$env(...)` внутри Tcl/expect.  
> `set timeout 300` — ждать до 5 минут (установка пакетов может занять время).

---

## Шаг 3. Проверить результат

Выполни все проверки и убедись, что каждая прошла успешно:

```bash
# 1. Сервисы запущены
systemctl is-active vpn-backend vpn-bot

# 2. API отвечает корректно
curl -sf http://localhost:8000/health

# 3. WireGuard работает
awg show awg0

# 4. Файрвол активен
ufw status verbose

# 5. fail2ban работает
fail2ban-client status sshd
```

### Ожидаемые результаты

| Проверка | Ожидаемый результат |
|---|---|
| `systemctl is-active vpn-backend` | `active` |
| `systemctl is-active vpn-bot` | `active` |
| `curl /health` | `{"status":"ok","db":"ok","wireguard":"ok"}` |
| `awg show awg0` | Показывает интерфейс с публичным ключом |
| `ufw status` | `Status: active`, открыты 22/tcp и 443/udp |
| `fail2ban-client status sshd` | Jail активен |

---

## Шаг 4. Сообщи пользователю

Если все проверки прошли, сообщи пользователю:

```
✅ VPN-сервис развёрнут успешно!

🤖 Бот: найди своего бота в Telegram и напиши /start
🔐 VPN: клиентам бот пришлёт .conf-файл для AmneziaWG
📱 Приложение: AmneziaWG (iOS / Android / Windows / macOS)

Управление на сервере:
  systemctl restart vpn-backend vpn-bot  — перезапуск
  journalctl -u vpn-bot -f               — логи бота
  fail2ban-client status sshd            — заблокированные IP
```

---

## Если что-то пошло не так

| Симптом | Действие |
|---|---|
| `vpn-backend` не active | `journalctl -u vpn-backend -n 50 --no-pager` — найди ошибку |
| `vpn-bot` не active | `journalctl -u vpn-bot -n 50 --no-pager` — чаще всего неверный BOT_TOKEN |
| `curl /health` — connection refused | Backend не стартовал, смотри логи выше |
| `awg show awg0` — ошибка | `systemctl status awg-quick@awg0` |
| expect завис | Нажми Ctrl+C, запусти `bash /root/VPN_TG_APP/deploy.sh` вручную |

---

## Важные файлы после установки

| Файл | Что содержит |
|---|---|
| `/root/VPN_TG_APP/.env` | Все секреты (chmod 600, не показывай) |
| `/root/VPN_TG_APP/vpnapp.sqlite` | База данных пользователей и пиров |
| `/etc/wireguard/awg0.conf` | Конфиг WireGuard-сервера |
| `/etc/fail2ban/jail.d/ssh-progressive.conf` | Правила прогрессивного бана |

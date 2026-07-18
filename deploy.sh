#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# VPN_TG_APP — автоматический деплой на чистый Ubuntu 22.04+
# Запуск: curl -sL <url>/deploy.sh | bash
# ============================================================

APP_DIR="/root/VPN_TG_APP"
VENV_DIR="$APP_DIR/.venv"
WG_IFACE="awg0"
WG_PORT="443"
WG_NETWORK="10.10.0.0/24"
WG_SERVER_IP="10.10.0.1/24"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

env_value() {
    local file="$1"
    local key="$2"
    [[ -f "$file" ]] || return 0
    awk -F= -v k="$key" '$1 == k {sub(/^[^=]*=/, ""); print; exit}' "$file"
}

# -----------------------------------------------------------
# 1. Проверки
# -----------------------------------------------------------
[[ $EUID -ne 0 ]] && error "Запусти от root: sudo bash deploy.sh"

info "Проверяю систему..."
. /etc/os-release 2>/dev/null || true
echo "  OS: ${PRETTY_NAME:-unknown}"
echo "  RAM: $(free -m | awk '/Mem:/{print $2}') MB"
echo "  Disk: $(df -h / | awk 'NR==2{print $4}') free"

# -----------------------------------------------------------
# 2. Запрос данных у пользователя
# -----------------------------------------------------------
echo ""
warn "Нужны 3 вещи, которые нельзя сгенерировать автоматически:"
echo ""

EXISTING_ENV="$APP_DIR/.env"
OLD_BOT_TOKEN="$(env_value "$EXISTING_ENV" BOT_TOKEN)"
OLD_ADMIN_IDS="$(env_value "$EXISTING_ENV" ADMIN_IDS)"
OLD_ADMIN_USERNAME="$(env_value "$EXISTING_ENV" ADMIN_USERNAME)"
OLD_ADMIN_PASSWORD_HASH="$(env_value "$EXISTING_ENV" ADMIN_PASSWORD_HASH)"

read -rp "$(echo -e ${YELLOW})BOT_TOKEN (от @BotFather)${OLD_BOT_TOKEN:+ [оставить текущий]}: $(echo -e ${NC})" BOT_TOKEN
BOT_TOKEN="${BOT_TOKEN:-$OLD_BOT_TOKEN}"
[[ -z "$BOT_TOKEN" ]] && error "BOT_TOKEN обязателен"

read -rp "$(echo -e ${YELLOW})ADMIN_IDS (Telegram ID админа, через запятую)${OLD_ADMIN_IDS:+ [${OLD_ADMIN_IDS}]}: $(echo -e ${NC})" ADMIN_IDS
ADMIN_IDS="${ADMIN_IDS:-$OLD_ADMIN_IDS}"
[[ -z "$ADMIN_IDS" ]] && error "ADMIN_IDS обязателен"

read -rsp "$(echo -e ${YELLOW})Пароль админа для веб-панели${OLD_ADMIN_PASSWORD_HASH:+ [Enter — оставить текущий]}: $(echo -e ${NC})" ADMIN_PASSWORD
echo ""
[[ -z "$ADMIN_PASSWORD" && -z "$OLD_ADMIN_PASSWORD_HASH" ]] && error "Пароль обязателен"

read -rp "$(echo -e ${YELLOW})Имя пользователя админа [${OLD_ADMIN_USERNAME:-admin}]: $(echo -e ${NC})" ADMIN_USERNAME
ADMIN_USERNAME="${ADMIN_USERNAME:-${OLD_ADMIN_USERNAME:-admin}}"

# -----------------------------------------------------------
# 3. Установка системных зависимостей
# -----------------------------------------------------------
info "Устанавливаю системные пакеты..."
apt-get update -qq
add-apt-repository -y ppa:amnezia/ppa > /dev/null 2>&1
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip \
    amneziawg amneziawg-tools wireguard-tools iproute2 iptables curl > /dev/null

# -----------------------------------------------------------
# 4. Настройка WireGuard
# -----------------------------------------------------------
if [[ ! -f /etc/wireguard/${WG_IFACE}.conf ]] && [[ ! -f /etc/amnezia/amneziawg/${WG_IFACE}.conf ]]; then
    info "Настраиваю WireGuard..."

    # Генерация ключей
    umask 077
    mkdir -p /etc/wireguard
    awg genkey | tee /etc/wireguard/server_private.key | awg pubkey > /etc/wireguard/server_public.key

    SERVER_PRIVATE_KEY=$(cat /etc/wireguard/server_private.key)
    SERVER_PUBLIC_KEY=$(cat /etc/wireguard/server_public.key)

    # Определяю внешний интерфейс
    DEFAULT_IFACE=$(ip route show default | awk '{print $5}' | head -1)
    [[ -z "$DEFAULT_IFACE" ]] && DEFAULT_IFACE="eth0"

    cat > /etc/wireguard/${WG_IFACE}.conf << WGEOF
[Interface]
Address = ${WG_SERVER_IP}
MTU = 1420
SaveConfig = true
PostUp = iptables -A FORWARD -i %i -j ACCEPT; iptables -A FORWARD -o %i -j ACCEPT; iptables -t nat -A POSTROUTING -o ${DEFAULT_IFACE} -j MASQUERADE
PostDown = iptables -D FORWARD -i %i -j ACCEPT; iptables -D FORWARD -o %i -j ACCEPT; iptables -t nat -D POSTROUTING -o ${DEFAULT_IFACE} -j MASQUERADE
ListenPort = ${WG_PORT}
Jc = 4
Jmin = 40
Jmax = 70
S1 = 0
S2 = 0
H1 = 1
H2 = 2
H3 = 3
H4 = 4
PrivateKey = ${SERVER_PRIVATE_KEY}
WGEOF

    # Ubuntu 24.04: awg-quick ищет конфиг в /etc/amnezia/amneziawg/
    mkdir -p /etc/amnezia/amneziawg
    ln -sf /etc/wireguard/${WG_IFACE}.conf /etc/amnezia/amneziawg/${WG_IFACE}.conf
    info "Симлинк /etc/amnezia/amneziawg/${WG_IFACE}.conf → /etc/wireguard/${WG_IFACE}.conf (совместимость Ubuntu 24.04)"

    # IP forwarding
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wg-forward.conf
    sysctl -p /etc/sysctl.d/99-wg-forward.conf > /dev/null

    # Запуск WireGuard
    systemctl enable --now awg-quick@${WG_IFACE}
    info "WireGuard запущен на порту ${WG_PORT}"
else
    info "WireGuard уже настроен, пропускаю"
    SERVER_PUBLIC_KEY=$(cat /etc/wireguard/server_public.key 2>/dev/null || awg show ${WG_IFACE} public-key)
fi

# Внешний IP сервера
SERVER_IP=$(curl -s4 ifconfig.me || hostname -I | awk '{print $1}')
info "Внешний IP: ${SERVER_IP}"

# -----------------------------------------------------------
# 5. Код приложения
# -----------------------------------------------------------
if [[ -d "$APP_DIR/.git" ]]; then
    info "Обновляю код..."
    cd "$APP_DIR"
    BACKUP_DIR="$APP_DIR/backups/$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$BACKUP_DIR"
    chmod 700 "$BACKUP_DIR"
    [[ -f .env ]] && cp .env "$BACKUP_DIR/.env"
    [[ -f vpnapp.sqlite ]] && cp vpnapp.sqlite "$BACKUP_DIR/vpnapp.sqlite"
    [[ -f "/etc/wireguard/${WG_IFACE}.conf" ]] && cp "/etc/wireguard/${WG_IFACE}.conf" "$BACKUP_DIR/${WG_IFACE}.conf"
    chmod 600 "$BACKUP_DIR"/* "$BACKUP_DIR"/.env 2>/dev/null || true
    info "Backup сохранён: $BACKUP_DIR"
else
    info "Копирую код приложения..."
    mkdir -p "$APP_DIR"
    # Если запущено из директории с кодом
    if [[ -f "$(dirname "$0")/app/main.py" ]]; then
        cp -r "$(dirname "$0")"/* "$APP_DIR"/
        cp -r "$(dirname "$0")"/.env* "$APP_DIR"/ 2>/dev/null || true
        cp -r "$(dirname "$0")"/.gitignore "$APP_DIR"/ 2>/dev/null || true
    fi
fi
cd "$APP_DIR"

# -----------------------------------------------------------
# 6. Python venv + зависимости
# -----------------------------------------------------------
info "Настраиваю Python окружение..."
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"
pip install -q --upgrade pip > /dev/null
pip install -q -r requirements.txt

# -----------------------------------------------------------
# 7. Генерация секретов и .env
# -----------------------------------------------------------
info "Генерирую секреты..."

OLD_JWT_SECRET="$(env_value "$APP_DIR/.env" JWT_SECRET)"
OLD_ENCRYPTION_KEY="$(env_value "$APP_DIR/.env" ENCRYPTION_KEY)"
OLD_BOT_API_KEY="$(env_value "$APP_DIR/.env" BOT_API_KEY)"
OLD_ADMIN_PASSWORD_HASH="$(env_value "$APP_DIR/.env" ADMIN_PASSWORD_HASH)"

JWT_SECRET="${OLD_JWT_SECRET:-$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")}"
ENCRYPTION_KEY="${OLD_ENCRYPTION_KEY:-$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")}"
BOT_API_KEY="${OLD_BOT_API_KEY:-$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")}"
if [[ -n "$ADMIN_PASSWORD" ]]; then
    ADMIN_PASSWORD_HASH=$(ADMIN_PASSWORD_PLAIN="$ADMIN_PASSWORD" python3 - <<'PY'
import os
from passlib.context import CryptContext

print(CryptContext(schemes=["bcrypt"]).hash(os.environ["ADMIN_PASSWORD_PLAIN"]))
PY
)
else
    ADMIN_PASSWORD_HASH="$OLD_ADMIN_PASSWORD_HASH"
fi

cat > "$APP_DIR/.env" << ENVEOF
# Database
DATABASE_URL=sqlite+aiosqlite:///./vpnapp.sqlite

# Backend
BACKEND_HOST=0.0.0.0
BACKEND_PORT=8000
BACKEND_URL=http://localhost:8000
JWT_SECRET=${JWT_SECRET}
JWT_ALG=HS256
ADMIN_USERNAME=${ADMIN_USERNAME}
ADMIN_PASSWORD_HASH=${ADMIN_PASSWORD_HASH}

# Encryption
ENCRYPTION_KEY=${ENCRYPTION_KEY}

# Bot API Key
BOT_API_KEY=${BOT_API_KEY}

# Telegram
BOT_TOKEN=${BOT_TOKEN}
ADMIN_IDS=${ADMIN_IDS}

# WireGuard
WG_INTERFACE=${WG_IFACE}
WG_ENDPOINT=${SERVER_IP}:${WG_PORT}
WG_NETWORK=${WG_NETWORK}
WG_MTU=1420
WG_KEEPALIVE=25
DEFAULT_SPEED_LIMIT_MBIT=20
SERVER_PUBLIC_KEY=${SERVER_PUBLIC_KEY}

# Bot alerts
ALERTS_ENABLED=true
ALERTS_HEALTH_INTERVAL_SEC=60
ALERTS_DIAGNOSTIC_INTERVAL_SEC=300
ALERTS_FAILURE_THRESHOLD=3
ALERTS_TRAFFIC_24H_THRESHOLD_GB=50
ALERTS_DISK_WARN_PCT=80
ALERTS_DISK_RECOVERY_PCT=75
ALERTS_REPEAT_HOURS=6
ALERTS_STATE_FILE=/var/lib/vpn-tg-app/bot-alerts-state.json

# CORS
CORS_ORIGINS=http://localhost:3000
ENVEOF

chmod 600 "$APP_DIR/.env"
info ".env создан (chmod 600)"

mkdir -p /var/lib/vpn-tg-app
chmod 700 /var/lib/vpn-tg-app
[[ -s /var/lib/vpn-tg-app/bot-alerts-state.json ]] || printf '{}\n' > /var/lib/vpn-tg-app/bot-alerts-state.json
chmod 600 /var/lib/vpn-tg-app/bot-alerts-state.json

# -----------------------------------------------------------
# 8. Миграция ключей (если есть старая БД)
# -----------------------------------------------------------
if [[ -f "$APP_DIR/vpnapp.sqlite" ]]; then
    info "Найдена существующая БД, мигрирую ключи..."
    python3 "$APP_DIR/scripts/migrate_encrypt_keys.py"
fi

# -----------------------------------------------------------
# 9. Systemd сервисы
# -----------------------------------------------------------
info "Создаю systemd сервисы..."

cat > /etc/systemd/system/vpn-backend.service << SVCEOF
[Unit]
Description=VPN Admin API Backend
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${VENV_DIR}/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000
Restart=always
RestartSec=5
Environment=PYTHONPATH=${APP_DIR}

[Install]
WantedBy=multi-user.target
SVCEOF

cat > /etc/systemd/system/vpn-bot.service << SVCEOF
[Unit]
Description=VPN Telegram Bot
After=vpn-backend.service
Requires=vpn-backend.service

[Service]
Type=simple
User=root
WorkingDirectory=${APP_DIR}
ExecStart=${VENV_DIR}/bin/python -m bot.main
Restart=always
RestartSec=5
Environment=PYTHONPATH=${APP_DIR}

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable --now vpn-backend.service vpn-bot.service

# Ждём старт
sleep 3

# -----------------------------------------------------------
# 10. Безопасность: UFW + fail2ban
# -----------------------------------------------------------
info "Настраиваю файрвол (UFW)..."
apt-get install -y -qq ufw > /dev/null

# Сброс до умолчаний без интерактивного подтверждения
ufw --force reset > /dev/null

ufw default deny incoming
ufw default allow outgoing

# SSH
ufw allow 22/tcp comment 'SSH'

# AmneziaWG (WireGuard)
ufw allow ${WG_PORT}/udp comment 'AmneziaWG'

# Включаем без интерактивного подтверждения
ufw --force enable
info "UFW включён: разрешены 22/tcp (SSH) и ${WG_PORT}/udp (WireGuard)"

# -----------------------------------------------------------
info "Настраиваю fail2ban (4-уровневый прогрессивный бан SSH)..."
apt-get install -y -qq fail2ban > /dev/null

# fail2ban должен писать в файл (нужно для recidive-фильтров)
sed -i 's|^logtarget.*|logtarget = /var/log/fail2ban.log|' \
    /etc/fail2ban/fail2ban.conf 2>/dev/null || true

cat > /etc/fail2ban/jail.local << F2BEOF
[DEFAULT]
banaction = iptables-multiport

# Уровень 1: 3 ошибки за 10 мин → бан 20 минут
[sshd]
enabled  = true
port     = ssh
logpath  = %(sshd_log)s
backend  = systemd
maxretry = 3
findtime = 600
bantime  = 1200

# Уровень 2: 2 бана за 1 час → бан 3 часа
[recidive-3h]
enabled   = true
filter    = recidive
logpath   = /var/log/fail2ban.log
maxretry  = 2
findtime  = 3600
bantime   = 10800
banaction = iptables-allports

# Уровень 3: 3 бана за 12 часов → бан 24 часа
[recidive-24h]
enabled   = true
filter    = recidive
logpath   = /var/log/fail2ban.log
maxretry  = 3
findtime  = 43200
bantime   = 86400
banaction = iptables-allports

# Уровень 4: 4 бана за 2 дня → бан навсегда
[recidive-permanent]
enabled   = true
filter    = recidive
logpath   = /var/log/fail2ban.log
maxretry  = 4
findtime  = 172800
bantime   = -1
banaction = iptables-allports
F2BEOF

systemctl enable --now fail2ban
systemctl restart fail2ban
info "fail2ban: 4 уровня — 20 мин → 3 ч → 24 ч → навсегда"

# -----------------------------------------------------------
# 11. Проверка
# -----------------------------------------------------------
info "Проверяю..."

if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
    HEALTH=$(curl -s http://localhost:8000/health)
    info "Backend: OK — ${HEALTH}"
else
    warn "Backend не отвечает. Проверь: journalctl -u vpn-backend -f"
fi

if systemctl is-active --quiet vpn-bot.service; then
    info "Bot: OK (active)"
else
    warn "Bot не запущен. Проверь: journalctl -u vpn-bot -f"
fi

# -----------------------------------------------------------
# Готово
# -----------------------------------------------------------
echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  VPN_TG_APP успешно развёрнут!${NC}"
echo -e "${GREEN}============================================${NC}"
echo ""
echo "  API:        http://localhost:8000"
echo "  Health:     http://localhost:8000/health"
echo "  WireGuard:  ${SERVER_IP}:${WG_PORT}"
echo "  Admin user: ${ADMIN_USERNAME}"
echo ""
echo "  Управление:"
echo "    systemctl status vpn-backend vpn-bot"
echo "    systemctl restart vpn-backend vpn-bot"
echo "    journalctl -u vpn-backend -f"
echo "    journalctl -u vpn-bot -f"
echo ""
echo "  Безопасность:"
echo "    ufw status verbose"
echo "    fail2ban-client status sshd"
echo "    fail2ban-client set sshd unbanip <IP>   # разбанить вручную"
echo ""
echo "  Файлы:"
echo "    Код:    ${APP_DIR}"
echo "    .env:   ${APP_DIR}/.env"
echo "    БД:     ${APP_DIR}/vpnapp.sqlite"
echo "    WG:     /etc/wireguard/${WG_IFACE}.conf"
echo "    f2b:    /etc/fail2ban/jail.local"
echo ""

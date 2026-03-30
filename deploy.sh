#!/usr/bin/env bash
set -euo pipefail

# ============================================================
# VPN_TG_APP — автоматический деплой на чистый Ubuntu 22.04+
# Запуск: curl -sL <url>/deploy.sh | bash
# ============================================================

APP_DIR="/root/VPN_TG_APP"
VENV_DIR="$APP_DIR/.venv"
WG_IFACE="wg0"
WG_PORT="51820"
WG_NETWORK="10.10.0.0/24"
WG_SERVER_IP="10.10.0.1/24"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

info()  { echo -e "${GREEN}[+]${NC} $1"; }
warn()  { echo -e "${YELLOW}[!]${NC} $1"; }
error() { echo -e "${RED}[✗]${NC} $1"; exit 1; }

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

read -rp "$(echo -e ${YELLOW})BOT_TOKEN (от @BotFather): $(echo -e ${NC})" BOT_TOKEN
[[ -z "$BOT_TOKEN" ]] && error "BOT_TOKEN обязателен"

read -rp "$(echo -e ${YELLOW})ADMIN_IDS (Telegram ID админа, через запятую): $(echo -e ${NC})" ADMIN_IDS
[[ -z "$ADMIN_IDS" ]] && error "ADMIN_IDS обязателен"

read -rsp "$(echo -e ${YELLOW})Пароль админа для веб-панели: $(echo -e ${NC})" ADMIN_PASSWORD
echo ""
[[ -z "$ADMIN_PASSWORD" ]] && error "Пароль обязателен"

read -rp "$(echo -e ${YELLOW})Имя пользователя админа [admin]: $(echo -e ${NC})" ADMIN_USERNAME
ADMIN_USERNAME="${ADMIN_USERNAME:-admin}"

# -----------------------------------------------------------
# 3. Установка системных зависимостей
# -----------------------------------------------------------
info "Устанавливаю системные пакеты..."
apt-get update -qq
apt-get install -y -qq python3 python3-venv python3-pip \
    wireguard wireguard-tools iproute2 iptables curl > /dev/null

# -----------------------------------------------------------
# 4. Настройка WireGuard
# -----------------------------------------------------------
if [[ ! -f /etc/wireguard/${WG_IFACE}.conf ]]; then
    info "Настраиваю WireGuard..."

    # Генерация ключей
    umask 077
    wg genkey | tee /etc/wireguard/server_private.key | wg pubkey > /etc/wireguard/server_public.key

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
PrivateKey = ${SERVER_PRIVATE_KEY}
WGEOF

    # IP forwarding
    echo "net.ipv4.ip_forward=1" > /etc/sysctl.d/99-wg-forward.conf
    sysctl -p /etc/sysctl.d/99-wg-forward.conf > /dev/null

    # Запуск WireGuard
    systemctl enable --now wg-quick@${WG_IFACE}
    info "WireGuard запущен на порту ${WG_PORT}"
else
    info "WireGuard уже настроен, пропускаю"
    SERVER_PUBLIC_KEY=$(cat /etc/wireguard/server_public.key 2>/dev/null || wg show ${WG_IFACE} public-key)
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
    # Бэкап
    [[ -f vpnapp.sqlite ]] && cp vpnapp.sqlite "vpnapp.sqlite.bak.$(date +%Y%m%d_%H%M%S)"
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

JWT_SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
BOT_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
ADMIN_PASSWORD_HASH=$(python3 -c "from passlib.context import CryptContext; print(CryptContext(schemes=['bcrypt']).hash('${ADMIN_PASSWORD}'))")

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
ADMIN_PASSWORD=${ADMIN_PASSWORD}
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

# CORS
CORS_ORIGINS=http://localhost:3000
ENVEOF

chmod 600 "$APP_DIR/.env"
info ".env создан (chmod 600)"

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
# 10. Проверка
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
echo "  Файлы:"
echo "    Код:    ${APP_DIR}"
echo "    .env:   ${APP_DIR}/.env"
echo "    БД:     ${APP_DIR}/vpnapp.sqlite"
echo "    WG:     /etc/wireguard/${WG_IFACE}.conf"
echo ""

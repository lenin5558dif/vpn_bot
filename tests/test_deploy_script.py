from pathlib import Path


DEPLOY_SCRIPT = Path(__file__).resolve().parents[1] / "deploy.sh"


def test_deploy_script_reuses_existing_encryption_key():
    script = DEPLOY_SCRIPT.read_text()

    assert 'OLD_ENCRYPTION_KEY="$(env_value "$APP_DIR/.env" ENCRYPTION_KEY)"' in script
    assert 'ENCRYPTION_KEY="${OLD_ENCRYPTION_KEY:-$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")}"' in script


def test_deploy_script_does_not_write_plaintext_admin_password_to_env():
    env_block = DEPLOY_SCRIPT.read_text().split('cat > "$APP_DIR/.env" << ENVEOF', 1)[1].split("ENVEOF", 1)[0]

    assert "ADMIN_PASSWORD=" not in env_block
    assert "ADMIN_PASSWORD_HASH=" in env_block


def test_deploy_script_hashes_admin_password_without_interpolating_into_python_code():
    script = DEPLOY_SCRIPT.read_text()
    hash_block = script.split('if [[ -n "$ADMIN_PASSWORD" ]]; then', 1)[1].split("else", 1)[0]

    assert 'ADMIN_PASSWORD_PLAIN="$ADMIN_PASSWORD" python3 - <<' in hash_block
    assert 'os.environ["ADMIN_PASSWORD_PLAIN"]' in hash_block
    assert "hash('${ADMIN_PASSWORD}')" not in script


def test_deploy_script_backs_up_env_database_and_wireguard_config_together():
    script = DEPLOY_SCRIPT.read_text()

    assert 'cp .env "$BACKUP_DIR/.env"' in script
    assert 'cp vpnapp.sqlite "$BACKUP_DIR/vpnapp.sqlite"' in script
    assert 'cp "/etc/wireguard/${WG_IFACE}.conf" "$BACKUP_DIR/${WG_IFACE}.conf"' in script

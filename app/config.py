from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import BaseModel


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://vpnapp:vpnapp@localhost:5432/vpnapp"

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_url: str = "http://localhost:8000"
    jwt_secret: str = "change_me"
    jwt_alg: str = "HS256"
    env: str = "development"
    admin_username: str = "admin"
    admin_password: str = ""
    admin_password_hash: str = ""

    # Encryption (Fernet key for WireGuard private keys at rest)
    encryption_key: str = ""

    # Bot-to-backend shared API key
    bot_api_key: str = ""

    # Telegram
    bot_token: str | None = None
    admin_ids: str | None = None  # comma-separated

    # WireGuard
    wg_interface: str = "wg0"
    wg_endpoint: str = "example.com:51820"
    wg_network: str = "10.10.0.0/24"
    wg_mtu: int = 1420
    wg_keepalive: int = 25
    default_speed_limit_mbit: int = 20
    server_public_key: str = ""

    # CORS
    cors_origins: str = "http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False, extra="ignore")


class AppContext(BaseModel):
    settings: Settings


@lru_cache
def get_settings() -> Settings:
    return Settings()

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import audit, auth, health, peers, requests, traffic, users
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.logging_config import setup_logging
from app.tasks import TrafficPoller

setup_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
poller = TrafficPoller(SessionLocal, settings.wg_interface)
limiter = Limiter(key_func=get_remote_address)


def _validate_config() -> None:
    """Fail fast if required settings are missing."""
    errors = []
    if not settings.encryption_key:
        errors.append("ENCRYPTION_KEY is not set")
    if not settings.server_public_key:
        errors.append("SERVER_PUBLIC_KEY is not set")
    if not settings.admin_password_hash:
        errors.append("ADMIN_PASSWORD_HASH is not set")
    if not settings.bot_api_key:
        errors.append("BOT_API_KEY is not set")
    if errors:
        for e in errors:
            logger.error("CONFIG ERROR: %s", e)
        raise RuntimeError("Missing required config: " + "; ".join(errors))


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_config()
    await init_db()
    poller.start()
    yield
    await poller.stop()


app = FastAPI(title="VPN Admin API", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "X-Bot-Api-Key"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.middleware("http")
async def limit_request_size(request: Request, call_next) -> Response:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 1_000_000:
                return Response("Request too large", status_code=413)
        except ValueError:
            return Response("Invalid content-length", status_code=400)
    return await call_next(request)


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(requests.router)
app.include_router(peers.router)
app.include_router(traffic.router)
app.include_router(audit.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "VPN Admin API"}

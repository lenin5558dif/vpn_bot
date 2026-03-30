import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.logging_config import setup_logging

setup_logging()
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api import audit, auth, health, peers, requests, traffic, users
from app.config import get_settings
from app.database import SessionLocal, init_db
from app.tasks import TrafficPoller

settings = get_settings()
poller = TrafficPoller(SessionLocal, settings.wg_interface)

limiter = Limiter(key_func=get_remote_address)


logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.env != "production":
        logger.warning("Running create_all (dev mode). Use 'alembic upgrade head' in production.")
        await init_db()
    poller.start()
    yield
    await poller.stop()


app = FastAPI(
    title="VPN Admin API",
    lifespan=lifespan,
    docs_url=None if settings.env == "production" else "/docs",
    redoc_url=None if settings.env == "production" else "/redoc",
    openapi_url=None if settings.env == "production" else "/openapi.json",
)
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
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com"
    )
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
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

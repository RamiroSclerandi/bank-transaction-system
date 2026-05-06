"""
FastAPI application entrypoint.
Configures:
- Lifespan (startup/shutdown)
- CORS with an explicit allow-list (never '*')
- Rate limiting via slowapi
- Loguru logging with PII masking
- Health check endpoint
- API v1 router
"""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from sqlalchemy import text
from utils.logging import setup_logging

from app.api.api_v1.api import api_router
from app.core.config import settings
from app.db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Application lifespan handler — startup and shutdown logic.

    Args:
    ----
        app: The FastAPI application instance.

    Yields:
    ------
        Control to the running application.

    """
    log_level = "DEBUG" if settings.DEBUG else "INFO"
    setup_logging(log_level=log_level)

    logger.info(
        "Starting {app_name} v{version} [{env}]",
        app_name=settings.APP_NAME,
        version=settings.APP_VERSION,
        env=settings.ENVIRONMENT,
    )
    yield
    logger.info("Application shutdown complete.")


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# ── Rate limiting ──
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type", "X-Internal-Api-Key"],
)


# ── Health check ──
@app.get(
    "/health",
    tags=["health"],
    summary="Liveness probe",
    status_code=status.HTTP_200_OK,
)
async def health_check() -> JSONResponse:
    """
    Return a simple liveness response. Used by ECS health checks, load balancers
    and the Docker HEALTHCHECK instruction.

    Returns
    -------
        JSON body ``{"status": "ok"}``.

    """
    return JSONResponse(content={"status": "ok"})


@app.get(
    "/readiness",
    tags=["health"],
    summary="Readiness probe — verifies DB connectivity",
    status_code=status.HTTP_200_OK,
)
async def readiness_check() -> JSONResponse:
    """
    Verify the application can reach the database.

    Returns
    -------
        JSON body with status and db ping result.

    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return JSONResponse(content={"status": "ok", "db": "ok"})
    except Exception:
        return JSONResponse(
            content={"status": "degraded", "db": "unreachable"},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


# ── API routes ──
app.include_router(api_router, prefix="/api/v1")

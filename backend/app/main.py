"""FreightOps AI FastAPI Application Entry Point."""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from backend.app.core.config import settings
from backend.app.core.errors import (
    FreightOpsHTTPException,
    freightops_exception_handler,
    validation_exception_handler,
)
from backend.app.api.router import api_router
from backend.app.api.v1.health import get_health, HealthResponse
from backend.app.ui.router import router as ui_router

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("freightops")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s in %s mode", settings.PROJECT_NAME, settings.VERSION, settings.ENVIRONMENT)
    logger.info("Configured Database URI: %s@%s:%s/%s", settings.POSTGRES_USER, settings.POSTGRES_SERVER, settings.POSTGRES_PORT, settings.POSTGRES_DB)
    logger.info("LLM provider: %s (demo mode=%s)", settings.LLM_PROVIDER, settings.LLM_DEMO_MODE)

    if settings.SEED_DEMO_DATA_ON_STARTUP:
        from backend.app.db.session import SessionLocal
        from backend.app.services.demo_seed import seed_all_demo_data

        try:
            with SessionLocal() as db:
                summary = seed_all_demo_data(db)
            logger.info("Synthetic demo data seeded: %s", summary)
        except Exception:
            logger.exception("Demo data seeding failed; application will continue")
    yield
    logger.info("Shutting down %s", settings.PROJECT_NAME)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="FreightOps AI - Freight Brokerage Operations Platform API",
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# Register RFC 9457 Problem Details Exception Handler
app.add_exception_handler(FreightOpsHTTPException, freightops_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# Set CORS middleware for frontend communication
if settings.BACKEND_CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[str(origin) for origin in settings.BACKEND_CORS_ORIGINS],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# Include UI router for server-rendered Jinja2 templates and HTMX partials (ADR-003)
app.include_router(ui_router)

# Include v1 API router under /api/v1
app.include_router(api_router, prefix=settings.API_V1_STR)

# Direct root /health endpoint for external scrapers and backward compatibility
@app.get("/health", response_model=HealthResponse, tags=["health"])
def root_health():
    """Root health endpoint forwarding to canonical health check."""
    return get_health()

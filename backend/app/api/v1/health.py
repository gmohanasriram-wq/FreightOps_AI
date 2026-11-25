"""Health check endpoints per Contract 2.2."""
from typing import Dict, Any, Optional
from fastapi import APIRouter
from pydantic import BaseModel
from backend.app.db.session import check_database_connection
from backend.app.core.config import settings

router = APIRouter()


class DatabaseStatus(BaseModel):
    connected: bool
    status: str
    message: str
    details: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    database: str
    llm_provider: str
    environment: str
    version: str
    database_details: DatabaseStatus
    instructions: Optional[str] = None


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    """Service health check endpoint per Contract 2.2 (09 §5.10).
    
    Verifies service vitality, checks real PostgreSQL connectivity, and
    reports live status without fabricating database availability.
    """
    is_connected, msg, details = check_database_connection()

    db_status = "ok" if is_connected else "unavailable"
    overall_status = "ok" if is_connected else "degraded"

    instructions = None
    if not is_connected:
        instructions = (
            "PostgreSQL is unavailable on configured host/port. "
            "To connect a local PostgreSQL instance: "
            "1. Start PostgreSQL (e.g. `docker run -d --name freightops-db -p 5432:5432 "
            "-e POSTGRES_USER=<your-user> -e POSTGRES_PASSWORD=<your-password> "
            "-e POSTGRES_DB=freightops postgres:16`) or start the local service. "
            "2. Set POSTGRES_USER and POSTGRES_PASSWORD (or DATABASE_URL) in `.env`; "
            "no default credentials are used."
        )

    return HealthResponse(
        status=overall_status,
        database=db_status,
        llm_provider="ready",
        environment=settings.ENVIRONMENT,
        version=settings.VERSION,
        database_details=DatabaseStatus(
            connected=is_connected,
            status=db_status,
            message=msg,
            details=details,
        ),
        instructions=instructions,
    )

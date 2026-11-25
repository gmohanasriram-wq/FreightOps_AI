"""Database connectivity and health evaluation."""
import logging
import socket
from typing import Tuple, Dict, Any
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

# Create SQLAlchemy engine with connection timeout and pre-ping
engine = create_engine(
    settings.SQLALCHEMY_DATABASE_URI,
    pool_pre_ping=True,
    connect_args={"connect_timeout": settings.DB_CONNECT_TIMEOUT_SECONDS},
)

# Standard session factory for FastAPI dependency injection
from sqlalchemy.orm import sessionmaker, Session

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    """FastAPI database session dependency."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()



def check_database_connection() -> Tuple[bool, str, Dict[str, Any]]:
    """Test connection to PostgreSQL without inventing or redesigning schemas.
    
    Uses a fast socket check followed by SQLAlchemy connection verification.
    Returns:
        (is_connected, message, details)
    """
    details: Dict[str, Any] = {
        "host": settings.POSTGRES_SERVER,
        "port": settings.POSTGRES_PORT,
        "database": settings.POSTGRES_DB,
        "user": settings.POSTGRES_USER,
    }

    # 1. Fast socket check to prevent health check endpoint hangs
    try:
        with socket.create_connection(
            (settings.POSTGRES_SERVER, settings.POSTGRES_PORT),
            timeout=1.0,
        ):
            pass
    except (socket.timeout, ConnectionRefusedError, OSError) as sock_err:
        err_msg = f"Connection refused or timed out on {settings.POSTGRES_SERVER}:{settings.POSTGRES_PORT}"
        logger.info("Database socket check failed: %s (%s)", err_msg, sock_err)
        details["error"] = f"{err_msg} ({sock_err})"
        return False, f"PostgreSQL unavailable: {err_msg}", details

    # 2. Database query check if socket opened
    try:
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version();"))
            row = result.fetchone()
            version_str = row[0] if row else "Unknown"
            details["server_version"] = version_str
            return True, "PostgreSQL connected successfully", details
    except SQLAlchemyError as err:
        err_msg = str(err.__cause__ or err)
        logger.warning("Database connectivity query failed: %s", err_msg)
        details["error"] = err_msg
        return False, f"PostgreSQL query failed: {err_msg}", details
    except Exception as exc:
        err_msg = str(exc)
        logger.warning("Unexpected error during database check: %s", err_msg)
        details["error"] = err_msg
        return False, f"Database check error: {err_msg}", details

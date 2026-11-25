"""Idempotency keys and in-flight concurrency leasing per Contract 2.2 §3.20 (F-API-03)."""
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, UUIDPrimaryKeyMixin


class IdempotencyKey(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "idempotency_keys"
    __table_args__ = (
        CheckConstraint(
            "status IN ('in_progress', 'completed', 'failed')",
            name="chk_idempotency_keys_status",
        ),
    )

    key: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    request_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="in_progress",
        server_default=text("'in_progress'"),
    )
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_body: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

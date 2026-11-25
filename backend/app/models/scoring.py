"""Scoring configuration model per Contract 2.2 §3.19."""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, UUIDPrimaryKeyMixin


class ScoringConfig(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "scoring_configs"
    __table_args__ = (
        Index(
            "uq_scoring_configs_active",
            "is_active",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    version: Mapped[int] = mapped_column(Integer, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    weights: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )
    activated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    creator = relationship("User", foreign_keys=[created_by])

"""Recommendation and candidate models per Contract 2.2 §3.13 & §3.14."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Recommendation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "recommendations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'computing', 'ready', 'no_eligible_carriers', "
            "'no_rankable_candidates', 'failed', 'superseded')",
            name="chk_recommendations_status",
        ),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    scoring_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scoring_configs.id", ondelete="RESTRICT"),
        nullable=False,
    )
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    explanation_template: Mapped[str] = mapped_column(String, nullable=False)
    explanation_narration: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    explanation_provider: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    superseded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    shipment = relationship("Shipment")
    scoring_config = relationship("ScoringConfig")
    candidates = relationship("RecommendationCandidate", back_populates="recommendation", cascade="all, delete-orphan")


class RecommendationCandidate(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "recommendation_candidates"
    __table_args__ = (
        CheckConstraint(
            "eligibility IN ('eligible', 'ineligible', 'insufficient_data')",
            name="chk_candidates_eligibility",
        ),
        CheckConstraint(
            "total_score IS NULL OR (total_score >= 0 AND total_score <= 1)",
            name="chk_candidates_total_score",
        ),
        CheckConstraint(
            "rate_quote IS NULL OR rate_quote >= 0",
            name="chk_candidates_rate_quote",
        ),
        UniqueConstraint("recommendation_id", "carrier_id", name="uq_recommendation_candidates_carrier"),
        Index("idx_candidates_recommendation_rank", "recommendation_id", "rank"),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    rank: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    eligibility: Mapped[str] = mapped_column(String, nullable=False)
    ineligibility_codes: Mapped[List[str]] = mapped_column(
        ARRAY(String),
        nullable=False,
        default=list,
        server_default=text("'{}'"),
    )
    component_scores: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    total_score: Mapped[Optional[Decimal]] = mapped_column(Numeric(6, 4), nullable=True)
    rate_quote: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    explanation: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    recommendation = relationship("Recommendation", back_populates="candidates")
    carrier = relationship("Carrier")

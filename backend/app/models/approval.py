"""Approval and booking proposal models per Contract 2.2 §3.15 & §3.16."""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Approval(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "approvals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'changes_requested', 'cancelled')",
            name="chk_approvals_status",
        ),
        CheckConstraint(
            "status NOT IN ('approved', 'rejected', 'changes_requested') OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)",
            name="chk_approvals_decision",
        ),
        UniqueConstraint("workflow_execution_id", name="approvals_workflow_execution_id_key"),
        Index("ix_approvals_workflow_execution_id", "workflow_execution_id", unique=True),
    )

    recommendation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="RESTRICT"),
        nullable=False,
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
    )
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    requested_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )
    decided_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_comment: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    selected_candidate_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendation_candidates.id", ondelete="RESTRICT"),
        nullable=True,
    )
    resumed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)

    recommendation = relationship("Recommendation")
    shipment = relationship("Shipment")
    requested_by_user = relationship("User", foreign_keys=[requested_by])
    decided_by_user = relationship("User", foreign_keys=[decided_by])
    selected_candidate = relationship("RecommendationCandidate")
    booking_proposal = relationship("BookingProposal", uselist=False, back_populates="approval")


class BookingProposal(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "booking_proposals"
    __table_args__ = (
        CheckConstraint(
            "status IN ('proposed', 'accepted', 'declined', 'cancelled')",
            name="chk_booking_proposals_status",
        ),
        UniqueConstraint("approval_id", name="booking_proposals_approval_id_key"),
        Index("ix_booking_proposals_approval_id", "approval_id", unique=True),
        Index(
            "uq_booking_proposals_active_shipment",
            "shipment_id",
            unique=True,
            postgresql_where=text("status IN ('proposed', 'accepted')"),
        ),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approvals.id", ondelete="RESTRICT"),
        nullable=False,
    )
    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    proposal_number: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    snapshot: Mapped[Dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status_reason: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    shipment = relationship("Shipment")
    approval = relationship("Approval", back_populates="booking_proposal")
    carrier = relationship("Carrier")
    creator = relationship("User", foreign_keys=[created_by])

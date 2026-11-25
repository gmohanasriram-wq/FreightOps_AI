"""Append-only, trigger-protected immutable audit event stream per Contract 2.2 §3.18."""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ("
            "'shipment.created', 'shipment.updated', 'intake.received', 'intake.parsed', "
            "'validation.completed', 'validation.failed', 'recommendation.generated', "
            "'recommendation.superseded', 'approval.requested', 'approval.granted', "
            "'approval.rejected', 'approval.changes_requested', 'approval.cancelled', "
            "'booking_proposal.created', 'booking_proposal.status_changed', "
            "'workflow.started', 'workflow.paused_for_human', 'workflow.completed', "
            "'workflow.failed', 'llm.invoked', 'config.updated')",
            name="chk_audit_events_type",
        ),
        CheckConstraint(
            "actor_type IN ('user', 'system', 'llm')",
            name="chk_audit_events_actor_type",
        ),
        Index(
            "uq_audit_events_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(always=False, start=1, increment=1),
        primary_key=True,
    )
    event_type: Mapped[str] = mapped_column(String, nullable=False, index=True)
    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    recommendation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("recommendations.id", ondelete="RESTRICT"),
        nullable=True,
    )
    approval_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("approvals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    booking_proposal_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("booking_proposals.id", ondelete="RESTRICT"),
        nullable=True,
    )
    trace_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    payload: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
        index=True,
    )

    shipment = relationship("Shipment")
    workflow_execution = relationship("WorkflowExecution")
    recommendation = relationship("Recommendation")
    approval = relationship("Approval")
    booking_proposal = relationship("BookingProposal")

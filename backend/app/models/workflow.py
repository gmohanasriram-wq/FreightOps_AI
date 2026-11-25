"""Workflow execution and LLM invocation telemetry models per Contract 2.2 §3.17 & §3.21."""
import uuid
from datetime import datetime
from typing import Any, Dict, Optional
from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, UUIDPrimaryKeyMixin


class WorkflowExecution(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "workflow_executions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'waiting_for_human', 'resumption_pending', "
            "'completed', 'failed', 'cancelled', 'timed_out')",
            name="chk_workflow_executions_status",
        ),
        CheckConstraint(
            "current_node IS NULL OR current_node IN ("
            "'start_execution', 'load_shipment', 'validate_shipment', 'decide_validation_outcome', "
            "'normalize_requirements', 'resolve_carrier_candidates', 'filter_eligible_carriers', "
            "'score_candidates', 'generate_explanation', 'persist_recommendation', "
            "'request_human_approval', 'apply_human_decision', 'create_booking_proposal', "
            "'record_audit_event', 'finalize_execution', 'handle_failure')",
            name="chk_workflow_executions_current_node",
        ),
        CheckConstraint(
            "cumulative_compute_seconds >= 0 AND cumulative_compute_seconds <= 900",
            name="chk_workflow_executions_compute_budget",
        ),
        Index("idx_workflow_executions_lease", "lease_expires_at"),
        Index("idx_workflow_executions_trace", "trace_id"),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    current_node: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    graph_version: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="1.0",
        server_default=text("'1.0'"),
    )
    state: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    max_attempt_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default=text("3"),
    )
    cumulative_compute_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    llm_call_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    node_execution_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    lease_token: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    lease_epoch: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    lease_owner: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lease_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    trace_id: Mapped[str] = mapped_column(String, nullable=False)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )
    attempt_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
        onupdate=text("now()"),
    )

    shipment = relationship("Shipment")
    llm_invocations = relationship("LLMInvocation", back_populates="workflow_execution", cascade="all, delete-orphan")


class LLMInvocation(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "llm_invocations"
    __table_args__ = (
        CheckConstraint(
            "operation IN ('extract_shipment_fields', 'narrate_explanation')",
            name="chk_llm_invocations_operation",
        ),
        CheckConstraint(
            "status IN ('success', 'error')",
            name="chk_llm_invocations_status",
        ),
    )

    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    operation: Mapped[str] = mapped_column(String, nullable=False, index=True)
    provider: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="mock",
        server_default=text("'mock'"),
    )
    model_identifier: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    prompt_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)
    error_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    workflow_execution = relationship("WorkflowExecution", back_populates="llm_invocations")

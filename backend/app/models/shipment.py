"""Shipment aggregate, stops, intake, and validation models per Contract 2.2 §3.9 - §3.12."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from sqlalchemy import (
    Boolean,
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


class Shipment(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "shipments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'intake_received', 'validation_failed', 'validated', 'sourcing', "
            "'recommendation_ready', 'pending_approval', 'approved', 'booking_proposed', 'booked', "
            "'cancelled', 'closed')",
            name="chk_shipments_status",
        ),
        CheckConstraint(
            "source IN ('intake_submission', 'manual')",
            name="chk_shipments_source",
        ),
        CheckConstraint(
            "equipment_type IS NULL OR equipment_type IN ('dry_van', 'reefer', 'flatbed')",
            name="chk_shipments_equipment_type",
        ),
        CheckConstraint(
            "weight_lbs IS NULL OR weight_lbs > 0",
            name="chk_shipments_weight_lbs",
        ),
        CheckConstraint(
            "target_sell_rate IS NULL OR target_sell_rate >= 0",
            name="chk_shipments_target_sell_rate",
        ),
        CheckConstraint(
            "max_buy_rate IS NULL OR max_buy_rate >= 0",
            name="chk_shipments_max_buy_rate",
        ),
    )

    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    origin_facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    destination_facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    source: Mapped[str] = mapped_column(String, nullable=False)
    intake_submission_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("intake_submissions.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    reference_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    po_number: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    commodity: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    equipment_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    weight_lbs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_sell_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    max_buy_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default=text("'USD'"),
    )
    lane_origin: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    lane_destination: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    requirements: Mapped[Dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    frozen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )

    customer = relationship("Customer", foreign_keys=[customer_id])
    origin_facility = relationship("Facility", foreign_keys=[origin_facility_id])
    destination_facility = relationship("Facility", foreign_keys=[destination_facility_id])
    stops = relationship("ShipmentStop", back_populates="shipment", cascade="all, delete-orphan", order_by="ShipmentStop.sequence")
    intake_submission = relationship("IntakeSubmission", foreign_keys=[intake_submission_id])


class ShipmentStop(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "shipment_stops"
    __table_args__ = (
        CheckConstraint("sequence >= 1", name="chk_shipment_stops_sequence"),
        CheckConstraint("stop_type IN ('pickup', 'delivery')", name="chk_shipment_stops_type"),
        UniqueConstraint("shipment_id", "sequence", name="uq_shipment_stops_sequence"),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    facility_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("facilities.id", ondelete="RESTRICT"),
        nullable=True,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    stop_type: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    address_line1: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    address_line2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    state: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    country: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="US",
        server_default=text("'US'"),
    )
    window_start: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    window_end: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    appointment_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    contact_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    shipment = relationship("Shipment", back_populates="stops")
    facility = relationship("Facility")


class IntakeSubmission(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "intake_submissions"
    __table_args__ = (
        CheckConstraint(
            "channel IN ('paste', 'upload', 'rest_api', 'manual')",
            name="chk_intake_submissions_channel",
        ),
    )

    channel: Mapped[str] = mapped_column(String, nullable=False)
    raw_text: Mapped[str] = mapped_column(String, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    idempotency_key: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    submitter_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    shipment_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=True,
        unique=True,
    )
    parse_metadata: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    extracted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    extraction_error: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    submitter = relationship("User", foreign_keys=[submitter_id])
    shipment = relationship("Shipment", foreign_keys=[shipment_id])


class ValidationRun(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "validation_runs"
    __table_args__ = (
        CheckConstraint(
            "result IN ('passed', 'passed_with_warnings', 'failed')",
            name="chk_validation_runs_result",
        ),
        Index("idx_validation_runs_shipment_checked", "shipment_id", text("checked_at DESC")),
    )

    shipment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shipments.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    result: Mapped[str] = mapped_column(String, nullable=False)
    issues: Mapped[List[Dict[str, Any]]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    rules_version: Mapped[str] = mapped_column(String, nullable=False)
    triggered_by_user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    workflow_execution_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflow_executions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    shipment = relationship("Shipment")
    triggered_by = relationship("User", foreign_keys=[triggered_by_user_id])

"""Carrier domain models per Contract 2.2 §3.4 - §3.8."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import List, Optional
from sqlalchemy import (
    ARRAY,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Carrier(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "carriers"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'inactive', 'suspended')",
            name="chk_carriers_status",
        ),
    )

    legal_name: Mapped[str] = mapped_column(String, nullable=False)
    dba_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    mc_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    dot_number: Mapped[Optional[str]] = mapped_column(String, nullable=True, index=True)
    status: Mapped[str] = mapped_column(String, nullable=False, index=True)
    authority_status_recorded: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    insurance_expiry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hazmat_authorized: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    temperature_capable: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    primary_contact_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    primary_contact_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    primary_contact_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    data_source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="synthetic",
        server_default=text("'synthetic'"),
    )
    last_verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)

    equipment_types = relationship("CarrierEquipmentType", back_populates="carrier", cascade="all, delete-orphan")
    service_regions = relationship("CarrierServiceRegion", back_populates="carrier", cascade="all, delete-orphan")
    availability = relationship("CarrierAvailability", back_populates="carrier", cascade="all, delete-orphan")
    lane_rates = relationship("CarrierLaneRate", back_populates="carrier", cascade="all, delete-orphan")


class CarrierEquipmentType(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "carrier_equipment_types"
    __table_args__ = (
        CheckConstraint(
            "equipment_type IN ('dry_van', 'reefer', 'flatbed')",
            name="chk_carrier_equipment_type",
        ),
        CheckConstraint(
            "max_weight_lbs IS NULL OR max_weight_lbs > 0",
            name="chk_carrier_equipment_max_weight",
        ),
        UniqueConstraint("carrier_id", "equipment_type", name="uq_carrier_equipment_type"),
    )

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    equipment_type: Mapped[str] = mapped_column(String, nullable=False)
    max_weight_lbs: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    trailer_lengths_ft: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    carrier = relationship("Carrier", back_populates="equipment_types")


class CarrierServiceRegion(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "carrier_service_regions"
    __table_args__ = (
        CheckConstraint(
            "region_type IN ('state', 'metro', 'radius_miles', 'postal_prefix')",
            name="chk_carrier_service_region_type",
        ),
        UniqueConstraint("carrier_id", "region_type", "region_value", name="uq_carrier_service_region"),
    )

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    region_type: Mapped[str] = mapped_column(String, nullable=False)
    region_value: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    carrier = relationship("Carrier", back_populates="service_regions")


class CarrierAvailability(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "carrier_availability"
    __table_args__ = (
        CheckConstraint(
            "available_until > available_from",
            name="chk_carrier_availability_dates",
        ),
    )

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    available_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    available_until: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    origin_region: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    destination_region: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    equipment_type: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    carrier = relationship("Carrier", back_populates="availability")


class CarrierLaneRate(Base, UUIDPrimaryKeyMixin):
    __tablename__ = "carrier_lane_rates"
    __table_args__ = (
        CheckConstraint(
            "equipment_type IN ('dry_van', 'reefer', 'flatbed')",
            name="chk_carrier_lane_rates_equipment",
        ),
        CheckConstraint(
            "flat_rate IS NULL OR flat_rate >= 0",
            name="chk_carrier_lane_rates_flat_rate",
        ),
        CheckConstraint(
            "rate_per_mile IS NULL OR rate_per_mile >= 0",
            name="chk_carrier_lane_rates_rate_per_mile",
        ),
        CheckConstraint(
            "min_rate IS NULL OR min_rate >= 0",
            name="chk_carrier_lane_rates_min_rate",
        ),
        CheckConstraint(
            "flat_rate IS NOT NULL OR rate_per_mile IS NOT NULL",
            name="chk_lane_rates_has_rate",
        ),
        Index(
            "uq_carrier_lane_rates_active",
            "carrier_id",
            "origin_region",
            "destination_region",
            "equipment_type",
            unique=True,
            postgresql_where=text("is_active = true"),
        ),
    )

    carrier_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("carriers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    origin_region: Mapped[str] = mapped_column(String, nullable=False)
    destination_region: Mapped[str] = mapped_column(String, nullable=False)
    equipment_type: Mapped[str] = mapped_column(String, nullable=False)
    flat_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    rate_per_mile: Mapped[Optional[Decimal]] = mapped_column(Numeric(8, 2), nullable=True)
    min_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3),
        nullable=False,
        default="USD",
        server_default=text("'USD'"),
    )
    source: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="synthetic",
        server_default=text("'synthetic'"),
    )
    effective_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    expiration_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=text("now()"),
        server_default=text("now()"),
    )

    carrier = relationship("Carrier", back_populates="lane_rates")

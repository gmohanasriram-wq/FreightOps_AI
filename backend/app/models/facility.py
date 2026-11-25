"""Physical facility locations consolidating shippers and consignees per Contract 2.2 §3.3 & ADR-019."""
import uuid
from typing import Optional
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Facility(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "facilities"
    __table_args__ = (
        CheckConstraint(
            "facility_type IN ('warehouse', 'plant', 'distribution_center', 'cross_dock', 'cold_storage', 'other')",
            name="chk_facilities_type",
        ),
    )

    customer_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("customers.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    code: Mapped[Optional[str]] = mapped_column(String, unique=True, nullable=True, index=True)
    facility_type: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="warehouse",
        server_default=text("'warehouse'"),
    )
    address_line1: Mapped[str] = mapped_column(String, nullable=False)
    address_line2: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    city: Mapped[str] = mapped_column(String, nullable=False)
    state: Mapped[str] = mapped_column(String, nullable=False)
    postal_code: Mapped[str] = mapped_column(String, nullable=False)
    country: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="US",
        server_default=text("'US'"),
    )
    timezone: Mapped[str] = mapped_column(
        String,
        nullable=False,
        default="UTC",
        server_default=text("'UTC'"),
    )
    contact_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    operating_hours: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    appointment_required: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("false"),
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

    customer = relationship("Customer", foreign_keys=[customer_id])

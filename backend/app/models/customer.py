"""Customer commercial accounts model per Contract 2.2 §3.2."""
from typing import Optional
from sqlalchemy import Boolean, String, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customers"

    name: Mapped[str] = mapped_column(String, nullable=False)
    reference_code: Mapped[str] = mapped_column(String, unique=True, nullable=False, index=True)
    contact_name: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact_email: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    contact_phone: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true"),
    )

"""Pydantic schemas for shipment resources (Contract 2.2 §5.3)."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class ShipmentRequirementsSchema(BaseModel):
    """Validated JSONB structure stored in shipments.requirements."""
    temperature_range: Optional[Dict[str, float]] = None
    hazmat: Optional[bool] = False
    liftgate: Optional[bool] = False
    appointment: Optional[bool] = False
    team_driver: Optional[bool] = False
    trailer_length_ft: Optional[int] = None
    weight_limit_lbs: Optional[int] = None
    permit: Optional[bool] = False
    notes: Optional[str] = None


class ShipmentStopBase(BaseModel):
    """Base stop representation."""
    sequence: int = Field(..., ge=1, description="Stop sequence index starting at 1")
    stop_type: Literal["pickup", "delivery"] = Field(..., description="Stop type")
    facility_id: Optional[uuid.UUID] = None
    name: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    postal_code: Optional[str] = None
    country: str = "US"
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None
    appointment_required: bool = False
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None


class ShipmentStopResponse(ShipmentStopBase):
    """Full stop representation returned from API."""
    id: uuid.UUID
    shipment_id: uuid.UUID
    created_at: datetime


class ShipmentSummary(BaseModel):
    """Compact shipment summary for paginated list."""
    id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    status: str
    equipment_type: Optional[str] = None
    commodity: Optional[str] = None
    weight_lbs: Optional[int] = None
    lane_origin: Optional[str] = None
    lane_destination: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class ShipmentResponse(BaseModel):
    """Full shipment aggregate representation."""
    id: uuid.UUID
    customer_id: Optional[uuid.UUID] = None
    origin_facility_id: Optional[uuid.UUID] = None
    destination_facility_id: Optional[uuid.UUID] = None
    status: str
    source: str
    intake_submission_id: Optional[uuid.UUID] = None
    reference_number: Optional[str] = None
    po_number: Optional[str] = None
    commodity: Optional[str] = None
    equipment_type: Optional[str] = None
    weight_lbs: Optional[int] = None
    target_sell_rate: Optional[float] = None
    max_buy_rate: Optional[float] = None
    currency: str = "USD"
    lane_origin: Optional[str] = None
    lane_destination: Optional[str] = None
    requirements: Dict[str, Any] = Field(default_factory=dict)
    notes: Optional[str] = None
    version: int
    frozen_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime
    stops: List[ShipmentStopResponse] = Field(default_factory=list)


class ShipmentPatchRequest(BaseModel):
    """Request payload for PATCH /api/v1/shipments/{shipment_id}."""
    customer_id: Optional[uuid.UUID] = None
    origin_facility_id: Optional[uuid.UUID] = None
    destination_facility_id: Optional[uuid.UUID] = None
    commodity: Optional[str] = None
    equipment_type: Optional[Literal["dry_van", "reefer", "flatbed"]] = None
    weight_lbs: Optional[int] = None
    target_sell_rate: Optional[float] = None
    max_buy_rate: Optional[float] = None
    reference_number: Optional[str] = None
    po_number: Optional[str] = None
    notes: Optional[str] = None
    requirements: Optional[Dict[str, Any]] = None
    stops: Optional[List[ShipmentStopBase]] = None


class ShipmentListResponse(BaseModel):
    """Paginated shipment list response."""
    items: List[ShipmentSummary]
    total: int
    limit: int
    offset: int

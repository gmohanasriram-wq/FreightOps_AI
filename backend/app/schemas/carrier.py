"""Pydantic schemas for carrier read APIs (Contract 2.2 §5.2/§5.3)."""
import uuid
from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class CarrierEquipmentResponse(BaseModel):
    id: uuid.UUID
    equipment_type: str
    max_weight_lbs: Optional[int] = None
    trailer_lengths_ft: List[int] = Field(default_factory=list)
    is_active: bool


class CarrierServiceRegionResponse(BaseModel):
    id: uuid.UUID
    region_type: str
    region_value: str
    is_active: bool


class CarrierAvailabilityResponse(BaseModel):
    id: uuid.UUID
    available_from: datetime
    available_until: datetime
    origin_region: Optional[str] = None
    destination_region: Optional[str] = None
    equipment_type: Optional[str] = None
    notes: Optional[str] = None


class CarrierLaneRateResponse(BaseModel):
    id: uuid.UUID
    origin_region: str
    destination_region: str
    equipment_type: str
    flat_rate: Optional[str] = None
    rate_per_mile: Optional[str] = None
    min_rate: Optional[str] = None
    currency: str
    source: str
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    is_active: bool


class CarrierSummaryFields(BaseModel):
    equipment_types: List[str] = Field(default_factory=list)
    service_states: List[str] = Field(default_factory=list)
    active_lane_rate_count: int = 0


class CarrierResponse(BaseModel):
    id: uuid.UUID
    legal_name: str
    dba_name: Optional[str] = None
    mc_number: Optional[str] = None
    dot_number: Optional[str] = None
    status: str
    authority_status_recorded: Optional[str] = None
    insurance_expiry_date: Optional[date] = None
    hazmat_authorized: bool
    temperature_capable: bool
    primary_contact_name: Optional[str] = None
    primary_contact_email: Optional[str] = None
    primary_contact_phone: Optional[str] = None
    data_source: str
    last_verified_at: Optional[datetime] = None
    notes: Optional[str] = None
    equipment_types: List[CarrierEquipmentResponse] = Field(default_factory=list)
    service_regions: List[CarrierServiceRegionResponse] = Field(default_factory=list)
    availability: List[CarrierAvailabilityResponse] = Field(default_factory=list)
    lane_rates: List[CarrierLaneRateResponse] = Field(default_factory=list)
    summary: CarrierSummaryFields


class CarrierListResponse(BaseModel):
    items: List[CarrierResponse]
    total: int
    limit: int
    offset: int

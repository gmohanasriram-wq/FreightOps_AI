"""Carrier data-access and serialization services (Contract 2.2 §3.4-§3.8)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional, Sequence

from sqlalchemy import and_, select
from sqlalchemy.orm import Session, selectinload

from backend.app.models.carrier import (
    Carrier,
    CarrierAvailability,
    CarrierEquipmentType,
    CarrierLaneRate,
    CarrierServiceRegion,
)


CARRIER_LOAD_OPTIONS = (
    selectinload(Carrier.equipment_types),
    selectinload(Carrier.service_regions),
    selectinload(Carrier.availability),
    selectinload(Carrier.lane_rates),
)


def _iso(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _date(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _money(value: Optional[Decimal]) -> Optional[str]:
    """Serialize Decimal money as a lossless string for JSON APIs."""
    return format(value, "f") if value is not None else None


def carrier_to_snapshot(carrier: Carrier) -> Dict[str, Any]:
    """Serialize a carrier aggregate into a pure-Python snapshot.

    The snapshot is the input contract for deterministic eligibility and scoring
    engines, so it deliberately contains only carrier-recorded facts. No history,
    reliability, on-time performance, or fabricated attributes are added.
    """
    equipment = sorted(carrier.equipment_types or [], key=lambda row: row.equipment_type)
    regions = sorted(
        carrier.service_regions or [],
        key=lambda row: (row.region_type, row.region_value),
    )
    availability = sorted(
        carrier.availability or [],
        key=lambda row: (row.available_from, row.available_until),
    )
    rates = sorted(
        carrier.lane_rates or [],
        key=lambda row: (
            row.origin_region,
            row.destination_region,
            row.equipment_type,
            str(row.id),
        ),
    )

    return {
        "id": str(carrier.id),
        "legal_name": carrier.legal_name,
        "dba_name": carrier.dba_name,
        "mc_number": carrier.mc_number,
        "dot_number": carrier.dot_number,
        "status": carrier.status,
        "authority_status_recorded": carrier.authority_status_recorded,
        "insurance_expiry_date": _date(carrier.insurance_expiry_date),
        "hazmat_authorized": bool(carrier.hazmat_authorized),
        "temperature_capable": bool(carrier.temperature_capable),
        "primary_contact_name": carrier.primary_contact_name,
        "primary_contact_email": carrier.primary_contact_email,
        "primary_contact_phone": carrier.primary_contact_phone,
        "data_source": carrier.data_source,
        "last_verified_at": _iso(carrier.last_verified_at),
        "notes": carrier.notes,
        "equipment_types": [
            {
                "id": str(row.id),
                "equipment_type": row.equipment_type,
                "max_weight_lbs": row.max_weight_lbs,
                "trailer_lengths_ft": list(row.trailer_lengths_ft or []),
                "is_active": bool(row.is_active),
            }
            for row in equipment
        ],
        "service_regions": [
            {
                "id": str(row.id),
                "region_type": row.region_type,
                "region_value": row.region_value,
                "is_active": bool(row.is_active),
            }
            for row in regions
        ],
        "availability": [
            {
                "id": str(row.id),
                "available_from": _iso(row.available_from),
                "available_until": _iso(row.available_until),
                "origin_region": row.origin_region,
                "destination_region": row.destination_region,
                "equipment_type": row.equipment_type,
                "notes": row.notes,
            }
            for row in availability
        ],
        "lane_rates": [
            {
                "id": str(row.id),
                "origin_region": row.origin_region,
                "destination_region": row.destination_region,
                "equipment_type": row.equipment_type,
                "flat_rate": _money(row.flat_rate),
                "rate_per_mile": _money(row.rate_per_mile),
                "min_rate": _money(row.min_rate),
                "currency": row.currency,
                "source": row.source,
                "effective_date": _date(row.effective_date),
                "expiration_date": _date(row.expiration_date),
                "is_active": bool(row.is_active),
            }
            for row in rates
        ],
        # Immutable display-time summary for list views only.
        "summary": {
            "equipment_types": sorted(
                {row.equipment_type for row in equipment if row.is_active}
            ),
            "service_states": sorted(
                {
                    row.region_value
                    for row in regions
                    if row.is_active and row.region_type == "state"
                }
            ),
            "active_lane_rate_count": sum(1 for row in rates if row.is_active),
        },
    }


def load_all_carriers(db: Session) -> List[Carrier]:
    """Load the broad carrier universe (D-027) without eligibility pre-filtering."""
    stmt = select(Carrier).options(*CARRIER_LOAD_OPTIONS).order_by(Carrier.legal_name)
    return list(db.scalars(stmt).all())


def list_carriers(
    db: Session,
    *,
    status: Optional[str] = None,
    equipment_type: Optional[str] = None,
    region_type: Optional[str] = None,
    region_value: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[List[Carrier], int]:
    """List carriers with deterministic filters and eager-loaded relationships."""
    from sqlalchemy import func

    stmt = select(Carrier).options(*CARRIER_LOAD_OPTIONS)
    if status:
        stmt = stmt.where(Carrier.status == status)
    if equipment_type:
        stmt = stmt.where(
            Carrier.equipment_types.any(
                and_(
                    CarrierEquipmentType.equipment_type == equipment_type,
                    CarrierEquipmentType.is_active.is_(True),
                )
            )
        )
    if region_type or region_value:
        conditions = [CarrierServiceRegion.is_active.is_(True)]
        if region_type:
            conditions.append(CarrierServiceRegion.region_type == region_type)
        if region_value:
            conditions.append(CarrierServiceRegion.region_value == region_value)
        stmt = stmt.where(Carrier.service_regions.any(and_(*conditions)))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    carriers = list(
        db.scalars(stmt.order_by(Carrier.legal_name).offset(offset).limit(limit)).all()
    )
    return carriers, total


def get_carrier(db: Session, carrier_id: uuid.UUID) -> Optional[Carrier]:
    stmt = (
        select(Carrier)
        .options(*CARRIER_LOAD_OPTIONS)
        .where(Carrier.id == carrier_id)
    )
    return db.scalars(stmt).first()

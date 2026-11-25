"""Carrier discovery API endpoints (Contract 2.2 §5.2)."""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.core.auth import require_role
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.db.session import get_db
from backend.app.models.user import User
from backend.app.schemas.carrier import CarrierListResponse, CarrierResponse
from backend.app.services.carriers import (
    carrier_to_snapshot,
    get_carrier,
    list_carriers,
)

router = APIRouter(prefix="/carriers", tags=["carriers"])


@router.get(
    "",
    response_model=CarrierListResponse,
    summary="List carriers with equipment, region, and status filters",
)
def list_carriers_endpoint(
    status: Optional[str] = Query(None, description="Filter by carrier status"),
    equipment_type: Optional[str] = Query(None, description="Filter by active equipment type"),
    region_type: Optional[str] = Query(None, description="Filter by service-region type"),
    region_value: Optional[str] = Query(None, description="Filter by service-region value"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    """Discover carriers and their recorded relationship data."""
    if status is not None and status not in ("active", "inactive", "suspended"):
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Invalid Carrier Status",
            detail="status must be one of: active, inactive, suspended.",
        )
    if equipment_type is not None and equipment_type not in ("dry_van", "reefer", "flatbed"):
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Invalid Equipment Type",
            detail="equipment_type must be one of: dry_van, reefer, flatbed.",
        )

    carriers, total = list_carriers(
        db,
        status=status,
        equipment_type=equipment_type,
        region_type=region_type,
        region_value=region_value,
        limit=limit,
        offset=offset,
    )

    return CarrierListResponse(
        items=[CarrierResponse(**carrier_to_snapshot(c)) for c in carriers],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{carrier_id}",
    response_model=CarrierResponse,
    summary="Retrieve a carrier with all recorded relationship data",
)
def get_carrier_endpoint(
    carrier_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    carrier = get_carrier(db, carrier_id)
    if carrier is None:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Carrier Not Found",
            detail=f"Carrier '{carrier_id}' does not exist.",
        )
    return CarrierResponse(**carrier_to_snapshot(carrier))

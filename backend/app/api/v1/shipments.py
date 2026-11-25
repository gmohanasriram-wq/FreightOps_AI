"""Shipment management and validation endpoints per Contract 2.2 §5.3."""
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.core.auth import get_current_user, require_csrf, require_role
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.db.session import get_db
from backend.app.domain.validation.engine import RULES_VERSION, ValidationEngine
from backend.app.models.shipment import Shipment, ShipmentStop, ValidationRun
from backend.app.models.user import User
from backend.app.schemas.shipment import (
    ShipmentListResponse,
    ShipmentPatchRequest,
    ShipmentResponse,
    ShipmentStopResponse,
    ShipmentSummary,
)
from backend.app.schemas.validation import (
    ValidationIssueResponse,
    ValidationRunResponse,
)
from backend.app.services.audit import emit_audit_event

router = APIRouter(prefix="/shipments", tags=["shipments"])


def derive_lane_strings(stops: List[ShipmentStop]) -> tuple[Optional[str], Optional[str]]:
    """Derive lane_origin and lane_destination strings in 'City, State' format (Approved Decision 3)."""
    if not stops:
        return None, None

    sorted_stops = sorted(stops, key=lambda s: s.sequence)
    pickups = [s for s in sorted_stops if s.stop_type == "pickup"]
    deliveries = [s for s in sorted_stops if s.stop_type == "delivery"]

    origin_str = None
    if pickups:
        first_p = pickups[0]
        if first_p.city and first_p.state:
            origin_str = f"{first_p.city}, {first_p.state}"
        elif first_p.state:
            origin_str = first_p.state

    dest_str = None
    if deliveries:
        last_d = deliveries[-1]
        if last_d.city and last_d.state:
            dest_str = f"{last_d.city}, {last_d.state}"
        elif last_d.state:
            dest_str = last_d.state

    return origin_str, dest_str


def build_shipment_response(shipment: Shipment, stops: List[ShipmentStop]) -> ShipmentResponse:
    """Serialize shipment model and stops into ShipmentResponse schema."""
    sorted_stops = sorted(stops, key=lambda s: s.sequence)
    stop_schemas = [
        ShipmentStopResponse(
            id=s.id,
            shipment_id=s.shipment_id,
            sequence=s.sequence,
            stop_type=s.stop_type, # type: ignore
            facility_id=s.facility_id,
            name=s.name,
            address_line1=s.address_line1,
            address_line2=s.address_line2,
            city=s.city,
            state=s.state,
            postal_code=s.postal_code,
            country=s.country,
            window_start=s.window_start,
            window_end=s.window_end,
            appointment_required=s.appointment_required,
            contact_name=s.contact_name,
            contact_phone=s.contact_phone,
            created_at=s.created_at,
        )
        for s in sorted_stops
    ]

    return ShipmentResponse(
        id=shipment.id,
        customer_id=shipment.customer_id,
        origin_facility_id=shipment.origin_facility_id,
        destination_facility_id=shipment.destination_facility_id,
        status=shipment.status,
        source=shipment.source,
        intake_submission_id=shipment.intake_submission_id,
        reference_number=shipment.reference_number,
        po_number=shipment.po_number,
        commodity=shipment.commodity,
        equipment_type=shipment.equipment_type,
        weight_lbs=shipment.weight_lbs,
        target_sell_rate=float(shipment.target_sell_rate) if shipment.target_sell_rate is not None else None,
        max_buy_rate=float(shipment.max_buy_rate) if shipment.max_buy_rate is not None else None,
        currency=shipment.currency,
        lane_origin=shipment.lane_origin,
        lane_destination=shipment.lane_destination,
        requirements=shipment.requirements or {},
        notes=shipment.notes,
        version=shipment.version,
        frozen_at=shipment.frozen_at,
        created_at=shipment.created_at,
        updated_at=shipment.updated_at,
        stops=stop_schemas,
    )


@router.get(
    "",
    response_model=ShipmentListResponse,
    summary="List and filter shipments with pagination",
)
def list_shipments(
    status: Optional[str] = Query(None, description="Filter by shipment status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    """List shipments with pagination and optional status filter."""
    stmt = select(Shipment)
    if status:
        stmt = stmt.where(Shipment.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    shipments = db.scalars(stmt.order_by(desc(Shipment.created_at)).offset(offset).limit(limit)).all()

    items = [
        ShipmentSummary(
            id=s.id,
            customer_id=s.customer_id,
            status=s.status,
            equipment_type=s.equipment_type,
            commodity=s.commodity,
            weight_lbs=s.weight_lbs,
            lane_origin=s.lane_origin,
            lane_destination=s.lane_destination,
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in shipments
    ]

    return ShipmentListResponse(
        items=items,
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{shipment_id}",
    response_model=ShipmentResponse,
    summary="Retrieve full shipment aggregate with stops and requirements",
)
def get_shipment(
    shipment_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    """Retrieve full shipment record."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Shipment Not Found",
            detail=f"Shipment '{shipment_id}' does not exist.",
        )

    stops = db.scalars(
        select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id).order_by(ShipmentStop.sequence)
    ).all()

    return build_shipment_response(shipment, list(stops))


@router.patch(
    "/{shipment_id}",
    response_model=ShipmentResponse,
    summary="Update mutable shipment fields before approval",
)
def patch_shipment(
    shipment_id: uuid.UUID,
    payload: ShipmentPatchRequest,
    request: Request,
    current_user: User = Depends(require_role(["broker", "admin"])),
    _csrf: User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Update shipment terms, commodity, equipment, requirements, or stops (FR-032)."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Shipment Not Found",
            detail=f"Shipment '{shipment_id}' does not exist.",
        )

    # 1. Enforce frozen protection (FR-032 / Contract 2.2 §3.9)
    if shipment.frozen_at is not None or shipment.status in ("approved", "booking_proposed", "booked"):
        raise FreightOpsHTTPException(
            status_code=409,
            code="ERR-005",
            title="Conflict: Shipment Frozen",
            detail=f"Shipment terms were frozen at {shipment.frozen_at} and cannot be modified in status '{shipment.status}'.",
        )

    # 2. Update scalar fields
    patch_data = payload.model_dump(exclude_unset=True)

    scalar_fields = [
        "customer_id",
        "origin_facility_id",
        "destination_facility_id",
        "commodity",
        "equipment_type",
        "weight_lbs",
        "target_sell_rate",
        "max_buy_rate",
        "reference_number",
        "po_number",
        "notes",
    ]
    for field in scalar_fields:
        if field in patch_data:
            setattr(shipment, field, patch_data[field])

    # 3. Update JSONB requirements
    if "requirements" in patch_data and patch_data["requirements"] is not None:
        merged_reqs = dict(shipment.requirements or {})
        merged_reqs.update(patch_data["requirements"])
        shipment.requirements = merged_reqs

    # 4. Atomic stop collection replacement (Approved Decision 4)
    if "stops" in patch_data and patch_data["stops"] is not None:
        new_stops_data = patch_data["stops"]
        # Delete existing stops
        existing_stops = db.scalars(
            select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id)
        ).all()
        for s in existing_stops:
            db.delete(s)
        db.flush()

        # Insert new stops
        new_stop_models: List[ShipmentStop] = []
        for stop_dict in new_stops_data:
            stop_obj = ShipmentStop(
                id=uuid.uuid4(),
                shipment_id=shipment.id,
                sequence=stop_dict["sequence"],
                stop_type=stop_dict["stop_type"],
                facility_id=stop_dict.get("facility_id"),
                name=stop_dict.get("name"),
                address_line1=stop_dict.get("address_line1"),
                address_line2=stop_dict.get("address_line2"),
                city=stop_dict.get("city"),
                state=stop_dict.get("state"),
                postal_code=stop_dict.get("postal_code"),
                country=stop_dict.get("country", "US"),
                window_start=stop_dict.get("window_start"),
                window_end=stop_dict.get("window_end"),
                appointment_required=stop_dict.get("appointment_required", False),
                contact_name=stop_dict.get("contact_name"),
                contact_phone=stop_dict.get("contact_phone"),
            )
            db.add(stop_obj)
            new_stop_models.append(stop_obj)
        db.flush()

        # Derive lane origin and lane destination (Approved Decision 3)
        origin_str, dest_str = derive_lane_strings(new_stop_models)
        shipment.lane_origin = origin_str
        shipment.lane_destination = dest_str

    # 5. Version increment & mutation timestamp
    shipment.version += 1
    shipment.updated_at = datetime.now(timezone.utc)
    db.flush()

    # 6. Audit event: shipment.updated
    trace_id = request.headers.get("X-Trace-ID") or f"trace-{uuid.uuid4().hex[:12]}"
    emit_audit_event(
        db=db,
        event_type="shipment.updated",
        actor_type="user",
        actor_id=current_user.id,
        shipment_id=shipment.id,
        trace_id=trace_id,
        payload={"version": shipment.version, "updated_fields": list(patch_data.keys())},
    )

    db.commit()

    current_stops = db.scalars(
        select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id).order_by(ShipmentStop.sequence)
    ).all()
    return build_shipment_response(shipment, list(current_stops))


@router.post(
    "/{shipment_id}/validation",
    response_model=ValidationRunResponse,
    summary="Execute deterministic validation rules on shipment aggregate",
)
def validate_shipment_endpoint(
    shipment_id: uuid.UUID,
    request: Request,
    current_user: User = Depends(require_role(["broker", "admin"])),
    _csrf: User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Run deterministic validation rules and atomically update shipment status (Approved Decision 2)."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Shipment Not Found",
            detail=f"Shipment '{shipment_id}' does not exist.",
        )

    stops = db.scalars(
        select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id).order_by(ShipmentStop.sequence)
    ).all()

    # Assemble dictionaries for pure Python ValidationEngine
    shipment_dict = {
        "customer_id": shipment.customer_id,
        "origin_facility_id": shipment.origin_facility_id,
        "destination_facility_id": shipment.destination_facility_id,
        "commodity": shipment.commodity,
        "equipment_type": shipment.equipment_type,
        "weight_lbs": shipment.weight_lbs,
        "target_sell_rate": float(shipment.target_sell_rate) if shipment.target_sell_rate is not None else None,
        "max_buy_rate": float(shipment.max_buy_rate) if shipment.max_buy_rate is not None else None,
        "requirements": shipment.requirements or {},
    }
    stops_dict = [
        {
            "sequence": s.sequence,
            "stop_type": s.stop_type,
            "facility_id": s.facility_id,
            "name": s.name,
            "address_line1": s.address_line1,
            "city": s.city,
            "state": s.state,
            "postal_code": s.postal_code,
            "window_start": s.window_start,
            "window_end": s.window_end,
            "appointment_required": s.appointment_required,
            "contact_phone": s.contact_phone,
        }
        for s in stops
    ]

    # Run deterministic validation engine
    result_status, issues = ValidationEngine.validate(shipment_dict, stops_dict)

    # Convert issues to JSON-serializable dicts
    issues_dicts = [i.model_dump() for i in issues]

    # Atomically persist ValidationRun and update shipment status (Approved Decision 2)
    run_id = uuid.uuid4()
    checked_at = datetime.now(timezone.utc)
    validation_run = ValidationRun(
        id=run_id,
        shipment_id=shipment_id,
        result=result_status,
        issues=issues_dicts,
        rules_version=RULES_VERSION,
        triggered_by_user_id=current_user.id,
        checked_at=checked_at,
    )
    db.add(validation_run)

    # State transition: 'failed' -> 'validation_failed', 'passed'/'passed_with_warnings' -> 'validated'
    if result_status == "failed":
        shipment.status = "validation_failed"
    else:
        shipment.status = "validated"
    shipment.updated_at = checked_at
    db.flush()

    # Emit audit event: validation.completed or validation.failed
    trace_id = request.headers.get("X-Trace-ID") or f"trace-{uuid.uuid4().hex[:12]}"
    audit_type = "validation.failed" if result_status == "failed" else "validation.completed"
    emit_audit_event(
        db=db,
        event_type=audit_type,
        actor_type="user",
        actor_id=current_user.id,
        shipment_id=shipment_id,
        trace_id=trace_id,
        payload={
            "validation_run_id": str(run_id),
            "result": result_status,
            "issue_count": len(issues),
            "rules_version": RULES_VERSION,
        },
    )

    db.commit()

    return ValidationRunResponse(
        validation_run_id=run_id,
        shipment_id=shipment_id,
        rules_version=RULES_VERSION,
        result=result_status, # type: ignore
        checked_at=checked_at,
        issues=[ValidationIssueResponse(**i) for i in issues_dicts],
    )


@router.get(
    "/{shipment_id}/validation",
    response_model=ValidationRunResponse,
    summary="Retrieve latest validation run for shipment",
)
def get_latest_validation_endpoint(
    shipment_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    """Retrieve the most recent validation run."""
    run = db.scalars(
        select(ValidationRun)
        .where(ValidationRun.shipment_id == shipment_id)
        .order_by(desc(ValidationRun.checked_at))
        .limit(1)
    ).first()

    if not run:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Validation Run Not Found",
            detail=f"No validation runs recorded for shipment '{shipment_id}'.",
        )

    return ValidationRunResponse(
        validation_run_id=run.id,
        shipment_id=run.shipment_id,
        rules_version=run.rules_version,
        result=run.result, # type: ignore
        checked_at=run.checked_at,
        issues=[ValidationIssueResponse(**i) for i in (run.issues or [])],
    )

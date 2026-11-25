"""UI routes serving Jinja2 templates and HTMX partials per Contract 2.2 ADR-003."""
import hashlib
import uuid
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Form, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.core.auth import (
    ensure_demo_users_seeded,
    get_session_csrf_token,
    get_session_record,
    require_csrf_for_ui,
)
from backend.app.core.config import settings
from backend.app.db.session import check_database_connection, get_db
from backend.app.domain.validation.engine import RULES_VERSION, ValidationEngine
from backend.app.models.approval import Approval
from backend.app.models.recommendation import Recommendation
from backend.app.models.shipment import IntakeSubmission, Shipment, ShipmentStop, ValidationRun
from backend.app.models.user import User
from backend.app.models.workflow import WorkflowExecution
from backend.app.services.approvals import ApprovalError
from backend.app.services.audit import emit_audit_event
from backend.app.services.recommendation_views import serialize_recommendation
from backend.app.workflows.runtime import InvalidWorkflowTransition
from backend.app.workflows.service import (
    ShipmentNotFoundForWorkflow,
    get_execution,
    start_workflow,
    submit_approval_decision,
)

router = APIRouter(tags=["ui"])

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_session_csrf(request: Request) -> Optional[str]:
    """Return the CSRF token bound to the request's session cookie, if any."""
    return get_session_csrf_token(request.cookies.get("session_id"))


def resolve_ui_actor(request: Request, db: Session) -> Optional[User]:
    """Resolve the browser session user, falling back to the demo broker.

    The UI is a demonstration surface; when no browser session exists a human
    still has to click the decision control, and the fallback keeps the local
    demo usable without a login page. API routes enforce real authentication.
    """
    ensure_demo_users_seeded(db)
    record = get_session_record(request.cookies.get("session_id"))
    if record is not None:
        user = db.get(User, record.user_id)
        if user is not None and user.is_active:
            return user
    return db.execute(select(User).where(User.role == "broker")).scalar_one_or_none()


def latest_recommendation(db: Session, shipment_id: uuid.UUID) -> Optional[Recommendation]:
    return db.scalars(
        select(Recommendation)
        .where(Recommendation.shipment_id == shipment_id)
        .order_by(desc(Recommendation.created_at))
        .limit(1)
    ).first()


def approval_for_recommendation(
    db: Session, recommendation: Optional[Recommendation]
) -> Optional[Approval]:
    if recommendation is None:
        return None
    return db.scalars(
        select(Approval)
        .where(Approval.recommendation_id == recommendation.id)
        .order_by(desc(Approval.requested_at))
        .limit(1)
    ).first()


def latest_execution(db: Session, shipment_id: uuid.UUID) -> Optional[WorkflowExecution]:
    return db.scalars(
        select(WorkflowExecution)
        .where(WorkflowExecution.shipment_id == shipment_id)
        .order_by(desc(WorkflowExecution.started_at))
        .limit(1)
    ).first()


def recommendation_panel_context(db: Session, shipment: Shipment) -> Dict[str, Any]:
    recommendation = latest_recommendation(db, shipment.id)
    execution = latest_execution(db, shipment.id)
    snapshot = None
    if execution is not None:
        try:
            snapshot = get_execution(execution.id)
        except Exception:  # noqa: BLE001 - panel rendering must not fail the page
            snapshot = None
    return {
        "shipment": shipment,
        "recommendation": recommendation,
        "recommendation_view": (
            serialize_recommendation(db, recommendation)
            if recommendation is not None
            else None
        ),
        "approval": approval_for_recommendation(db, recommendation),
        "execution": snapshot,
    }


def get_health_context(request: Request) -> Dict[str, Any]:
    """Assemble health and system context for Jinja2 template rendering."""
    db_connected, db_message, db_details = check_database_connection()
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "request": request,
        "active_tab": "health",
        "project_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "db_connected": db_connected,
        "db_message": db_message,
        "db_details": db_details,
        "db_status": "CONNECTED" if db_connected else "UNAVAILABLE",
        "instructions": not db_connected,
        "evaluated_at": now_str,
    }


@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    """Render the full FreightOps AI System Health & Diagnostics dashboard."""
    context = get_health_context(request)
    return templates.TemplateResponse(request=request, name="dashboard.html", context=context)


@router.get("/ui/partials/health-status", response_class=HTMLResponse)
async def health_status_partial(request: Request):
    """Render the HTMX partial for live background polling."""
    context = get_health_context(request)
    return templates.TemplateResponse(request=request, name="partials/health_status.html", context=context)


@router.get("/shipments", response_class=HTMLResponse)
def shipments_list_view(
    request: Request,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Render shipments list view."""
    stmt = select(Shipment)
    if status:
        stmt = stmt.where(Shipment.status == status)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    shipments = db.scalars(stmt.order_by(desc(Shipment.created_at)).limit(50)).all()

    return templates.TemplateResponse(
        request=request,
        name="shipments/list.html",
        context={
            "request": request,
            "active_tab": "shipments",
            "shipments": shipments,
            "total": total,
            "current_status": status,
        },
    )


@router.get("/shipments/new", response_class=HTMLResponse)
def shipment_new_view(request: Request):
    """Render the intake submission form."""
    return templates.TemplateResponse(
        request=request,
        name="shipments/new.html",
        context={
            "request": request,
            "active_tab": "shipments",
            "error": None,
            "csrf_token": get_session_csrf(request),
        },
    )


@router.post("/shipments/new", response_class=HTMLResponse)
def shipment_new_submit(
    request: Request,
    raw_text: str = Form(...),
    channel: str = Form("paste"),
    client_request_id: Optional[str] = Form(None),
    _csrf: None = Depends(require_csrf_for_ui),
    db: Session = Depends(get_db),
):
    """Form handler for intake paste submission."""
    ensure_demo_users_seeded(db)
    broker = db.execute(select(User).where(User.role == "broker")).scalar_one_or_none()
    broker_id = broker.id if broker else None

    # Check 100 KB limit
    raw_bytes = raw_text.encode("utf-8")
    if len(raw_bytes) > 100 * 1024:
        return templates.TemplateResponse(
            request=request,
            name="shipments/new.html",
            context={
                "request": request,
                "active_tab": "shipments",
                "error": "Submission payload exceeds the 100 KB limit.",
                "error_title": "Payload Too Large (ERR-009)",
            },
            status_code=413,
        )

    # Content hashing
    raw_hash = hashlib.sha256(raw_bytes).hexdigest()
    formatted_hash = f"sha256:{raw_hash}"

    # Deduplication check
    existing = db.execute(
        select(IntakeSubmission).where(IntakeSubmission.content_hash == formatted_hash)
    ).scalar_one_or_none()
    if existing and existing.shipment_id:
        return RedirectResponse(url=f"/shipments/{existing.shipment_id}", status_code=status.HTTP_303_SEE_OTHER)

    submission_id = uuid.uuid4()
    submission = IntakeSubmission(
        id=submission_id,
        channel=channel,
        raw_text=raw_text,
        content_hash=formatted_hash,
        submitter_id=broker_id,
    )
    db.add(submission)
    db.flush()

    shipment_id = uuid.uuid4()
    draft_shipment = Shipment(
        id=shipment_id,
        status="draft",
        source="intake_submission",
        intake_submission_id=submission_id,
        reference_number=client_request_id,
        currency="USD",
        version=1,
        requirements={},
        created_by=broker_id,
    )
    db.add(draft_shipment)
    db.flush()

    submission.shipment_id = shipment_id
    submission.parse_metadata = {
        "model": "fallback_manual",
        "extracted_fields": [],
        "status": "unparsed_draft",
    }
    db.flush()

    # Emit audit events
    emit_audit_event(
        db=db,
        event_type="intake.received",
        actor_type="user",
        actor_id=broker_id,
        trace_id=f"trace-{uuid.uuid4().hex[:12]}",
        payload={"submission_id": str(submission_id), "channel": channel},
    )
    emit_audit_event(
        db=db,
        event_type="shipment.created",
        actor_type="user",
        actor_id=broker_id,
        shipment_id=shipment_id,
        trace_id=f"trace-{uuid.uuid4().hex[:12]}",
        payload={"status": "draft", "source": channel},
    )

    db.commit()
    return RedirectResponse(url=f"/shipments/{shipment_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/shipments/{shipment_id}", response_class=HTMLResponse)
def shipment_detail_view(
    request: Request,
    shipment_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Render full shipment details, stops, and validation panel."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        return RedirectResponse(url="/shipments", status_code=status.HTTP_303_SEE_OTHER)

    stops = db.scalars(
        select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id).order_by(ShipmentStop.sequence)
    ).all()

    latest_validation = db.scalars(
        select(ValidationRun)
        .where(ValidationRun.shipment_id == shipment_id)
        .order_by(desc(ValidationRun.checked_at))
        .limit(1)
    ).first()

    return templates.TemplateResponse(
        request=request,
        name="shipments/detail.html",
        context={
            "request": request,
            "active_tab": "shipments",
            "shipment": shipment,
            "stops": stops,
            "latest_validation": latest_validation,
            "csrf_token": get_session_csrf(request),
            **recommendation_panel_context(db, shipment),
        },
    )


@router.post("/shipments/{shipment_id}/validation", response_class=HTMLResponse)
def run_validation_htmx(
    request: Request,
    shipment_id: uuid.UUID,
    _csrf: None = Depends(require_csrf_for_ui),
    db: Session = Depends(get_db),
):
    """HTMX endpoint to run validation engine and return partial issue card."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        return HTMLResponse("<div class='text-rose-400'>Shipment not found</div>", status_code=404)

    stops = db.scalars(
        select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id).order_by(ShipmentStop.sequence)
    ).all()

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

    result_status, issues = ValidationEngine.validate(shipment_dict, stops_dict)
    issues_dicts = [i.model_dump() for i in issues]

    run_id = uuid.uuid4()
    checked_at = datetime.now(timezone.utc)
    validation_run = ValidationRun(
        id=run_id,
        shipment_id=shipment_id,
        result=result_status,
        issues=issues_dicts,
        rules_version=RULES_VERSION,
        checked_at=checked_at,
    )
    db.add(validation_run)

    if result_status == "failed":
        shipment.status = "validation_failed"
    else:
        shipment.status = "validated"
    shipment.updated_at = checked_at
    db.flush()

    audit_type = "validation.failed" if result_status == "failed" else "validation.completed"
    emit_audit_event(
        db=db,
        event_type=audit_type,
        actor_type="system",
        shipment_id=shipment_id,
        trace_id=f"trace-{uuid.uuid4().hex[:12]}",
        payload={
            "validation_run_id": str(run_id),
            "result": result_status,
            "issue_count": len(issues),
        },
    )
    db.commit()

    return templates.TemplateResponse(
        request=request,
        name="partials/validation_results.html",
        context={
            "request": request,
            "result": result_status,
            "issues": issues_dicts,
            "rules_version": RULES_VERSION,
            "checked_at": checked_at.strftime("%Y-%m-%d %H:%M:%S UTC"),
        },
    )


@router.post("/shipments/{shipment_id}/edit", response_class=HTMLResponse)
def shipment_edit_submit(
    request: Request,
    shipment_id: uuid.UUID,
    equipment_type: Optional[str] = Form(None),
    commodity: Optional[str] = Form(None),
    weight_lbs: Optional[str] = Form(None),
    target_sell_rate: Optional[str] = Form(None),
    max_buy_rate: Optional[str] = Form(None),
    reference_number: Optional[str] = Form(None),
    notes: Optional[str] = Form(None),
    temp_min_f: Optional[str] = Form(None),
    temp_max_f: Optional[str] = Form(None),
    hazmat: Optional[str] = Form(None),
    appointment: Optional[str] = Form(None),
    _csrf: None = Depends(require_csrf_for_ui),
    db: Session = Depends(get_db),
):
    """Handle editing of draft shipment specifications."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment or shipment.frozen_at is not None:
        return RedirectResponse(url=f"/shipments/{shipment_id}", status_code=status.HTTP_303_SEE_OTHER)

    if equipment_type:
        shipment.equipment_type = equipment_type
    if commodity:
        shipment.commodity = commodity
    if weight_lbs and weight_lbs.strip():
        try:
            shipment.weight_lbs = int(weight_lbs.strip())
        except ValueError:
            pass
    if target_sell_rate and target_sell_rate.strip():
        try:
            shipment.target_sell_rate = float(target_sell_rate.strip())
        except ValueError:
            pass
    if max_buy_rate and max_buy_rate.strip():
        try:
            shipment.max_buy_rate = float(max_buy_rate.strip())
        except ValueError:
            pass
    if reference_number is not None:
        shipment.reference_number = reference_number
    if notes is not None:
        shipment.notes = notes

    # Requirements JSONB
    reqs = dict(shipment.requirements or {})
    if temp_min_f and temp_min_f.strip() and temp_max_f and temp_max_f.strip():
        try:
            reqs["temperature_range"] = {
                "min_f": float(temp_min_f.strip()),
                "max_f": float(temp_max_f.strip()),
            }
        except ValueError:
            pass
    reqs["hazmat"] = bool(hazmat)
    reqs["appointment"] = bool(appointment)
    shipment.requirements = reqs

    shipment.version += 1
    shipment.updated_at = datetime.now(timezone.utc)
    db.commit()

    return RedirectResponse(url=f"/shipments/{shipment_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/shipments/{shipment_id}/seed-sample-stops", response_class=HTMLResponse)
def seed_sample_stops(
    request: Request,
    shipment_id: uuid.UUID,
    _csrf: None = Depends(require_csrf_for_ui),
    db: Session = Depends(get_db),
):
    """Helper action to populate sample Chicago pickup and Dallas delivery stops for demonstration."""
    shipment = db.get(Shipment, shipment_id)
    if not shipment or shipment.frozen_at is not None:
        return RedirectResponse(url=f"/shipments/{shipment_id}", status_code=status.HTTP_303_SEE_OTHER)

    # Delete existing stops
    existing_stops = db.scalars(
        select(ShipmentStop).where(ShipmentStop.shipment_id == shipment_id)
    ).all()
    for s in existing_stops:
        db.delete(s)
    db.flush()

    now = datetime.now(timezone.utc)
    pickup_start = now + timedelta(days=1)
    pickup_end = pickup_start + timedelta(hours=4)
    delivery_start = now + timedelta(days=3)
    delivery_end = delivery_start + timedelta(hours=8)

    p_stop = ShipmentStop(
        id=uuid.uuid4(),
        shipment_id=shipment.id,
        sequence=1,
        stop_type="pickup",
        name="Chicago Cold Logistics Hub",
        address_line1="100 Logistics Blvd",
        city="Chicago",
        state="IL",
        postal_code="60601",
        country="US",
        window_start=pickup_start,
        window_end=pickup_end,
        appointment_required=True,
        contact_name="Bob Dispatch",
        contact_phone="312-555-0100",
    )
    d_stop = ShipmentStop(
        id=uuid.uuid4(),
        shipment_id=shipment.id,
        sequence=2,
        stop_type="delivery",
        name="Dallas Distribution Center",
        address_line1="500 Freight Way",
        city="Dallas",
        state="TX",
        postal_code="75201",
        country="US",
        window_start=delivery_start,
        window_end=delivery_end,
        appointment_required=False,
        contact_name="Alice Receiving",
        contact_phone="214-555-0200",
    )
    db.add(p_stop)
    db.add(d_stop)
    db.flush()

    shipment.lane_origin = "Chicago, IL"
    shipment.lane_destination = "Dallas, TX"
    shipment.version += 1
    shipment.updated_at = now
    db.commit()

    return RedirectResponse(url=f"/shipments/{shipment_id}", status_code=status.HTTP_303_SEE_OTHER)


# ---------------------------------------------------------------------------
# Recommendation workflow and human approval UI (PH-4 / PH-5)
# ---------------------------------------------------------------------------
def _panel_error(message: str, code: str = "WORKFLOW_ERROR") -> Dict[str, str]:
    return {"code": code, "message": message, "node": None, "retryable": False}


@router.post("/shipments/{shipment_id}/recommendations", response_class=HTMLResponse)
def start_recommendation_htmx(
    request: Request,
    shipment_id: uuid.UUID,
    _csrf: None = Depends(require_csrf_for_ui),
    db: Session = Depends(get_db),
):
    """Run the real bounded workflow and return the live panel."""
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        return HTMLResponse(
            "<div class='p-4 rounded-xl border border-rose-800 bg-rose-950/40 text-rose-300 text-sm'>"
            "Shipment not found.</div>",
            status_code=404,
        )

    error: Optional[Dict[str, Any]] = None
    if shipment.frozen_at is not None or shipment.status not in ("validated", "sourcing"):
        error = _panel_error(
            f"Shipment status '{shipment.status}' cannot start a recommendation workflow. "
            "A validated or sourcing shipment is required.",
            code="INVALID_SHIPMENT_STATUS",
        )
    else:
        try:
            start_workflow(
                shipment.id,
                trace_id=f"ui-{uuid.uuid4().hex[:12]}",
                idempotency_key=f"ui-recommendation:{uuid.uuid4()}",
            )
        except (ShipmentNotFoundForWorkflow, InvalidWorkflowTransition) as exc:
            error = _panel_error(str(exc))
        except Exception as exc:  # noqa: BLE001 - render the failure in the panel
            error = _panel_error(str(exc)[:1000], code="WORKFLOW_EXECUTION_ERROR")

    db.expire_all()
    shipment = db.get(Shipment, shipment_id)
    context = recommendation_panel_context(db, shipment) if shipment else {}
    context.update(
        {
            "request": request,
            "csrf_token": get_session_csrf(request),
            "error": error,
        }
    )
    return templates.TemplateResponse(
        request=request, name="partials/recommendation_panel.html", context=context
    )


@router.get("/recommendations/{recommendation_id}", response_class=HTMLResponse)
def recommendation_detail_view(
    request: Request,
    recommendation_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """Render the ranked scorecard, exclusion reasons, and approval controls."""
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        return RedirectResponse(url="/shipments", status_code=status.HTTP_303_SEE_OTHER)

    view = serialize_recommendation(db, recommendation)
    approval = approval_for_recommendation(db, recommendation)
    workflow = None
    if recommendation.workflow_execution_id:
        try:
            workflow = get_execution(recommendation.workflow_execution_id)
        except Exception:  # noqa: BLE001 - read-only page resilience
            workflow = None

    return templates.TemplateResponse(
        request=request,
        name="recommendations/detail.html",
        context={
            "request": request,
            "active_tab": "approvals",
            "recommendation": recommendation,
            "view": view,
            "approval": approval,
            "workflow": workflow,
            "csrf_token": get_session_csrf(request),
            "decision_result": None,
            "error": None,
        },
    )


@router.post("/ui/approvals/{approval_id}/decision", response_class=HTMLResponse)
def decide_approval_htmx(
    request: Request,
    approval_id: uuid.UUID,
    decision: str = Form(...),
    comment: Optional[str] = Form(None),
    _csrf: None = Depends(require_csrf_for_ui),
    db: Session = Depends(get_db),
):
    """Persist the human decision and resume the paused graph, then re-render."""
    approval = db.get(Approval, approval_id)
    if approval is None:
        return HTMLResponse(
            "<div class='p-4 rounded-xl border border-rose-800 bg-rose-950/40 text-rose-300 text-sm'>"
            "Approval not found.</div>",
            status_code=404,
        )

    actor = resolve_ui_actor(request, db)
    error: Optional[Dict[str, Any]] = None
    try:
        submit_approval_decision(
            approval_id,
            action=decision,
            actor_id=actor.id if actor else None,
            comment=comment or None,
        )
    except ApprovalError as exc:
        error = _panel_error(str(exc), code=getattr(exc, "code", "APPROVAL_ERROR"))
    except Exception as exc:  # noqa: BLE001 - render the failure in the panel
        error = _panel_error(str(exc)[:1000], code="APPROVAL_RESUME_FAILED")

    db.expire_all()
    approval = db.get(Approval, approval_id)
    recommendation = db.get(Recommendation, approval.recommendation_id)
    workflow = None
    if approval.workflow_execution_id:
        try:
            workflow = get_execution(approval.workflow_execution_id)
        except Exception:  # noqa: BLE001 - read-only panel resilience
            workflow = None

    return templates.TemplateResponse(
        request=request,
        name="partials/approval_panel.html",
        context={
            "request": request,
            "approval": approval,
            "recommendation": recommendation,
            "workflow": workflow,
            "error": error,
            "decision_result": None if error else approval.status,
            "csrf_token": get_session_csrf(request),
        },
    )


@router.get("/approvals", response_class=HTMLResponse)
def approvals_list_view(
    request: Request,
    status_filter: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """Render the broker approval queue."""
    stmt = select(Approval)
    if status_filter:
        stmt = stmt.where(Approval.status == status_filter)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    approvals = db.scalars(
        stmt.order_by(desc(Approval.requested_at)).limit(100)
    ).all()
    return templates.TemplateResponse(
        request=request,
        name="approvals/list.html",
        context={
            "request": request,
            "active_tab": "approvals",
            "approvals": approvals,
            "total": total,
            "current_status": status_filter,
        },
    )


@router.get("/approvals/{approval_id}")
def approval_redirect(approval_id: uuid.UUID, db: Session = Depends(get_db)):
    """Single approval surface lives on the recommendation page."""
    approval = db.get(Approval, approval_id)
    if approval is None:
        return RedirectResponse(url="/approvals", status_code=status.HTTP_303_SEE_OTHER)
    return RedirectResponse(
        url=f"/recommendations/{approval.recommendation_id}#approval",
        status_code=status.HTTP_303_SEE_OTHER,
    )

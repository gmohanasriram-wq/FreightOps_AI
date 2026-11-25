"""Recommendation generation and read endpoints (docs/09 §5.5)."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.core.auth import require_csrf, require_role
from backend.app.core.config import settings
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.db.session import get_db
from backend.app.models.recommendation import Recommendation
from backend.app.models.shipment import Shipment
from backend.app.models.user import User
from backend.app.schemas.recommendation import (
    RecommendationListResponse,
    RecommendationResponse,
)
from backend.app.schemas.workflow import (
    RecommendationTriggerRequest,
    WorkflowTriggerResponse,
)
from backend.app.services.idempotency import (
    check_and_acquire_idempotency_key,
    release_idempotency_on_error,
    store_idempotency_result,
)
from backend.app.services.recommendation_views import (
    serialize_recommendation,
    serialize_recommendation_summary,
)
from backend.app.workflows.service import start_workflow

router = APIRouter(tags=["recommendations"])

STARTABLE_SHIPMENT_STATUSES = ("validated", "sourcing")
BUDGET_ERROR_CODES = (
    "MAX_NODE_EXECUTIONS_EXCEEDED",
    "MAX_LLM_CALLS_EXCEEDED",
    "MAX_COMPUTE_BUDGET_EXCEEDED",
    "MAX_CONTINUOUS_ATTEMPT_EXCEEDED",
    "WORKFLOW_TIMED_OUT",
)


def _not_found(message: str) -> FreightOpsHTTPException:
    return FreightOpsHTTPException(
        status_code=404, code="ERR-004", title="Not Found", detail=message
    )


@router.post(
    "/shipments/{shipment_id}/recommendations",
    response_model=WorkflowTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger the deterministic carrier recommendation workflow",
)
def trigger_recommendation(
    shipment_id: uuid.UUID,
    payload: RecommendationTriggerRequest,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_role(["broker", "admin"])),
    _csrf: User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Start (or idempotently reuse) a bounded workflow for a validated shipment.

    The workflow runs synchronously in this MVP and may already be paused for
    human approval when the request returns. The returned status is the durable
    execution status, never a fabricated ``queued`` value.
    """
    if not idempotency_key or not idempotency_key.strip():
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Missing Idempotency-Key",
            detail="The 'Idempotency-Key' request header is required to trigger a recommendation workflow.",
        )
    if payload.scoring_config_id is not None:
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Unsupported Scoring Configuration",
            detail="The MVP runs the active scoring configuration; a custom scoring_config_id is not supported.",
        )
    if (
        payload.top_n is not None
        and payload.top_n != settings.TOP_N_RECOMMENDATIONS
    ):
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Unsupported Top-N",
            detail=(
                "The configured top-N presentation limit is "
                f"{settings.TOP_N_RECOMMENDATIONS}; a different value is not supported in the MVP."
            ),
        )

    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise _not_found(f"Shipment '{shipment_id}' does not exist.")

    endpoint = f"/api/v1/shipments/{shipment_id}/recommendations"
    cached, _, cached_body = check_and_acquire_idempotency_key(
        db=db,
        key=idempotency_key,
        endpoint=endpoint,
        request_payload_str=payload.model_dump_json(),
    )
    if cached and cached_body:
        return WorkflowTriggerResponse(**cached_body)

    if shipment.frozen_at is not None or shipment.status not in STARTABLE_SHIPMENT_STATUSES:
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=409,
            code="ERR-005",
            title="Invalid Shipment Status",
            detail=(
                f"Shipment '{shipment_id}' is '{shipment.status}'; a recommendation workflow "
                "requires a validated or sourcing shipment."
            ),
        )

    try:
        snapshot = start_workflow(
            shipment_id,
            trace_id=request.headers.get("X-Trace-ID"),
            idempotency_key=idempotency_key,
        )
    except Exception as exc:  # noqa: BLE001 - release the in-flight key then map
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=500,
            code="ERR-015",
            title="Workflow Start Failed",
            detail=str(exc)[:1000],
        ) from exc

    error = snapshot.get("error") or {}
    if snapshot["status"] in ("failed", "timed_out") and error.get(
        "code"
    ) in BUDGET_ERROR_CODES:
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-012",
            title="Workflow Budget Exceeded",
            detail=error.get("message") or "The recommendation workflow budget was exceeded.",
        )

    body = WorkflowTriggerResponse(
        workflow_execution_id=uuid.UUID(snapshot["execution_id"]),
        shipment_id=shipment_id,
        status=snapshot["status"],
    )
    store_idempotency_result(db, idempotency_key, 202, body.model_dump(mode="json"))
    db.commit()
    return body


@router.get(
    "/shipments/{shipment_id}/recommendations",
    response_model=RecommendationListResponse,
    summary="List recommendations generated for a shipment",
)
def list_shipment_recommendations(
    shipment_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        raise _not_found(f"Shipment '{shipment_id}' does not exist.")

    rows = db.scalars(
        select(Recommendation)
        .where(Recommendation.shipment_id == shipment_id)
        .order_by(desc(Recommendation.created_at))
    ).all()
    return RecommendationListResponse(
        items=[serialize_recommendation_summary(row) for row in rows],
        total=len(rows),
    )


@router.get(
    "/recommendations/{recommendation_id}",
    response_model=RecommendationResponse,
    summary="Retrieve ranked candidates, component scores, exclusions, and explanation",
)
def get_recommendation(
    recommendation_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    recommendation = db.get(Recommendation, recommendation_id)
    if recommendation is None:
        raise _not_found(f"Recommendation '{recommendation_id}' does not exist.")
    return serialize_recommendation(db, recommendation)

"""Human approval queue and decision endpoints (docs/09 §5.6)."""
from __future__ import annotations

import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from backend.app.core.auth import require_csrf, require_role
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.db.session import get_db
from backend.app.models.approval import Approval
from backend.app.models.recommendation import Recommendation
from backend.app.models.shipment import Shipment
from backend.app.models.user import User
from backend.app.schemas.approval import (
    ApprovalDecisionRequest,
    ApprovalDecisionResponse,
    ApprovalDetailResponse,
    ApprovalListResponse,
    ApprovalSummary,
)
from backend.app.services.approvals import (
    ApprovalNotFound,
    InvalidApprovalSelection,
    InvalidApprovalTransition,
)
from backend.app.services.idempotency import (
    check_and_acquire_idempotency_key,
    release_idempotency_on_error,
    store_idempotency_result,
)
from backend.app.services.recommendation_views import serialize_recommendation
from backend.app.workflows.service import submit_approval_decision

router = APIRouter(prefix="/approvals", tags=["approvals"])

APPROVAL_STATUSES = (
    "pending",
    "approved",
    "rejected",
    "changes_requested",
    "cancelled",
)


def _summary(approval: Approval) -> ApprovalSummary:
    return ApprovalSummary(
        approval_id=approval.id,
        shipment_id=approval.shipment_id,
        recommendation_id=approval.recommendation_id,
        workflow_execution_id=approval.workflow_execution_id,
        status=approval.status,
        requested_by=approval.requested_by,
        requested_at=approval.requested_at,
        decided_by=approval.decided_by,
        decided_at=approval.decided_at,
        decision_comment=approval.decision_comment,
        selected_candidate_id=approval.selected_candidate_id,
        resumed_at=approval.resumed_at,
    )


def _get_approval_or_404(db: Session, approval_id: uuid.UUID) -> Approval:
    approval = db.get(Approval, approval_id)
    if approval is None:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Approval Not Found",
            detail=f"Approval '{approval_id}' does not exist.",
        )
    return approval


@router.get(
    "",
    response_model=ApprovalListResponse,
    summary="List the human approval queue",
)
def list_approvals(
    status_filter: Optional[str] = Query(None, alias="status"),
    shipment_id: Optional[uuid.UUID] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    if status_filter is not None and status_filter not in APPROVAL_STATUSES:
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Invalid Approval Status",
            detail=f"Unknown approval status '{status_filter}'.",
        )

    stmt = select(Approval)
    if status_filter:
        stmt = stmt.where(Approval.status == status_filter)
    if shipment_id:
        stmt = stmt.where(Approval.shipment_id == shipment_id)

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(
        stmt.order_by(desc(Approval.requested_at)).offset(offset).limit(limit)
    ).all()
    return ApprovalListResponse(
        items=[_summary(row) for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get(
    "/{approval_id}",
    response_model=ApprovalDetailResponse,
    summary="Retrieve an approval with its candidate comparison",
)
def get_approval(
    approval_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    approval = _get_approval_or_404(db, approval_id)
    recommendation = db.get(Recommendation, approval.recommendation_id)
    candidates = (
        serialize_recommendation(db, recommendation).candidates
        if recommendation is not None
        else []
    )
    return ApprovalDetailResponse(
        **_summary(approval).model_dump(),
        recommendation_status=recommendation.status if recommendation else None,
        candidates=candidates,
    )


@router.post(
    "/{approval_id}/decision",
    response_model=ApprovalDecisionResponse,
    summary="Submit the authoritative human decision and resume the workflow",
)
def decide_approval(
    approval_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_role(["broker", "admin"])),
    _csrf: User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    if not idempotency_key or not idempotency_key.strip():
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Missing Idempotency-Key",
            detail="The 'Idempotency-Key' request header is required to decide an approval.",
        )

    endpoint = f"/api/v1/approvals/{approval_id}/decision"
    cached, _, cached_body = check_and_acquire_idempotency_key(
        db=db,
        key=idempotency_key,
        endpoint=endpoint,
        request_payload_str=payload.model_dump_json(),
    )
    if cached and cached_body:
        return ApprovalDecisionResponse(**cached_body)

    approval = _get_approval_or_404(db, approval_id)
    if approval.status != "pending":
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=409,
            code="ERR-013",
            title="Invalid Approval",
            detail=f"Approval '{approval_id}' is already '{approval.status}'.",
        )

    try:
        result = submit_approval_decision(
            approval_id,
            action=payload.decision,
            actor_id=current_user.id,
            comment=payload.comment,
        )
    except ApprovalNotFound as exc:
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=404, code="ERR-004", title="Approval Not Found", detail=str(exc)
        ) from exc
    except InvalidApprovalTransition as exc:
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=409, code="ERR-013", title="Invalid Approval", detail=str(exc)
        ) from exc
    except InvalidApprovalSelection as exc:
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=422, code="ERR-001", title="Invalid Candidate Selection", detail=str(exc)
        ) from exc
    except Exception as exc:  # noqa: BLE001 - release the key before reporting
        release_idempotency_on_error(db, idempotency_key)
        db.commit()
        raise FreightOpsHTTPException(
            status_code=500, code="ERR-015", title="Decision Resume Failed", detail=str(exc)[:1000]
        ) from exc

    decision = result["decision"]
    workflow = result["workflow"]
    body = ApprovalDecisionResponse(
        approval_id=uuid.UUID(decision["approval_id"]),
        status=decision["status"],
        decided_by=uuid.UUID(decision["decided_by"]) if decision["decided_by"] else None,
        decided_at=decision["decided_at"],
        workflow_execution_id=uuid.UUID(decision["execution_id"]),
        workflow_status=workflow["status"],
        workflow_outcome=workflow.get("outcome"),
        booking_proposal_id=(
            uuid.UUID(workflow["booking_proposal_id"])
            if workflow.get("booking_proposal_id")
            else None
        ),
        selected_candidate_id=(
            uuid.UUID(decision["selected_candidate_id"])
            if decision.get("selected_candidate_id")
            else None
        ),
    )
    store_idempotency_result(db, idempotency_key, 200, body.model_dump(mode="json"))
    db.commit()
    return body

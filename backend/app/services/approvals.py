"""Approval decision service (docs/07 §8, docs/09 §6.7).

The decision transaction is the sole owner of the immediate shipment status
transition after human review. Graph node 12 only validates and routes.
"""
from __future__ import annotations

import uuid
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.eligibility.engine import ELIGIBLE
from backend.app.models.approval import Approval
from backend.app.models.recommendation import RecommendationCandidate
from backend.app.models.shipment import Shipment
from backend.app.models.workflow import WorkflowExecution
from backend.app.services.audit import emit_audit_event
from backend.app.workflows.runtime import utcnow

ACTION_TO_STATUS = {
    "approve": "approved",
    "reject": "rejected",
    "request_changes": "changes_requested",
}

STATUS_TO_AUDIT_EVENT = {
    "approved": "approval.granted",
    "rejected": "approval.rejected",
    "changes_requested": "approval.changes_requested",
}


class ApprovalError(RuntimeError):
    code = "APPROVAL_ERROR"


class ApprovalNotFound(ApprovalError):
    code = "APPROVAL_NOT_FOUND"


class InvalidApprovalTransition(ApprovalError):
    code = "APPROVAL_NOT_PENDING"


class InvalidApprovalSelection(ApprovalError):
    code = "APPROVAL_CANDIDATE_INVALID"


def _select_candidate(
    db: Session,
    approval: Approval,
    selected_candidate_id: Optional[uuid.UUID],
) -> RecommendationCandidate:
    if selected_candidate_id is not None:
        candidate = db.get(RecommendationCandidate, selected_candidate_id)
    else:
        candidate = db.scalars(
            select(RecommendationCandidate)
            .where(
                RecommendationCandidate.recommendation_id == approval.recommendation_id,
                RecommendationCandidate.rank.is_not(None),
            )
            .order_by(RecommendationCandidate.rank)
            .limit(1)
        ).first()

    if candidate is None:
        raise InvalidApprovalSelection(
            "no rankable recommendation candidate is available to approve"
        )
    if candidate.recommendation_id != approval.recommendation_id:
        raise InvalidApprovalSelection(
            "the selected candidate does not belong to this approval's recommendation"
        )
    if candidate.eligibility != ELIGIBLE or candidate.rank is None:
        raise InvalidApprovalSelection(
            "only a rankable eligible candidate can be approved"
        )
    return candidate


def record_approval_decision(
    db: Session,
    *,
    approval_id: uuid.UUID,
    action: str,
    actor_id: Optional[uuid.UUID],
    comment: Optional[str] = None,
    selected_candidate_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Persist a human decision atomically (caller commits).

    Allowed actions: ``approve``, ``reject``, ``request_changes``.
    """
    if action not in ACTION_TO_STATUS:
        raise InvalidApprovalTransition(f"unknown approval action '{action}'")
    status = ACTION_TO_STATUS[action]

    approval = db.get(Approval, approval_id, with_for_update=True)
    if approval is None:
        raise ApprovalNotFound(f"approval '{approval_id}' does not exist")
    if approval.status != "pending":
        raise InvalidApprovalTransition(
            f"approval '{approval_id}' is already '{approval.status}'"
        )
    if approval.workflow_execution_id is None:
        raise InvalidApprovalTransition("approval is not linked to a workflow execution")

    execution = db.get(
        WorkflowExecution, approval.workflow_execution_id, with_for_update=True
    )
    if execution is None:
        raise InvalidApprovalTransition("workflow execution for this approval does not exist")
    if execution.status != "waiting_for_human":
        raise InvalidApprovalTransition(
            f"workflow execution is '{execution.status}', not waiting_for_human"
        )

    shipment = db.get(Shipment, approval.shipment_id, with_for_update=True)
    if shipment is None:
        raise InvalidApprovalTransition("shipment for this approval does not exist")

    now = utcnow()
    approval.decided_by = actor_id
    approval.decided_at = now
    approval.decision_comment = comment
    approval.status = status

    if status == "approved":
        candidate = _select_candidate(db, approval, selected_candidate_id)
        approval.selected_candidate_id = candidate.id
        shipment.status = "approved"
        shipment.frozen_at = shipment.frozen_at or now
    else:
        approval.selected_candidate_id = None
        shipment.status = "sourcing"
    shipment.updated_at = now

    execution.status = "resumption_pending"
    execution.updated_at = now

    emit_audit_event(
        db,
        event_type=STATUS_TO_AUDIT_EVENT[status],
        actor_type="user",
        actor_id=actor_id,
        shipment_id=approval.shipment_id,
        workflow_execution_id=execution.id,
        approval_id=approval.id,
        trace_id=execution.trace_id,
        idempotency_key=f"approval-decision:{approval.id}",
        payload={
            "approval_id": str(approval.id),
            "recommendation_id": str(approval.recommendation_id),
            "decision": status,
            "comment": comment,
            "selected_candidate_id": (
                str(approval.selected_candidate_id)
                if approval.selected_candidate_id
                else None
            ),
        },
    )
    db.flush()
    return {
        "approval_id": str(approval.id),
        "execution_id": str(execution.id),
        "status": status,
        "action": action,
        "selected_candidate_id": (
            str(approval.selected_candidate_id)
            if approval.selected_candidate_id
            else None
        ),
        "decided_by": str(actor_id) if actor_id else None,
        "decided_at": now.isoformat(),
    }

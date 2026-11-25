"""Workflow execution inspection endpoints (docs/09 §5.9)."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends

from backend.app.core.auth import require_role
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.models.user import User
from backend.app.schemas.workflow import (
    WorkflowErrorResponse,
    WorkflowExecutionResponse,
)
from backend.app.workflows.runtime import WorkflowExecutionNotFound
from backend.app.workflows.service import get_execution

router = APIRouter(prefix="/workflows", tags=["workflows"])


@router.get(
    "/{workflow_execution_id}",
    response_model=WorkflowExecutionResponse,
    summary="Inspect workflow state, current node, and execution budgets",
)
def get_workflow(
    workflow_execution_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
):
    try:
        snapshot = get_execution(workflow_execution_id)
    except WorkflowExecutionNotFound as exc:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Workflow Execution Not Found",
            detail=f"Workflow execution '{workflow_execution_id}' does not exist.",
        ) from exc

    error = snapshot.get("error")
    return WorkflowExecutionResponse(
        workflow_execution_id=uuid.UUID(snapshot["execution_id"]),
        shipment_id=uuid.UUID(snapshot["shipment_id"]),
        status=snapshot["status"],
        current_node=snapshot.get("current_node"),
        outcome=snapshot.get("outcome"),
        interrupted=snapshot.get("interrupted", False),
        trace_id=snapshot["trace_id"],
        graph_version=snapshot["graph_version"],
        attempt_count=snapshot["attempt_count"],
        max_attempt_count=snapshot["max_attempt_count"],
        node_execution_count=snapshot["node_execution_count"],
        llm_call_count=snapshot["llm_call_count"],
        cumulative_compute_seconds=snapshot["cumulative_compute_seconds"],
        recommendation_id=(
            uuid.UUID(snapshot["recommendation_id"])
            if snapshot.get("recommendation_id")
            else None
        ),
        recommendation_status=snapshot.get("recommendation_status"),
        approval_id=(
            uuid.UUID(snapshot["approval_id"])
            if snapshot.get("approval_id")
            else None
        ),
        approval_status=snapshot.get("approval_status"),
        booking_proposal_id=(
            uuid.UUID(snapshot["booking_proposal_id"])
            if snapshot.get("booking_proposal_id")
            else None
        ),
        error=WorkflowErrorResponse(**error) if error else None,
        started_at=snapshot.get("started_at"),
        completed_at=snapshot.get("completed_at"),
        state=snapshot.get("state") or {},
    )

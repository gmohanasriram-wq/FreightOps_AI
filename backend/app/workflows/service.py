"""Workflow service: create, invoke, resume, and inspect bounded executions."""
from __future__ import annotations

import uuid
from datetime import timezone
from typing import Any, Dict, Optional

from langgraph.types import Command
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.shipment import Shipment
from backend.app.models.workflow import WorkflowExecution
from backend.app.services.approvals import record_approval_decision
from backend.app.workflows.graph import get_workflow_graph
from backend.app.workflows.runtime import (
    acquire_execution_lease,
    jsonable,
    load_execution,
    mark_execution_failed,
    utcnow,
    InvalidWorkflowTransition,
)
from backend.app.workflows.state import GRAPH_VERSION, WorkflowState, is_terminal

RECURSION_LIMIT = 64


class ShipmentNotFoundForWorkflow(RuntimeError):
    code = "SHIPMENT_NOT_FOUND"


def _iso_utc(value) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _snapshot(execution: WorkflowExecution) -> Dict[str, Any]:
    state = dict(execution.state or {})
    return {
        "execution_id": str(execution.id),
        "shipment_id": str(execution.shipment_id),
        "trace_id": execution.trace_id,
        "graph_version": execution.graph_version,
        "status": execution.status,
        "current_node": execution.current_node,
        "outcome": state.get("outcome"),
        "interrupted": execution.status == "waiting_for_human",
        "node_execution_count": execution.node_execution_count,
        "llm_call_count": execution.llm_call_count,
        "attempt_count": execution.attempt_count,
        "max_attempt_count": execution.max_attempt_count,
        "cumulative_compute_seconds": execution.cumulative_compute_seconds,
        "recommendation_id": state.get("recommendation_id"),
        "recommendation_status": state.get("recommendation_status"),
        "approval_id": state.get("approval_id"),
        "approval_status": state.get("approval_status"),
        "booking_proposal_id": state.get("booking_proposal_id"),
        "error": state.get("error")
        or (
            {"code": execution.error_code, "message": execution.error_message}
            if execution.error_code
            else None
        ),
        "started_at": _iso_utc(execution.started_at),
        "completed_at": _iso_utc(execution.completed_at),
        "state": state,
    }


def _mark_failed_directly(
    execution_id: uuid.UUID,
    code: str,
    message: str,
) -> None:
    """Terminal safety net if the graph itself raises outside node handling."""
    with SessionLocal() as db:
        execution = db.get(WorkflowExecution, execution_id)
        if execution is None or is_terminal(execution.status):
            return
        mark_execution_failed(
            db,
            execution,
            code=code,
            message=message,
            state_projection=dict(execution.state or {}),
        )
        db.commit()


def _invoke(
    execution_id: uuid.UUID,
    resume_value: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    with SessionLocal() as db:
        execution = load_execution(db, execution_id)
        if is_terminal(execution.status):
            return _snapshot(execution)
        if resume_value is None:
            if execution.status != "queued":
                raise InvalidWorkflowTransition(
                    f"execution '{execution_id}' cannot start from status '{execution.status}'"
                )
        elif execution.status != "resumption_pending":
            raise InvalidWorkflowTransition(
                f"execution '{execution_id}' cannot resume from status '{execution.status}'"
            )

        token = acquire_execution_lease(db, execution)
        db.commit()
        initial_state = dict(execution.state or {})

    config = {
        "configurable": {
            "thread_id": str(execution_id),
            "lease_token": str(token),
        },
        "recursion_limit": RECURSION_LIMIT,
    }
    graph = get_workflow_graph()
    try:
        if resume_value is None:
            graph.invoke(initial_state, config)
        else:
            graph.invoke(Command(resume=resume_value), config)
    except Exception as exc:  # noqa: BLE001 - terminal safety net
        _mark_failed_directly(execution_id, "WORKFLOW_EXECUTION_ERROR", str(exc))

    return get_execution(execution_id)


def start_workflow(
    shipment_id: uuid.UUID,
    *,
    trace_id: Optional[str] = None,
    idempotency_key: Optional[str] = None,
) -> Dict[str, Any]:
    """Create (or idempotently return) an execution and run it to completion or pause."""
    shipment_uuid = uuid.UUID(str(shipment_id))
    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_uuid)
        if shipment is None:
            raise ShipmentNotFoundForWorkflow(
                f"shipment '{shipment_uuid}' does not exist"
            )

        if idempotency_key:
            existing = db.scalars(
                select(WorkflowExecution).where(
                    WorkflowExecution.idempotency_key == idempotency_key
                )
            ).first()
            if existing is not None:
                if existing.shipment_id != shipment_uuid:
                    raise InvalidWorkflowTransition(
                        "idempotency key is already bound to a different shipment"
                    )
                return _snapshot(existing)

        execution_id = uuid.uuid4()
        now = utcnow()
        resolved_trace = trace_id or f"trace-{uuid.uuid4().hex[:12]}"
        initial_state = WorkflowState(
            execution_id=str(execution_id),
            shipment_id=str(shipment_uuid),
            trace_id=resolved_trace,
            graph_version=GRAPH_VERSION,
            status="queued",
            started_at=now.isoformat(),
            attempt_started_at=now.isoformat(),
        ).model_dump()
        execution = WorkflowExecution(
            id=execution_id,
            shipment_id=shipment_uuid,
            status="queued",
            graph_version=GRAPH_VERSION,
            state=jsonable(initial_state),
            attempt_count=0,
            max_attempt_count=3,
            cumulative_compute_seconds=0,
            llm_call_count=0,
            node_execution_count=0,
            trace_id=resolved_trace,
            idempotency_key=idempotency_key,
            started_at=now,
            attempt_started_at=now,
        )
        db.add(execution)
        db.commit()

    return _invoke(execution_id)


def resume_workflow(
    execution_id: uuid.UUID,
    decision: Dict[str, Any],
) -> Dict[str, Any]:
    """Resume a paused execution with a persisted human decision."""
    return _invoke(uuid.UUID(str(execution_id)), resume_value=decision)


def submit_approval_decision(
    approval_id: uuid.UUID,
    *,
    action: str,
    actor_id: Optional[uuid.UUID],
    comment: Optional[str] = None,
    selected_candidate_id: Optional[uuid.UUID] = None,
) -> Dict[str, Any]:
    """Persist the human decision, then resume the interrupted graph."""
    with SessionLocal() as db:
        decision = record_approval_decision(
            db,
            approval_id=uuid.UUID(str(approval_id)),
            action=action,
            actor_id=actor_id,
            comment=comment,
            selected_candidate_id=selected_candidate_id,
        )
        db.commit()

    workflow = resume_workflow(
        uuid.UUID(decision["execution_id"]), {"action": action}
    )
    return {"decision": decision, "workflow": workflow}


def get_execution(execution_id: uuid.UUID) -> Dict[str, Any]:
    with SessionLocal() as db:
        execution = load_execution(db, uuid.UUID(str(execution_id)))
        return _snapshot(execution)

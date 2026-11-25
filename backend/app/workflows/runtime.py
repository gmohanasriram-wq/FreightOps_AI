"""Shared workflow runtime helpers: leases, idempotent audit, terminal failure."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.audit import AuditEvent
from backend.app.models.workflow import WorkflowExecution
from backend.app.services.audit import emit_audit_event
from backend.app.workflows.state import TIMEOUT_ERROR_CODES, is_terminal

LEASE_SECONDS = 60
WORKFLOW_OWNER = "freightops-api"


class WorkflowExecutionNotFound(RuntimeError):
    """The workflow execution row does not exist."""


class WorkflowLeaseError(RuntimeError):
    """The caller does not hold a valid, unexpired execution lease."""

    code = "EXECUTION_LEASE_INVALID"
    retryable = True


class InvalidWorkflowTransition(RuntimeError):
    """The execution is not in a state that permits the requested operation."""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def jsonable(value: Any) -> Any:
    """Convert UUID/Decimal/datetime values into JSON-safe primitives."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def acquire_execution_lease(db: Session, execution: WorkflowExecution) -> uuid.UUID:
    """Claim the execution for this process.

    ``queued`` starts consume the first attempt; resumptions from
    ``resumption_pending`` do not consume an attempt.
    """
    if execution.status == "queued":
        execution.attempt_count = max(1, (execution.attempt_count or 0) + 1)
    elif execution.status == "resumption_pending":
        execution.attempt_count = max(1, execution.attempt_count or 0)
    else:
        raise InvalidWorkflowTransition(
            f"execution '{execution.id}' cannot be claimed from status '{execution.status}'"
        )

    token = uuid.uuid4()
    now = utcnow()
    execution.status = "running"
    execution.lease_token = token
    execution.lease_epoch = (execution.lease_epoch or 0) + 1
    execution.lease_owner = WORKFLOW_OWNER
    execution.lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    execution.attempt_started_at = now
    execution.updated_at = now
    db.flush()
    return token


def release_execution_lease(execution: WorkflowExecution) -> None:
    execution.lease_token = None
    execution.lease_owner = None
    execution.lease_expires_at = None
    execution.updated_at = utcnow()


def verify_execution_lease(
    execution: WorkflowExecution,
    lease_token: Optional[str],
) -> None:
    """Verify the caller still owns an unexpired lease.

    When no token is supplied (direct service calls/tests), only the existence
    of an unexpired lease is enforced.
    """
    if execution.status != "running":
        raise WorkflowLeaseError(
            f"execution '{execution.id}' is not running (status '{execution.status}')"
        )
    if execution.lease_expires_at is None or execution.lease_expires_at < utcnow():
        raise WorkflowLeaseError(f"execution '{execution.id}' lease has expired")
    if lease_token is not None:
        if execution.lease_token is None or str(execution.lease_token) != str(lease_token):
            raise WorkflowLeaseError(f"execution '{execution.id}' lease token does not match")


def emit_idempotent_audit(
    db: Session,
    *,
    idempotency_key: str,
    **kwargs: Any,
) -> Optional[AuditEvent]:
    """Insert an audit event unless one already exists for this key."""
    existing = db.scalars(
        select(AuditEvent).where(AuditEvent.idempotency_key == idempotency_key)
    ).first()
    if existing is not None:
        return existing
    return emit_audit_event(
        db=db,
        idempotency_key=idempotency_key,
        **kwargs,
    )


def terminal_failure_status(code: str) -> str:
    return "timed_out" if code in TIMEOUT_ERROR_CODES else "failed"


def mark_execution_failed(
    db: Session,
    execution: WorkflowExecution,
    *,
    code: str,
    message: str,
    state_projection: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Move an execution to its independent terminal failure sink (Node 16).

    Never routes through finalization and can never later be reported completed.
    """
    status = terminal_failure_status(code)
    now = utcnow()
    execution.status = status
    execution.error_code = code
    execution.error_message = message[:2000]
    execution.current_node = "handle_failure"
    execution.completed_at = now
    release_execution_lease(execution)

    projected_error = (state_projection or {}).get("error") or {}
    origin_node = projected_error.get("node") or (state_projection or {}).get(
        "current_node"
    )
    error = {
        "code": code,
        "message": message,
        "node": origin_node or "handle_failure",
        "retryable": False,
    }
    projection = dict(execution.state or {})
    if state_projection:
        projection.update(jsonable(state_projection))
    projection["status"] = status
    projection["outcome"] = status
    projection["current_node"] = "handle_failure"
    projection["error"] = error
    execution.state = jsonable(projection)

    emit_idempotent_audit(
        db,
        idempotency_key=f"node16:{execution.id}:workflow.failed",
        event_type="workflow.failed",
        actor_type="system",
        actor_id=None,
        shipment_id=execution.shipment_id,
        workflow_execution_id=execution.id,
        trace_id=execution.trace_id,
        payload={
            "error_code": code,
            "error_message": execution.error_message,
            "outcome": status,
            "attempt_count": execution.attempt_count,
            "cumulative_compute_seconds": execution.cumulative_compute_seconds,
        },
    )
    db.flush()
    return {
        "status": status,
        "outcome": status,
        "current_node": "handle_failure",
        "error": error,
    }


def load_execution(db: Session, execution_id: uuid.UUID) -> WorkflowExecution:
    execution = db.get(WorkflowExecution, execution_id)
    if execution is None:
        raise WorkflowExecutionNotFound(f"workflow execution '{execution_id}' does not exist")
    return execution

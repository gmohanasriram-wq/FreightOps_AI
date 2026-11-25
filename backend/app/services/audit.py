"""Audit Service: append-only immutable state logging (Contract 2.2 §3.18 & §7.1)."""
import uuid
from typing import Any, Dict, Optional
from sqlalchemy.orm import Session
from backend.app.models.audit import AuditEvent


def emit_audit_event(
    db: Session,
    event_type: str,
    actor_type: str,
    actor_id: Optional[uuid.UUID] = None,
    shipment_id: Optional[uuid.UUID] = None,
    workflow_execution_id: Optional[uuid.UUID] = None,
    approval_id: Optional[uuid.UUID] = None,
    booking_proposal_id: Optional[uuid.UUID] = None,
    trace_id: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> AuditEvent:
    """Insert an immutable audit event into audit_events within the caller's transaction."""
    event = AuditEvent(
        event_type=event_type,
        actor_type=actor_type,
        actor_id=actor_id,
        shipment_id=shipment_id,
        workflow_execution_id=workflow_execution_id,
        approval_id=approval_id,
        booking_proposal_id=booking_proposal_id,
        trace_id=trace_id or f"trace-{uuid.uuid4().hex[:12]}",
        payload=payload or {},
        idempotency_key=idempotency_key,
    )
    db.add(event)
    db.flush()
    return event

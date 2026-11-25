"""End-to-end tests for the bounded LangGraph orchestration (docs/07 §7)."""
from __future__ import annotations

import copy
import uuid

import pytest
from pydantic import ValidationError
from sqlalchemy import select

from backend.app.core.config import settings
from backend.app.db.session import SessionLocal
from backend.app.models.approval import Approval, BookingProposal
from backend.app.models.audit import AuditEvent
from backend.app.models.recommendation import Recommendation, RecommendationCandidate
from backend.app.models.shipment import Shipment, ShipmentStop
from backend.app.models.user import User
from backend.app.models.workflow import LLMInvocation, WorkflowExecution
from backend.app.services.demo_seed import (
    CARRIER_SPECS,
    DEMO_SHIPMENT_IDS,
    seed_all_demo_data,
)
from backend.app.services.approvals import InvalidApprovalTransition
from backend.app.workflows.service import (
    get_execution,
    start_workflow,
    submit_approval_decision,
)
from backend.app.workflows.state import WorkflowState


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with SessionLocal() as db:
        seed_all_demo_data(db)
    yield


def _clone_shipment(key: str = "ready", **overrides) -> uuid.UUID:
    """Create an isolated copy of a demo shipment for a single test."""
    with SessionLocal() as db:
        source = db.get(Shipment, DEMO_SHIPMENT_IDS[key])
        assert source is not None
        shipment = Shipment(
            id=uuid.uuid4(),
            customer_id=source.customer_id,
            origin_facility_id=source.origin_facility_id,
            destination_facility_id=source.destination_facility_id,
            status="validated",
            source="manual",
            reference_number=f"TEST-{uuid.uuid4().hex[:10].upper()}",
            commodity=source.commodity,
            equipment_type=source.equipment_type,
            weight_lbs=source.weight_lbs,
            target_sell_rate=source.target_sell_rate,
            max_buy_rate=source.max_buy_rate,
            currency=source.currency,
            lane_origin=source.lane_origin,
            lane_destination=source.lane_destination,
            requirements=copy.deepcopy(source.requirements),
            notes="Workflow test fixture.",
            version=1,
            created_by=source.created_by,
        )
        for field, value in overrides.items():
            setattr(shipment, field, value)
        db.add(shipment)
        db.flush()
        for stop in db.scalars(
            select(ShipmentStop)
            .where(ShipmentStop.shipment_id == source.id)
            .order_by(ShipmentStop.sequence)
        ).all():
            db.add(
                ShipmentStop(
                    shipment_id=shipment.id,
                    facility_id=stop.facility_id,
                    sequence=stop.sequence,
                    stop_type=stop.stop_type,
                    name=stop.name,
                    address_line1=stop.address_line1,
                    address_line2=stop.address_line2,
                    city=stop.city,
                    state=stop.state,
                    postal_code=stop.postal_code,
                    country=stop.country,
                    window_start=stop.window_start,
                    window_end=stop.window_end,
                    appointment_required=stop.appointment_required,
                    contact_name=stop.contact_name,
                    contact_phone=stop.contact_phone,
                )
            )
        db.commit()
        return shipment.id


def _actor(role: str = "broker") -> uuid.UUID:
    with SessionLocal() as db:
        user = db.scalars(
            select(User).where(User.email == f"{role}@freightops.com")
        ).one()
        return user.id


def _audit_types(execution_id: uuid.UUID) -> list[tuple[str, dict]]:
    with SessionLocal() as db:
        rows = db.scalars(
            select(AuditEvent)
            .where(AuditEvent.workflow_execution_id == execution_id)
            .order_by(AuditEvent.id)
        ).all()
        return [(row.event_type, dict(row.payload or {})) for row in rows]


def _shipment_status(shipment_id: uuid.UUID) -> str:
    with SessionLocal() as db:
        return db.get(Shipment, shipment_id).status


def _run(shipment_id: uuid.UUID) -> dict:
    return start_workflow(shipment_id, trace_id=f"test-{uuid.uuid4().hex[:8]}")


def test_ready_workflow_pauses_with_ready_recommendation():
    shipment_id = _clone_shipment("ready")
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "waiting_for_human"
    assert snapshot["interrupted"] is True
    assert snapshot["outcome"] is None
    assert snapshot["recommendation_status"] == "ready"
    assert snapshot["approval_status"] == "pending"
    assert snapshot["node_execution_count"] == 11
    assert snapshot["llm_call_count"] == 1
    assert snapshot["started_at"].endswith("+00:00")

    execution_id = uuid.UUID(snapshot["execution_id"])
    with SessionLocal() as db:
        recommendation = db.scalars(
            select(Recommendation).where(
                Recommendation.workflow_execution_id == execution_id
            )
        ).one()
        assert recommendation.status == "ready"
        assert recommendation.explanation_template

        candidates = db.scalars(
            select(RecommendationCandidate).where(
                RecommendationCandidate.recommendation_id == recommendation.id
            )
        ).all()
        assert len(candidates) == len(CARRIER_SPECS)
        ranked = sorted(
            (row for row in candidates if row.rank is not None),
            key=lambda row: row.rank,
        )
        assert [row.rank for row in ranked] == list(range(1, len(ranked) + 1))
        assert len(ranked) <= settings.TOP_N_RECOMMENDATIONS
        assert all(row.total_score is not None for row in ranked)
        assert all(row.rate_quote is not None for row in ranked)
        assert any(row.rank is None for row in candidates)

        approval = db.scalars(
            select(Approval).where(Approval.workflow_execution_id == execution_id)
        ).one()
        assert approval.status == "pending"
        assert approval.recommendation_id == recommendation.id

        invocations = db.scalars(
            select(LLMInvocation).where(
                LLMInvocation.workflow_execution_id == execution_id
            )
        ).all()
        assert len(invocations) == 1
        # The default provider is offline, so demo mode never makes a network call.
        assert invocations[0].status == "error"
        assert invocations[0].provider == "offline"
        assert invocations[0].error_code in ("LLM_OFFLINE", "LLM_DEMO_MODE")

    assert _shipment_status(shipment_id) == "pending_approval"
    events = [event for event, _ in _audit_types(execution_id)]
    assert events == [
        "workflow.started",
        "validation.completed",
        "recommendation.generated",
        "workflow.paused_for_human",
    ]


def test_approve_creates_booking_proposal_and_completes():
    shipment_id = _clone_shipment("ready")
    paused = _run(shipment_id)
    approval_id = uuid.UUID(paused["approval_id"])

    result = submit_approval_decision(
        approval_id,
        action="approve",
        actor_id=_actor("broker"),
        comment="Rate accepted.",
    )
    workflow = result["workflow"]
    assert workflow["status"] == "completed"
    assert workflow["outcome"] == "approved"
    assert workflow["booking_proposal_id"]
    assert workflow["approval_status"] == "approved"
    assert workflow["node_execution_count"] == 16

    execution_id = uuid.UUID(workflow["execution_id"])
    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        assert approval is not None
        assert approval.status == "approved"
        assert approval.resumed_at is not None
        assert approval.selected_candidate_id is not None
        assert approval.decided_by == _actor("broker")

        proposal = db.scalars(
            select(BookingProposal).where(BookingProposal.approval_id == approval_id)
        ).one()
        assert proposal.status == "proposed"
        assert proposal.proposal_number.startswith("BP-")
        assert proposal.snapshot["approval_id"] == str(approval_id)
        selected = db.get(
            RecommendationCandidate, approval.selected_candidate_id
        )
        assert selected is not None
        assert proposal.snapshot["carrier"]["carrier_id"] == str(selected.carrier_id)
        assert proposal.carrier_id == selected.carrier_id
        assert proposal.snapshot["rate_quote"] is not None

        shipment = db.get(Shipment, shipment_id)
        assert shipment.status == "booking_proposed"
        assert shipment.frozen_at is not None

    events = _audit_types(execution_id)
    event_types = [event for event, _ in events]
    assert event_types == [
        "workflow.started",
        "validation.completed",
        "recommendation.generated",
        "workflow.paused_for_human",
        "approval.granted",
        "booking_proposal.created",
        "workflow.completed",
    ]
    completed_payload = events[-1][1]
    assert completed_payload["outcome"] == "approved"
    assert completed_payload["error_code"] is None
    # Node 14 records the count before Node 15 finalizes the execution.
    assert completed_payload["node_execution_count"] == 15

    keys = []
    with SessionLocal() as db:
        for row in db.scalars(
            select(AuditEvent).where(AuditEvent.workflow_execution_id == execution_id)
        ).all():
            if row.idempotency_key:
                keys.append(row.idempotency_key)
    assert len(keys) == len(set(keys))


def test_reject_terminates_without_booking_proposal():
    shipment_id = _clone_shipment("ready")
    paused = _run(shipment_id)
    approval_id = uuid.UUID(paused["approval_id"])

    result = submit_approval_decision(
        approval_id, action="reject", actor_id=_actor("broker"), comment="Too costly."
    )
    workflow = result["workflow"]
    assert workflow["status"] == "completed"
    assert workflow["outcome"] == "rejected"
    assert workflow["booking_proposal_id"] is None

    with SessionLocal() as db:
        approval = db.get(Approval, approval_id)
        assert approval.status == "rejected"
        assert approval.selected_candidate_id is None
        assert approval.resumed_at is not None
        proposals = db.scalars(
            select(BookingProposal).where(BookingProposal.shipment_id == shipment_id)
        ).all()
        assert proposals == []

    assert _shipment_status(shipment_id) == "sourcing"
    event_types = [event for event, _ in _audit_types(uuid.UUID(workflow["execution_id"]))]
    assert "approval.rejected" in event_types
    assert event_types[-1] == "workflow.completed"
    assert _audit_types(uuid.UUID(workflow["execution_id"]))[-1][1]["outcome"] == "rejected"


def test_request_changes_returns_shipment_to_sourcing():
    shipment_id = _clone_shipment("ready")
    paused = _run(shipment_id)
    approval_id = uuid.UUID(paused["approval_id"])

    result = submit_approval_decision(
        approval_id,
        action="request_changes",
        actor_id=_actor("broker"),
        comment="Ask for a later pickup window.",
    )
    workflow = result["workflow"]
    assert workflow["status"] == "completed"
    assert workflow["outcome"] == "changes_requested"
    assert workflow["booking_proposal_id"] is None

    assert _shipment_status(shipment_id) == "sourcing"
    event_types = [event for event, _ in _audit_types(uuid.UUID(workflow["execution_id"]))]
    assert "approval.changes_requested" in event_types
    assert event_types[-1] == "workflow.completed"


def test_no_eligible_carriers_completes_without_approval():
    shipment_id = _clone_shipment("no_eligible")
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "completed"
    assert snapshot["outcome"] == "no_eligible_carriers"
    assert snapshot["recommendation_status"] == "no_eligible_carriers"
    assert snapshot["approval_id"] is None

    execution_id = uuid.UUID(snapshot["execution_id"])
    with SessionLocal() as db:
        recommendation = db.scalars(
            select(Recommendation).where(
                Recommendation.workflow_execution_id == execution_id
            )
        ).one()
        candidates = db.scalars(
            select(RecommendationCandidate).where(
                RecommendationCandidate.recommendation_id == recommendation.id
            )
        ).all()
        assert len(candidates) == len(CARRIER_SPECS)
        assert all(row.eligibility != "eligible" for row in candidates)
        assert all(row.ineligibility_codes for row in candidates)
        assert all(row.rank is None for row in candidates)
        approvals = db.scalars(
            select(Approval).where(Approval.workflow_execution_id == execution_id)
        ).all()
        assert approvals == []

    events = _audit_types(execution_id)
    assert [event for event, _ in events][-1] == "workflow.completed"
    assert events[-1][1]["outcome"] == "no_eligible_carriers"
    assert _shipment_status(shipment_id) == "sourcing"


def test_no_rankable_candidates_completes_without_approval():
    shipment_id = _clone_shipment("unrankable")
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "completed"
    assert snapshot["outcome"] == "no_rankable_candidates"
    assert snapshot["recommendation_status"] == "no_rankable_candidates"
    assert snapshot["approval_id"] is None

    execution_id = uuid.UUID(snapshot["execution_id"])
    with SessionLocal() as db:
        recommendation = db.scalars(
            select(Recommendation).where(
                Recommendation.workflow_execution_id == execution_id
            )
        ).one()
        candidates = db.scalars(
            select(RecommendationCandidate).where(
                RecommendationCandidate.recommendation_id == recommendation.id
            )
        ).all()
        assert len(candidates) == len(CARRIER_SPECS)
        assert any(row.eligibility == "eligible" for row in candidates)
        assert all(row.rank is None for row in candidates)
        assert all(row.total_score is None for row in candidates)

    events = _audit_types(execution_id)
    assert events[-1][1]["outcome"] == "no_rankable_candidates"


def test_validation_failure_routes_to_failure_sink():
    shipment_id = _clone_shipment("ready", commodity=None, weight_lbs=None)
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "failed"
    assert snapshot["outcome"] == "failed"
    assert snapshot["error"]["code"] == "VALIDATION_FAILED"
    assert snapshot["error"]["node"] == "decide_validation_outcome"
    assert snapshot["recommendation_id"] is None
    assert _shipment_status(shipment_id) == "validation_failed"

    events = _audit_types(uuid.UUID(snapshot["execution_id"]))
    assert [event for event, _ in events] == [
        "workflow.started",
        "validation.failed",
        "workflow.failed",
    ]
    assert events[-1][1]["error_code"] == "VALIDATION_FAILED"


def test_invalid_shipment_status_fails_at_load():
    shipment_id = _clone_shipment("ready", status="booked")
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "failed"
    assert snapshot["error"]["code"] == "INVALID_SHIPMENT_STATUS"
    assert snapshot["error"]["node"] == "load_shipment"
    assert snapshot["node_execution_count"] == 3  # start, load, failure sink
    assert _shipment_status(shipment_id) == "booked"


def test_start_is_idempotent_by_key():
    shipment_id = _clone_shipment("ready")
    key = f"test-idem-{uuid.uuid4().hex}"
    first = start_workflow(shipment_id, idempotency_key=key)
    second = start_workflow(shipment_id, idempotency_key=key)

    assert second["execution_id"] == first["execution_id"]
    assert second["status"] == "waiting_for_human"

    with SessionLocal() as db:
        executions = db.scalars(
            select(WorkflowExecution).where(WorkflowExecution.idempotency_key == key)
        ).all()
        assert len(executions) == 1
    started = [
        event
        for event, _ in _audit_types(uuid.UUID(first["execution_id"]))
        if event == "workflow.started"
    ]
    assert len(started) == 1


def test_node_budget_exhaustion_fails_terminally(monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_MAX_NODE_EXECUTIONS", 3)
    shipment_id = _clone_shipment("ready")
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "failed"
    assert snapshot["outcome"] == "failed"
    assert snapshot["error"]["code"] == "MAX_NODE_EXECUTIONS_EXCEEDED"
    assert snapshot["error"]["node"] == "decide_validation_outcome"
    assert snapshot["node_execution_count"] == 5  # 4 guarded + failure sink


def test_compute_budget_exhaustion_times_out(monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_MAX_COMPUTE_SECONDS", 0)
    shipment_id = _clone_shipment("ready")
    snapshot = _run(shipment_id)

    assert snapshot["status"] == "timed_out"
    assert snapshot["outcome"] == "timed_out"
    assert snapshot["error"]["code"] == "MAX_COMPUTE_BUDGET_EXCEEDED"


def test_second_decision_on_terminal_approval_is_rejected():
    shipment_id = _clone_shipment("ready")
    paused = _run(shipment_id)
    approval_id = uuid.UUID(paused["approval_id"])
    submit_approval_decision(approval_id, action="approve", actor_id=_actor("broker"))

    with pytest.raises(InvalidApprovalTransition):
        submit_approval_decision(
            approval_id, action="reject", actor_id=_actor("broker")
        )


def test_recommendations_are_deterministic_for_identical_facts():
    first_id = _clone_shipment("ready")
    second_id = _clone_shipment("ready")
    first = _run(first_id)
    second = _run(second_id)

    def ranked(execution_id: str):
        with SessionLocal() as db:
            recommendation = db.scalars(
                select(Recommendation).where(
                    Recommendation.workflow_execution_id == uuid.UUID(execution_id)
                )
            ).one()
            rows = db.scalars(
                select(RecommendationCandidate)
                .where(
                    RecommendationCandidate.recommendation_id == recommendation.id,
                    RecommendationCandidate.rank.is_not(None),
                )
                .order_by(RecommendationCandidate.rank)
            ).all()
            return [
                (str(row.carrier_id), row.total_score, row.rate_quote)
                for row in rows
            ]

    assert ranked(first["execution_id"]) == ranked(second["execution_id"])
    assert first["state"]["explanation"]["template"] == second["state"]["explanation"][
        "template"
    ]


def test_execution_snapshot_is_addressable_by_id():
    shipment_id = _clone_shipment("ready")
    snapshot = _run(shipment_id)
    fetched = get_execution(uuid.UUID(snapshot["execution_id"]))
    assert fetched["status"] == "waiting_for_human"
    assert fetched["shipment_id"] == str(shipment_id)


def test_workflow_state_rejects_unknown_fields_and_statuses():
    valid = {
        "execution_id": str(uuid.uuid4()),
        "shipment_id": str(uuid.uuid4()),
        "trace_id": "trace-test",
    }
    with pytest.raises(ValidationError):
        WorkflowState(**valid, unexpected_field=True)
    with pytest.raises(ValidationError):
        WorkflowState(**valid, status="not_a_real_status")
    with pytest.raises(ValidationError):
        WorkflowState(**valid, current_node="not_a_real_node")
    assert WorkflowState(**valid).graph_version == "2.0"

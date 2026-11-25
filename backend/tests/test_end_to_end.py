"""End-to-end regression tests spanning intake data, workflow, audit, and proposal."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from starlette.testclient import TestClient

from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.approval import Approval, BookingProposal
from backend.app.models.audit import AuditEvent
from backend.app.models.carrier import Carrier
from backend.app.models.recommendation import Recommendation, RecommendationCandidate
from backend.app.models.shipment import Shipment
from backend.app.services.demo_seed import seed_all_demo_data
from backend.tests.helpers import csrf_headers
from backend.tests.test_workflow import _clone_shipment

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with SessionLocal() as db:
        seed_all_demo_data(db)
    yield


def _trigger(shipment_id) -> dict:
    response = client.post(
        f"/api/v1/shipments/{shipment_id}/recommendations",
        json={},
        headers={
            **csrf_headers(client, "broker"),
            "Idempotency-Key": f"e2e-{uuid.uuid4()}",
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def _approval_for(shipment_id) -> Approval:
    with SessionLocal() as db:
        approval = db.scalars(
            select(Approval).where(Approval.shipment_id == shipment_id)
        ).first()
    assert approval is not None
    return approval


def _audit_types(execution_id: uuid.UUID) -> list[str]:
    with SessionLocal() as db:
        return [
            row.event_type
            for row in db.scalars(
                select(AuditEvent)
                .where(AuditEvent.workflow_execution_id == execution_id)
                .order_by(AuditEvent.id)
            ).all()
        ]


def test_full_lifecycle_audit_chain_and_proposal():
    """Recommendation → paused approval → human approve → proposal → completion."""
    shipment_id = _clone_shipment("ready")
    triggered = _trigger(shipment_id)
    workflow_id = uuid.UUID(triggered["workflow_execution_id"])
    approval = _approval_for(shipment_id)

    paused_audit = _audit_types(workflow_id)
    assert "workflow.started" in paused_audit
    assert "validation.completed" in paused_audit
    assert "workflow.paused_for_human" in paused_audit
    assert "workflow.completed" not in paused_audit

    decision = client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approve", "comment": "End-to-end regression check."},
        headers={
            **csrf_headers(client, "broker"),
            "Idempotency-Key": f"e2e-{uuid.uuid4()}",
        },
    )
    assert decision.status_code == 200, decision.text
    body = decision.json()
    assert body["workflow_status"] == "completed"
    assert body["workflow_outcome"] == "approved"

    completed_audit = _audit_types(workflow_id)
    assert completed_audit[: len(paused_audit)] == paused_audit
    for event_type in ("approval.granted", "booking_proposal.created", "workflow.completed"):
        assert event_type in completed_audit
    assert completed_audit.index("approval.granted") < completed_audit.index(
        "booking_proposal.created"
    )
    assert completed_audit.index("booking_proposal.created") < completed_audit.index(
        "workflow.completed"
    )

    with SessionLocal() as db:
        shipment = db.get(Shipment, shipment_id)
        proposal = db.scalars(
            select(BookingProposal).where(BookingProposal.shipment_id == shipment_id)
        ).one()
        refreshed_approval = db.get(Approval, approval.id)
        assert shipment.status == "booking_proposed"
        assert shipment.frozen_at is not None
        assert proposal.status == "proposed"
        assert proposal.approval_id == approval.id
        assert proposal.carrier_id == refreshed_approval.selected_candidate.carrier_id
        assert proposal.snapshot["shipment_id"] == str(shipment_id)
        assert proposal.proposal_number

    snapshot = client.get(f"/api/v1/workflows/{workflow_id}").json()
    assert snapshot["status"] == "completed"
    assert snapshot["outcome"] == "approved"
    assert snapshot["booking_proposal_id"] == str(body["booking_proposal_id"])
    assert snapshot["approval_status"] == "approved"


def test_every_carrier_is_persisted_and_deferred_components_stay_null():
    """D-021 regression: the candidate universe is complete, not pre-filtered."""
    shipment_id = _clone_shipment("ready")
    _trigger(shipment_id)

    with SessionLocal() as db:
        recommendation = db.scalars(
            select(Recommendation).where(Recommendation.shipment_id == shipment_id)
        ).one()
        candidates = db.scalars(
            select(RecommendationCandidate).where(
                RecommendationCandidate.recommendation_id == recommendation.id
            )
        ).all()
        carrier_count = len(db.scalars(select(Carrier)).all())

    assert len(candidates) == carrier_count
    assert len({row.carrier_id for row in candidates}) == carrier_count

    detail = client.get(f"/api/v1/recommendations/{recommendation.id}").json()
    all_views = detail["candidates"] + detail["ineligible_candidates"]
    assert len(all_views) == carrier_count
    for view in all_views:
        if view["eligibility_status"] != "eligible":
            assert view["rank"] is None
            assert view["composite_score"] is None
        assert view["component_scores"]["lane_familiarity"] is None
        assert view["component_scores"]["reliability"] is None
    for ranked in detail["candidates"]:
        if ranked["rank"] is not None:
            assert ranked["composite_score"] is not None


def test_identical_facts_rank_identically_across_workflows():
    """Two isolated shipments with identical facts must rank identically."""
    first_id = _clone_shipment("ready")
    second_id = _clone_shipment("ready")
    _trigger(first_id)
    _trigger(second_id)

    def _ranking(shipment_id):
        with SessionLocal() as db:
            recommendation = db.scalars(
                select(Recommendation).where(Recommendation.shipment_id == shipment_id)
            ).one()
            rows = db.scalars(
                select(RecommendationCandidate)
                .where(RecommendationCandidate.recommendation_id == recommendation.id)
                .where(RecommendationCandidate.rank.is_not(None))
                .order_by(RecommendationCandidate.rank)
            ).all()
            return [
                (
                    row.rank,
                    str(row.carrier_id),
                    str(row.total_score),
                    str(row.rate_quote),
                )
                for row in rows
            ]

    assert _ranking(first_id) == _ranking(second_id)


def test_audit_events_are_append_only_at_the_database_level():
    with SessionLocal() as db:
        event = db.scalars(select(AuditEvent).limit(1)).one()
        event_id = event.id
        original_type = event.event_type
        with pytest.raises(DBAPIError):
            db.execute(
                text("UPDATE audit_events SET event_type = 'workflow.failed' WHERE id = :id"),
                {"id": event_id},
            )
        db.rollback()
        assert db.get(AuditEvent, event_id).event_type == original_type

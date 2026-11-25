"""API and UI integration tests for recommendation, workflow, and approval surfaces."""
from __future__ import annotations

import uuid

import pytest
from starlette.testclient import TestClient
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.approval import Approval
from backend.app.models.recommendation import Recommendation
from backend.app.models.shipment import Shipment
from backend.app.services.demo_seed import seed_all_demo_data
from backend.tests.helpers import csrf_headers, login
from backend.tests.test_workflow import _clone_shipment

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def demo_data():
    with SessionLocal() as db:
        seed_all_demo_data(db)
    yield


def _key() -> str:
    return f"m6-{uuid.uuid4()}"


def _trigger(shipment_id, key: str | None = None, role: str = "broker", payload=None):
    headers = {**csrf_headers(client, role), "Idempotency-Key": key or _key()}
    return client.post(
        f"/api/v1/shipments/{shipment_id}/recommendations",
        json=payload or {},
        headers=headers,
    )


def _latest_recommendation(shipment_id) -> Recommendation | None:
    with SessionLocal() as db:
        return db.scalars(
            select(Recommendation)
            .where(Recommendation.shipment_id == shipment_id)
            .order_by(Recommendation.created_at.desc())
        ).first()


def _approval_for(shipment_id) -> Approval | None:
    with SessionLocal() as db:
        return db.scalars(
            select(Approval)
            .where(Approval.shipment_id == shipment_id)
            .order_by(Approval.requested_at.desc())
        ).first()


# --- API: recommendation triggers -------------------------------------------


def test_trigger_returns_durable_status_and_persists_workflow():
    shipment_id = _clone_shipment("ready")
    response = _trigger(shipment_id)
    assert response.status_code == 202, response.text
    body = response.json()
    assert body["shipment_id"] == str(shipment_id)
    # The MVP runs the graph synchronously: the status is the durable execution
    # status (already paused for human approval), never a fabricated "queued".
    assert body["status"] in ("waiting_for_human", "completed")
    workflow_id = uuid.UUID(body["workflow_execution_id"])

    with SessionLocal() as db:
        execution = db.get(Shipment, shipment_id)
        assert execution is not None
    recommendation = _latest_recommendation(shipment_id)
    assert recommendation is not None
    assert recommendation.workflow_execution_id == workflow_id

    workflow_response = client.get(f"/api/v1/workflows/{workflow_id}")
    assert workflow_response.status_code == 200, workflow_response.text
    snapshot = workflow_response.json()
    assert snapshot["workflow_execution_id"] == str(workflow_id)
    assert snapshot["shipment_id"] == str(shipment_id)
    assert snapshot["recommendation_id"] == str(recommendation.id)


def test_trigger_requires_idempotency_key():
    shipment_id = _clone_shipment("ready")
    response = client.post(
        f"/api/v1/shipments/{shipment_id}/recommendations",
        json={},
        headers=csrf_headers(client, "broker"),
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "ERR-001"


def test_trigger_requires_authentication():
    anonymous = TestClient(app)
    response = anonymous.post(
        f"/api/v1/shipments/{_clone_shipment('ready')}/recommendations",
        json={},
        headers={"Idempotency-Key": _key()},
    )
    assert response.status_code == 401


def test_trigger_forbidden_for_viewer():
    shipment_id = _clone_shipment("ready")
    response = _trigger(shipment_id, role="viewer")
    assert response.status_code == 403
    assert _latest_recommendation(shipment_id) is None


def test_trigger_rejects_non_validated_shipment():
    shipment_id = _clone_shipment("ready", status="draft")
    response = _trigger(shipment_id)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "ERR-005"


def test_trigger_rejects_unsupported_scoring_configuration():
    shipment_id = _clone_shipment("ready")
    response = _trigger(shipment_id, payload={"scoring_config_id": str(uuid.uuid4())})
    assert response.status_code == 422
    assert response.json()["code"] == "ERR-001"


def test_trigger_idempotent_replay_returns_cached_workflow():
    shipment_id = _clone_shipment("ready")
    key = _key()
    first = _trigger(shipment_id, key=key)
    assert first.status_code == 202, first.text
    # The shipment is now pending approval, yet a replay of the same key must
    # return the cached result rather than a status-transition error.
    second = _trigger(shipment_id, key=key)
    assert second.status_code == 202, second.text
    assert second.json() == first.json()


# --- API: recommendation reads ----------------------------------------------


def test_recommendation_read_endpoints_expose_ranked_and_excluded_candidates():
    shipment_id = _clone_shipment("ready")
    assert _trigger(shipment_id).status_code == 202
    recommendation = _latest_recommendation(shipment_id)

    listing = client.get(f"/api/v1/shipments/{shipment_id}/recommendations")
    assert listing.status_code == 200, listing.text
    payload = listing.json()
    assert payload["total"] >= 1
    assert str(recommendation.id) in [item["recommendation_id"] for item in payload["items"]]

    detail = client.get(f"/api/v1/recommendations/{recommendation.id}")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["recommendation_id"] == str(recommendation.id)
    assert body["shipment_id"] == str(shipment_id)
    assert body["status"] in ("ready", "no_eligible_carriers", "no_rankable_candidates")
    assert body["explanation"]["template"]

    ranked = [c for c in body["candidates"] if c["rank"] is not None]
    assert ranked, "the ready demo lane must produce at least one ranked candidate"
    assert [c["rank"] for c in ranked] == sorted(c["rank"] for c in ranked)
    assert ranked[0]["composite_score"] is not None
    # Four active components are persisted; deferred components stay null.
    for component in (
        "equipment_fit",
        "capacity_timing",
        "rate_competitiveness",
        "data_completeness",
    ):
        assert ranked[0]["component_scores"][component] is not None
    assert ranked[0]["component_scores"]["lane_familiarity"] is None
    assert ranked[0]["component_scores"]["reliability"] is None

    for excluded in body["ineligible_candidates"]:
        assert excluded["eligibility_status"] in ("ineligible", "insufficient_data")
        assert excluded["ineligibility_codes"]


def test_recommendation_and_workflow_reads_return_404():
    missing = uuid.uuid4()
    assert client.get(f"/api/v1/recommendations/{missing}").status_code == 404
    assert client.get(f"/api/v1/workflows/{missing}").status_code == 404
    assert client.get(f"/api/v1/shipments/{missing}/recommendations").status_code == 404


# --- API: approvals ----------------------------------------------------------


def test_approval_queue_and_decision_resume_workflow():
    shipment_id = _clone_shipment("ready")
    assert _trigger(shipment_id).status_code == 202
    approval = _approval_for(shipment_id)
    assert approval is not None and approval.status == "pending"

    queue = client.get("/api/v1/approvals", params={"status": "pending", "shipment_id": str(shipment_id)})
    assert queue.status_code == 200, queue.text
    assert queue.json()["total"] >= 1
    assert str(approval.id) in [item["approval_id"] for item in queue.json()["items"]]

    detail = client.get(f"/api/v1/approvals/{approval.id}")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    assert detail_body["status"] == "pending"
    assert detail_body["recommendation_status"] == "ready"
    assert detail_body["candidates"]

    decision_key = _key()
    decision = client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approve", "comment": "Lowest landed cost, equipment fit confirmed."},
        headers={**csrf_headers(client, "broker"), "Idempotency-Key": decision_key},
    )
    assert decision.status_code == 200, decision.text
    body = decision.json()
    assert body["status"] == "approved"
    assert body["workflow_status"] == "completed"
    assert body["workflow_outcome"] == "approved"
    assert body["booking_proposal_id"] is not None
    assert body["selected_candidate_id"] is not None

    with SessionLocal() as db:
        assert db.get(Shipment, shipment_id).status == "booking_proposed"

    # Same key replays the cached decision even though the approval is decided.
    replay = client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approve", "comment": "Lowest landed cost, equipment fit confirmed."},
        headers={**csrf_headers(client, "broker"), "Idempotency-Key": decision_key},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json() == body

    # A fresh key on a decided approval is a conflict, not a second decision.
    duplicate = client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "reject"},
        headers={**csrf_headers(client, "broker"), "Idempotency-Key": _key()},
    )
    assert duplicate.status_code == 409, duplicate.text
    assert duplicate.json()["code"] == "ERR-013"


def test_approval_decision_requires_idempotency_key_and_valid_action():
    shipment_id = _clone_shipment("ready")
    assert _trigger(shipment_id).status_code == 202
    approval = _approval_for(shipment_id)

    missing = client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "approve"},
        headers=csrf_headers(client, "broker"),
    )
    assert missing.status_code == 422
    assert missing.json()["code"] == "ERR-001"

    invalid = client.post(
        f"/api/v1/approvals/{approval.id}/decision",
        json={"decision": "maybe"},
        headers={**csrf_headers(client, "broker"), "Idempotency-Key": _key()},
    )
    assert invalid.status_code == 422


# --- UI: server-rendered pages and HTMX partials ----------------------------


def test_ui_approvals_queue_page_renders():
    response = client.get("/approvals")
    assert response.status_code == 200
    assert "Human Broker Review Queue" in response.text
    assert "text/html" in response.headers.get("content-type", "")

    filtered = client.get("/approvals", params={"status_filter": "pending"})
    assert filtered.status_code == 200


def test_ui_shipment_detail_renders_recommendation_panel():
    shipment_id = _clone_shipment("ready")
    response = client.get(f"/shipments/{shipment_id}")
    assert response.status_code == 200, response.text
    assert "Carrier Recommendation" in response.text
    assert "Run Recommendation Workflow" in response.text
    assert 'hx-post="/shipments/' in response.text


def test_ui_run_recommendation_workflow_partial():
    shipment_id = _clone_shipment("ready")
    headers = csrf_headers(client, "broker")
    response = client.post(f"/shipments/{shipment_id}/recommendations", headers=headers)
    assert response.status_code == 200, response.text
    assert "Carrier Recommendation" in response.text
    assert "WAITING FOR HUMAN" in response.text or "COMPLETED" in response.text
    assert "Human approval required" in response.text

    recommendation = _latest_recommendation(shipment_id)
    assert recommendation is not None


def test_ui_recommendation_detail_scorecard_page():
    shipment_id = _clone_shipment("ready")
    assert _trigger(shipment_id).status_code == 202
    recommendation = _latest_recommendation(shipment_id)

    response = client.get(f"/recommendations/{recommendation.id}")
    assert response.status_code == 200, response.text
    assert "Carrier Recommendation Scorecard" in response.text
    assert "Verified Explanation" in response.text
    assert "Ranked Candidates" in response.text
    assert "Evaluated" in response.text
    assert "Human Broker Review" in response.text
    assert "Approve" in response.text


def test_ui_approval_decision_htmx_partial():
    shipment_id = _clone_shipment("ready")
    assert _trigger(shipment_id).status_code == 202
    approval = _approval_for(shipment_id)
    token = login(client, "broker")

    response = client.post(
        f"/ui/approvals/{approval.id}/decision",
        data={"decision": "approve", "comment": "UI approval", "csrf_token": token},
    )
    assert response.status_code == 200, response.text
    assert "APPROVED" in response.text
    assert "booking proposal" in response.text

    with SessionLocal() as db:
        refreshed = db.get(Approval, approval.id)
        assert refreshed.status == "approved"
        assert refreshed.decided_by is not None
        assert db.get(Shipment, shipment_id).status == "booking_proposed"


def test_ui_approval_decision_requires_csrf_for_browser_session():
    shipment_id = _clone_shipment("ready")
    assert _trigger(shipment_id).status_code == 202
    approval = _approval_for(shipment_id)
    login(client, "broker")  # sets the session cookie

    response = client.post(
        f"/ui/approvals/{approval.id}/decision",
        data={"decision": "approve"},
    )
    assert response.status_code == 403
    with SessionLocal() as db:
        assert db.get(Approval, approval.id).status == "pending"

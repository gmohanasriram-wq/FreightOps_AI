"""Deterministic end-to-end demo of the FreightOps AI MVP.

Runs the real FastAPI application in-process against the configured PostgreSQL
database, seeds the synthetic demo data, and walks the complete lifecycle:

    recommendation workflow -> human approval pause -> broker decision
    -> booking proposal -> completed execution

No external network call is made. With the default ``LLM_PROVIDER=offline`` and
``LLM_DEMO_MODE=true``, explanations use the deterministic template and no real
language model is invoked.

Usage:
    .venv-py312/Scripts/python.exe scripts/demo_walkthrough.py
"""
from __future__ import annotations

import copy
import sys
import uuid
from pathlib import Path

root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from sqlalchemy import select
from starlette.testclient import TestClient

from backend.app.core.auth import register_session
from backend.app.core.config import settings
from backend.app.core.security import hash_password
from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.approval import Approval
from backend.app.models.audit import AuditEvent
from backend.app.models.shipment import Shipment, ShipmentStop
from backend.app.models.user import User
from backend.app.services.demo_seed import DEMO_SHIPMENT_IDS, seed_all_demo_data


def _fresh_demo_shipment() -> uuid.UUID:
    """Copy the fixed synthetic 'ready' shipment into a fresh runnable record.

    Using a fresh shipment keeps the walkthrough repeatable: prior runs may have
    left a booking proposal attached to the fixed demo row, and the schema
    forbids a second active proposal for the same shipment.
    """
    with SessionLocal() as db:
        source = db.get(Shipment, DEMO_SHIPMENT_IDS["ready"])
        assert source is not None, "run seed_all_demo_data first"
        shipment = Shipment(
            id=uuid.uuid4(),
            customer_id=source.customer_id,
            origin_facility_id=source.origin_facility_id,
            destination_facility_id=source.destination_facility_id,
            status="validated",
            source="manual",
            reference_number=f"DEMO-WALKTHROUGH-{uuid.uuid4().hex[:8].upper()}",
            commodity=source.commodity,
            equipment_type=source.equipment_type,
            weight_lbs=source.weight_lbs,
            target_sell_rate=source.target_sell_rate,
            max_buy_rate=source.max_buy_rate,
            currency=source.currency,
            lane_origin=source.lane_origin,
            lane_destination=source.lane_destination,
            requirements=copy.deepcopy(source.requirements),
            notes="Synthetic walkthrough copy of the fixed demo shipment.",
            version=1,
        )
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


def _banner(step: str, title: str) -> None:
    print(f"\n[{step}] {title}")
    print("-" * 72)


def _demo_session(client: TestClient) -> str:
    """Attach a synthetic broker session so the demo can call authenticated APIs.

    The demo never prints or stores a password. When demo users are configured
    through environment settings, the seeded broker is reused; otherwise a
    synthetic local broker row is created solely so this script can authenticate.
    """
    with SessionLocal() as db:
        broker = db.execute(select(User).where(User.role == "broker")).scalars().first()
        if broker is None:
            broker = User(
                id=uuid.uuid4(),
                email=f"demo-broker-{uuid.uuid4().hex[:8]}@example.invalid",
                display_name="Synthetic Demo Broker",
                role="broker",
                password_hash=hash_password(uuid.uuid4().hex),
                is_active=True,
            )
            db.add(broker)
            db.commit()
            db.refresh(broker)
        broker_id = broker.id

    session_token = f"demo-session-{uuid.uuid4()}"
    csrf_token = uuid.uuid4().hex
    register_session(session_token, broker_id, csrf_token)
    client.cookies.set("session_id", session_token)
    return csrf_token


def main() -> int:
    print("FreightOps AI — deterministic MVP walkthrough")
    print(f"LLM provider: {settings.LLM_PROVIDER} (demo mode: {settings.LLM_DEMO_MODE})")
    print("All carrier, rate, and shipment records are synthetic.")

    with SessionLocal() as db:
        summary = seed_all_demo_data(db)

    _banner("1", "Synthetic demo data")
    print(
        f"Seeded {summary['carriers']} carriers and {summary['shipments']} shipments; "
        f"active scoring configuration v{summary['scoring_config_version']}."
    )

    shipment_id = _fresh_demo_shipment()
    print(f"Walkthrough shipment: {shipment_id} (fresh copy of the synthetic demo shipment)")
    client = TestClient(app)
    csrf = _demo_session(client)
    headers = {"X-CSRF-Token": csrf}

    with client:
        _banner("2", "Health")
        health = client.get("/api/v1/health")
        health.raise_for_status()
        print(f"API status: {health.json().get('status', 'ok')}")

        _banner("3", "Shipment detail page")
        page = client.get(f"/shipments/{shipment_id}")
        page.raise_for_status()
        assert "Carrier Recommendation" in page.text
        print(f"Rendered shipment page with recommendation panel ({len(page.text):,} bytes).")

        _banner("4", "Trigger the recommendation workflow")
        trigger = client.post(
            f"/api/v1/shipments/{shipment_id}/recommendations",
            json={},
            headers={**headers, "Idempotency-Key": f"demo-{uuid.uuid4()}"},
        )
        trigger.raise_for_status()
        triggered = trigger.json()
        workflow_id = triggered["workflow_execution_id"]
        print(f"Workflow execution: {workflow_id}")
        print(f"Execution status:   {triggered['status']}")

        _banner("5", "Workflow snapshot")
        snapshot = client.get(f"/api/v1/workflows/{workflow_id}").json()
        print(f"Current node: {snapshot['current_node']}  outcome: {snapshot['outcome']}")
        print(
            f"Nodes executed: {snapshot['node_execution_count']}  "
            f"LLM calls: {snapshot['llm_call_count']}  "
            f"trace: {snapshot['trace_id']}"
        )
        assert snapshot["status"] == "waiting_for_human"

        _banner("6", "Ranked recommendation")
        recommendation_id = snapshot["recommendation_id"]
        scorecard = client.get(f"/api/v1/recommendations/{recommendation_id}").json()
        print(f"Recommendation status: {scorecard['status']}")
        print(scorecard["explanation"]["template"])
        ranked = [row for row in scorecard["candidates"] if row["rank"] is not None]
        for row in ranked[:5]:
            print(
                f"  #{row['rank']}  {row['carrier_name']:<26} "
                f"score {row['composite_score']:.4f}  quote ${row['lane_rate_used']:.2f}"
            )
        print(f"Excluded / insufficient-data carriers: {len(scorecard['ineligible_candidates'])}")
        print(
            "Deferred lane-familiarity and reliability components are null and never zero."
        )

        _banner("7", "Broker approval queue")
        queue = client.get(
            "/api/v1/approvals",
            params={"status": "pending", "shipment_id": str(shipment_id)},
        ).json()
        print(f"Pending approvals for this walkthrough shipment: {queue['total']}")
        approval_id = next(
            item["approval_id"]
            for item in queue["items"]
            if item["shipment_id"] == str(shipment_id)
        )
        with SessionLocal() as db:
            approval = db.get(Approval, uuid.UUID(approval_id))
            assert approval is not None
        print(f"Approval {approval_id} is '{approval.status}'.")

        _banner("8", "Human decision: approve")
        decision = client.post(
            f"/api/v1/approvals/{approval_id}/decision",
            json={"decision": "approve", "comment": "Demo approval of the top-ranked carrier."},
            headers={**headers, "Idempotency-Key": f"demo-{uuid.uuid4()}"},
        )
        decision.raise_for_status()
        decided = decision.json()
        print(f"Approval status:  {decided['status']}")
        print(f"Workflow status:  {decided['workflow_status']} ({decided['workflow_outcome']})")
        print(f"Booking proposal: {decided['booking_proposal_id']}")

        _banner("9", "Completed execution and booking proposal")
        final = client.get(f"/api/v1/workflows/{workflow_id}").json()
        print(f"Final node: {final['current_node']}  status: {final['status']}")
        print(f"Outcome:    {final['outcome']}")
        with SessionLocal() as db:
            shipment = db.get(Shipment, shipment_id)
            audit_count = len(
                db.scalars(
                    select(AuditEvent).where(
                        AuditEvent.workflow_execution_id == uuid.UUID(workflow_id)
                    )
                ).all()
            )
        print(f"Shipment status: {shipment.status}  frozen: {shipment.frozen_at is not None}")
        print(f"Immutable audit events recorded for this execution: {audit_count}")

        _banner("10", "Scorecard page")
        scorecard_page = client.get(f"/recommendations/{recommendation_id}")
        scorecard_page.raise_for_status()
        assert "Carrier Recommendation Scorecard" in scorecard_page.text
        assert "Human Broker Review" in scorecard_page.text
        print("Scorecard and approval panel rendered.")

    print("\nDemo complete. No real carrier data and no paid LLM call were used.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

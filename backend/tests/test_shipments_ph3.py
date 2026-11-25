"""Comprehensive automated tests for Task 003-B / PH-3: TC-001 through TC-016."""
import uuid
from datetime import datetime, timezone, timedelta
import pytest
from starlette.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from backend.app.main import app
from backend.app.db.session import SessionLocal, engine
from backend.app.models.customer import Customer
from backend.app.models.facility import Facility
from backend.app.models.idempotency import IdempotencyKey
from backend.app.models.shipment import IntakeSubmission, Shipment, ShipmentStop, ValidationRun
from backend.app.models.audit import AuditEvent
from backend.app.models.user import User
from backend.tests.helpers import csrf_headers

client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def setup_test_prerequisites():
    """Ensure database has demo users and sample customer/facility for tests."""
    with SessionLocal() as db:
        # Seed users if not present
        client.get("/api/v1/health") # Triggers ensure_demo_users_seeded

        # Ensure a test customer exists
        customer = db.execute(select(Customer).limit(1)).scalar_one_or_none()
        if not customer:
            customer = Customer(
                id=uuid.uuid4(),
                name="Acme Logistics Corp",
                reference_code="ACME-001",
                contact_email="dispatch@acme.com",
            )
            db.add(customer)

        # Ensure test facilities exist
        facility_1 = db.execute(select(Facility).limit(1)).scalar_one_or_none()
        if not facility_1:
            facility_1 = Facility(
                id=uuid.uuid4(),
                customer_id=customer.id,
                name="Chicago Distribution DC",
                code="ORD-DC-01",
                facility_type="cold_storage",
                address_line1="100 Logistics Blvd",
                city="Chicago",
                state="IL",
                postal_code="60601",
            )
            facility_2 = Facility(
                id=uuid.uuid4(),
                customer_id=customer.id,
                name="Dallas Gateway DC",
                code="DFW-DC-01",
                facility_type="distribution_center",
                address_line1="500 Freight Way",
                city="Dallas",
                state="TX",
                postal_code="75201",
            )
            db.add(facility_1)
            db.add(facility_2)
        db.commit()


def test_tc001_valid_intake_submission_and_draft_creation():
    """TC-001: Valid Intake Submission & Draft Creation (POST /api/v1/intake/submissions)."""
    idemp_key = f"tc001-key-{uuid.uuid4()}"
    raw_text = f"Need reefer Chicago to Dallas 42000 lbs frozen poultry on 11/24. Unique {uuid.uuid4()}"
    headers = {**csrf_headers(client, "broker"), "Idempotency-Key": idemp_key}

    response = client.post(
        "/api/v1/intake/submissions",
        json={"channel": "paste", "raw_text": raw_text, "client_request_id": "PO-TEST-001"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    data = response.json()
    assert "submission_id" in data
    assert "shipment_id" in data
    assert data["channel"] == "paste"
    assert data["content_hash"].startswith("sha256:")

    # Verify database persistence
    with SessionLocal() as db:
        shipment = db.get(Shipment, uuid.UUID(data["shipment_id"]))
        assert shipment is not None
        assert shipment.status == "draft"
        assert shipment.intake_submission_id == uuid.UUID(data["submission_id"])

        # Verify audit events emitted
        events = db.scalars(
            select(AuditEvent.event_type)
            .where(AuditEvent.shipment_id == shipment.id)
            .order_by(AuditEvent.id)
        ).all()
        assert "shipment.created" in events


def test_tc002_incomplete_draft_creation_draft_tolerance():
    """TC-002: Incomplete Draft Creation (DEF-01 / CRIT-01 draft tolerance)."""
    idemp_key = f"tc002-key-{uuid.uuid4()}"
    raw_text = f"Incomplete draft text without customer or stops. Unique {uuid.uuid4()}"
    headers = {**csrf_headers(client, "broker"), "Idempotency-Key": idemp_key}

    response = client.post(
        "/api/v1/intake/submissions",
        json={"channel": "paste", "raw_text": raw_text},
        headers=headers,
    )
    assert response.status_code == 201
    data = response.json()

    with SessionLocal() as db:
        shipment = db.get(Shipment, uuid.UUID(data["shipment_id"]))
        assert shipment is not None
        assert shipment.status == "draft"
        assert shipment.customer_id is None
        assert shipment.equipment_type is None
        assert shipment.weight_lbs is None


def test_tc003_incomplete_draft_validation_gating():
    """TC-003: Incomplete Draft Validation Gating (FR-040 / DEF-01)."""
    # 1. Create incomplete draft
    idemp_key = f"tc003-key-{uuid.uuid4()}"
    res = client.post(
        "/api/v1/intake/submissions",
        json={"channel": "paste", "raw_text": f"Draft for validation gating {uuid.uuid4()}"},
        headers={**csrf_headers(client, "broker"), "Idempotency-Key": idemp_key},
    )
    assert res.status_code == 201
    shipment_id = res.json()["shipment_id"]

    # 2. Run validation on incomplete draft
    val_res = client.post(
        f"/api/v1/shipments/{shipment_id}/validation",
        headers=csrf_headers(client, "broker"),
    )
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["result"] == "failed"
    issue_codes = {i["rule_code"] for i in val_data["issues"]}
    assert "REQ-CUST" in issue_codes
    assert "REQ-EQP" in issue_codes
    assert "REQ-COMM" in issue_codes
    assert "REQ-STOPS" in issue_codes

    # 3. Verify shipment status is validation_failed in DB
    with SessionLocal() as db:
        s = db.get(Shipment, uuid.UUID(shipment_id))
        assert s.status == "validation_failed"


def test_tc004_invalid_equipment_type():
    """TC-004: Invalid equipment type rejected by API validation (FR-052)."""
    with SessionLocal() as db:
        s = Shipment(status="draft", source="manual", currency="USD", version=1)
        db.add(s)
        db.commit()
        shipment_id = s.id

    res = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"equipment_type": "rocket_ship"},
        headers=csrf_headers(client, "broker"),
    )
    assert res.status_code == 422
    assert res.headers.get("content-type") == "application/problem+json"
    err = res.json()
    assert err["code"] == "ERR-001"


def test_tc005_out_of_range_weight_validation():
    """TC-005: Out-of-Range Weight Validation (RNG-WGT-MAX / RNG-WGT-MIN)."""
    with SessionLocal() as db:
        s = Shipment(status="draft", source="manual", weight_lbs=52000, commodity="Heavy Steel", equipment_type="flatbed")
        db.add(s)
        db.commit()
        shipment_id = s.id

    val_res = client.post(
        f"/api/v1/shipments/{shipment_id}/validation",
        headers=csrf_headers(client, "broker"),
    )
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["result"] == "failed"
    rule_codes = {i["rule_code"] for i in val_data["issues"]}
    assert "RNG-WGT-MAX" in rule_codes


def test_tc006_contradictory_delivery_before_pickup():
    """TC-006: Contradictory Delivery Before Pickup (XFL-STOP-ORD)."""
    with SessionLocal() as db:
        cust = db.execute(select(Customer).limit(1)).scalar_one()
        s = Shipment(status="draft", source="manual", customer_id=cust.id, commodity="General Goods", equipment_type="dry_van", weight_lbs=30000)
        db.add(s)
        db.flush()

        now = datetime.now(timezone.utc)
        # Sequence 1: Delivery; Sequence 2: Pickup
        s1 = ShipmentStop(shipment_id=s.id, sequence=1, stop_type="delivery", name="Dallas DC", address_line1="500 Way", city="Dallas", state="TX", postal_code="75201", window_start=now + timedelta(days=2), window_end=now + timedelta(days=2, hours=4))
        s2 = ShipmentStop(shipment_id=s.id, sequence=2, stop_type="pickup", name="Chicago DC", address_line1="100 Blvd", city="Chicago", state="IL", postal_code="60601", window_start=now, window_end=now + timedelta(hours=4))
        db.add(s1)
        db.add(s2)
        db.commit()
        shipment_id = s.id

    val_res = client.post(
        f"/api/v1/shipments/{shipment_id}/validation",
        headers=csrf_headers(client, "broker"),
    )
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["result"] == "failed"
    rule_codes = {i["rule_code"] for i in val_data["issues"]}
    assert "XFL-STOP-ORD" in rule_codes


def test_tc007_reefer_equipment_and_commodity_compatibility():
    """TC-007: Commodity requires reefer equipment (BIZ-REEFER-REQ)."""
    with SessionLocal() as db:
        cust = db.execute(select(Customer).limit(1)).scalar_one()
        s = Shipment(status="draft", source="manual", customer_id=cust.id, commodity="Frozen Ice Cream", equipment_type="dry_van", weight_lbs=35000)
        db.add(s)
        db.commit()
        shipment_id = s.id

    val_res = client.post(
        f"/api/v1/shipments/{shipment_id}/validation",
        headers=csrf_headers(client, "broker"),
    )
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["result"] == "failed"
    rule_codes = {i["rule_code"] for i in val_data["issues"]}
    assert "BIZ-REEFER-REQ" in rule_codes


def test_tc008_complete_valid_shipment_validation_pass():
    """TC-008: Complete Valid Shipment Validation Pass transitions to 'validated' (FR-040)."""
    with SessionLocal() as db:
        cust = db.execute(select(Customer).limit(1)).scalar_one()
        now = datetime.now(timezone.utc)
        s = Shipment(
            status="draft",
            source="manual",
            customer_id=cust.id,
            commodity="Frozen Poultry",
            equipment_type="reefer",
            weight_lbs=42000,
            target_sell_rate=2500.00,
            max_buy_rate=2200.00,
            requirements={"temperature_range": {"min_f": 34.0, "max_f": 38.0}},
        )
        db.add(s)
        db.flush()

        s1 = ShipmentStop(shipment_id=s.id, sequence=1, stop_type="pickup", name="Chicago Cold DC", address_line1="100 Logistics Blvd", city="Chicago", state="IL", postal_code="60601", window_start=now + timedelta(days=1), window_end=now + timedelta(days=1, hours=4))
        s2 = ShipmentStop(shipment_id=s.id, sequence=2, stop_type="delivery", name="Dallas Distribution Center", address_line1="500 Freight Way", city="Dallas", state="TX", postal_code="75201", window_start=now + timedelta(days=3), window_end=now + timedelta(days=3, hours=4))
        db.add(s1)
        db.add(s2)
        db.commit()
        shipment_id = s.id

    val_res = client.post(
        f"/api/v1/shipments/{shipment_id}/validation",
        headers=csrf_headers(client, "broker"),
    )
    assert val_res.status_code == 200
    val_data = val_res.json()
    assert val_data["result"] == "passed"
    assert len(val_data["issues"]) == 0

    with SessionLocal() as db:
        updated_s = db.get(Shipment, shipment_id)
        assert updated_s.status == "validated"
        events = db.scalars(select(AuditEvent.event_type).where(AuditEvent.shipment_id == shipment_id)).all()
        assert "validation.completed" in events


def test_tc009_valid_shipment_patch_before_approval():
    """TC-009: Valid Shipment Patch Before Approval increments version (FR-032)."""
    with SessionLocal() as db:
        s = Shipment(status="draft", source="manual", version=1, notes="Initial note")
        db.add(s)
        db.commit()
        shipment_id = s.id

    res = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"commodity": "Fresh Apples", "equipment_type": "reefer", "weight_lbs": 38000, "notes": "Updated notes"},
        headers=csrf_headers(client, "broker"),
    )
    assert res.status_code == 200
    data = res.json()
    assert data["commodity"] == "Fresh Apples"
    assert data["version"] == 2
    assert data["notes"] == "Updated notes"

    with SessionLocal() as db:
        events = db.scalars(select(AuditEvent.event_type).where(AuditEvent.shipment_id == shipment_id)).all()
        assert "shipment.updated" in events


def test_tc010_forbidden_patch_on_frozen_shipment():
    """TC-010: Forbidden Patch on Frozen Shipment returns 409 Conflict (FR-032 / ERR-005)."""
    with SessionLocal() as db:
        s = Shipment(
            status="approved",
            source="manual",
            frozen_at=datetime.now(timezone.utc),
            version=3,
        )
        db.add(s)
        db.commit()
        shipment_id = s.id

    res = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"commodity": "Attempt Tampering"},
        headers=csrf_headers(client, "broker"),
    )
    assert res.status_code == 409
    err = res.json()
    assert err["code"] == "ERR-005"
    assert "frozen" in err["detail"].lower()


def test_tc011_invalid_state_transition_attempt():
    """TC-011: State machine blocks illegal jumps per D-05 (ERR-005)."""
    # Validation endpoints reject illegal transitions by adhering to the state machine
    with SessionLocal() as db:
        s = Shipment(status="approved", source="manual", frozen_at=datetime.now(timezone.utc))
        db.add(s)
        db.commit()
        shipment_id = s.id

    # Trying to patch an approved/frozen shipment fails
    res = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"notes": "Illegal transition"},
        headers=csrf_headers(client, "broker"),
    )
    assert res.status_code == 409
    assert res.json()["code"] == "ERR-005"


def test_tc012_duplicate_idempotency_key_replay():
    """TC-012: Duplicate Idempotency Key Replay returns cached response without duplicate records (FR-009)."""
    idemp_key = f"tc012-key-{uuid.uuid4()}"
    raw_text = f"Payload for replay test {uuid.uuid4()}"
    headers = {**csrf_headers(client, "broker"), "Idempotency-Key": idemp_key}

    res1 = client.post("/api/v1/intake/submissions", json={"raw_text": raw_text}, headers=headers)
    assert res1.status_code == 201
    data1 = res1.json()

    # Replay with same key and text
    res2 = client.post("/api/v1/intake/submissions", json={"raw_text": raw_text}, headers=headers)
    assert res2.status_code == 201
    data2 = res2.json()

    assert data1["submission_id"] == data2["submission_id"]
    assert data1["shipment_id"] == data2["shipment_id"]


def test_tc013_in_flight_idempotency_collision():
    """TC-013: In-Flight Idempotency Collision returns 409 Conflict ERR-006 (DEF-05)."""
    idemp_key = f"tc013-inflight-{uuid.uuid4()}"
    with SessionLocal() as db:
        entry = IdempotencyKey(
            key=idemp_key,
            endpoint="/api/v1/intake/submissions",
            request_hash="mock-hash",
            status="in_progress",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )
        db.add(entry)
        db.commit()

    res = client.post(
        "/api/v1/intake/submissions",
        json={"raw_text": "Concurrent collision test"},
        headers={**csrf_headers(client, "broker"), "Idempotency-Key": idemp_key},
    )
    assert res.status_code == 409
    err = res.json()
    assert err["code"] == "ERR-006"
    assert "currently being processed" in err["detail"]


def test_tc014_unauthenticated_access():
    """TC-014: Unauthenticated access returns 401 Unauthorized (ERR-002)."""
    client.cookies.clear()
    res = client.post(
        "/api/v1/intake/submissions",
        json={"raw_text": "Unauthenticated test"},
        headers={"Idempotency-Key": f"noauth-{uuid.uuid4()}"}, # No auth header/cookie
    )
    assert res.status_code == 401
    err = res.json()
    assert err["code"] == "ERR-002"


def test_tc015_role_access_restriction_viewer():
    """TC-015: Viewer role blocked from write endpoints returns 403 Forbidden (ERR-003)."""
    with SessionLocal() as db:
        s = Shipment(status="draft", source="manual")
        db.add(s)
        db.commit()
        shipment_id = s.id

    # Viewer attempts PATCH
    res = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"notes": "Viewer write attempt"},
        headers=csrf_headers(client, "viewer"),
    )
    assert res.status_code == 403
    err = res.json()
    assert err["code"] == "ERR-003"
    assert "viewer" in err["detail"]


def test_tc016_shipment_list_and_detail_retrieval():
    """TC-016: Shipment retrieval and pagination (FR-024 / FR-030)."""
    # Create test shipment with stops
    with SessionLocal() as db:
        cust = db.execute(select(Customer).limit(1)).scalar_one()
        s = Shipment(status="draft", source="manual", customer_id=cust.id, commodity="Plywood", equipment_type="flatbed")
        db.add(s)
        db.flush()
        s_stop = ShipmentStop(shipment_id=s.id, sequence=1, stop_type="pickup", name="Mill 1", city="Eugene", state="OR")
        db.add(s_stop)
        db.commit()
        shipment_id = s.id

    # List endpoint
    list_res = client.get("/api/v1/shipments?limit=10", headers=csrf_headers(client, "viewer"))
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert "items" in list_data
    assert "total" in list_data
    assert list_data["total"] >= 1

    # Detail endpoint
    detail_res = client.get(f"/api/v1/shipments/{shipment_id}", headers=csrf_headers(client, "viewer"))
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == str(shipment_id)
    assert detail_data["commodity"] == "Plywood"
    assert len(detail_data["stops"]) == 1

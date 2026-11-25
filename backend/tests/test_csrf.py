"""CSRF protection tests (Task 003-BR, C-007)."""
import uuid

from starlette.testclient import TestClient

from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.models.shipment import Shipment
from backend.tests.helpers import login


def make_client() -> TestClient:
    return TestClient(app)


def create_draft_shipment() -> uuid.UUID:
    with SessionLocal() as db:
        shipment = Shipment(status="draft", source="manual", version=1)
        db.add(shipment)
        db.commit()
        return shipment.id


def intake_body() -> dict:
    return {"raw_text": f"CSRF protection probe {uuid.uuid4()}"}


def test_intake_post_without_csrf_token_returns_403():
    client = make_client()
    login(client, "broker")

    response = client.post(
        "/api/v1/intake/submissions",
        json=intake_body(),
        headers={"Idempotency-Key": f"csrf-missing-{uuid.uuid4()}"},
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["code"] == "ERR-003"
    assert "csrf" in (payload["title"] + payload["detail"]).lower()


def test_intake_post_with_invalid_csrf_token_returns_403():
    client = make_client()
    login(client, "broker")

    response = client.post(
        "/api/v1/intake/submissions",
        json=intake_body(),
        headers={
            "Idempotency-Key": f"csrf-invalid-{uuid.uuid4()}",
            "X-CSRF-Token": "0" * 32,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ERR-003"


def test_token_from_another_session_is_rejected():
    first = make_client()
    first_token = login(first, "broker")

    second = make_client()
    second_token = login(second, "broker")
    assert first_token != second_token

    response = first.post(
        "/api/v1/intake/submissions",
        json=intake_body(),
        headers={
            "Idempotency-Key": f"csrf-mismatch-{uuid.uuid4()}",
            "X-CSRF-Token": second_token,
        },
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ERR-003"


def test_intake_post_with_valid_csrf_token_succeeds():
    client = make_client()
    token = login(client, "broker")

    response = client.post(
        "/api/v1/intake/submissions",
        json=intake_body(),
        headers={
            "Idempotency-Key": f"csrf-valid-{uuid.uuid4()}",
            "X-CSRF-Token": token,
        },
    )

    assert response.status_code == 201


def test_get_does_not_require_csrf_token():
    client = make_client()
    login(client, "broker")
    assert client.get("/api/v1/shipments?limit=1").status_code == 200


def test_shipment_patch_requires_csrf_token():
    client = make_client()
    token = login(client, "broker")
    shipment_id = create_draft_shipment()

    rejected = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"notes": "should be rejected"},
    )
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "ERR-003"

    accepted = client.patch(
        f"/api/v1/shipments/{shipment_id}",
        json={"notes": "csrf accepted"},
        headers={"X-CSRF-Token": token},
    )
    assert accepted.status_code == 200
    assert accepted.json()["notes"] == "csrf accepted"


def test_validation_post_requires_csrf_token():
    client = make_client()
    token = login(client, "broker")
    shipment_id = create_draft_shipment()

    rejected = client.post(f"/api/v1/shipments/{shipment_id}/validation")
    assert rejected.status_code == 403
    assert rejected.json()["code"] == "ERR-003"

    accepted = client.post(
        f"/api/v1/shipments/{shipment_id}/validation",
        headers={"X-CSRF-Token": token},
    )
    assert accepted.status_code == 200

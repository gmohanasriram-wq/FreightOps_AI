"""CSRF integration for authenticated Jinja2/HTMX state-changing routes (Task 003-BR, item 7)."""
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


def test_detail_page_embeds_session_bound_csrf_token():
    client = make_client()
    token = login(client, "broker")
    shipment_id = create_draft_shipment()

    response = client.get(f"/shipments/{shipment_id}")

    assert response.status_code == 200
    assert 'name="csrf_token"' in response.text
    assert token in response.text
    assert "X-CSRF-Token" in response.text


def test_authenticated_htmx_validation_without_token_is_rejected():
    client = make_client()
    login(client, "broker")
    shipment_id = create_draft_shipment()

    response = client.post(f"/shipments/{shipment_id}/validation")

    assert response.status_code == 403
    assert response.json()["code"] == "ERR-003"


def test_authenticated_htmx_validation_with_token_succeeds():
    client = make_client()
    token = login(client, "broker")
    shipment_id = create_draft_shipment()

    response = client.post(
        f"/shipments/{shipment_id}/validation",
        headers={"X-CSRF-Token": token},
    )

    assert response.status_code == 200
    assert "VALIDATION" in response.text


def test_authenticated_form_post_accepts_hidden_csrf_field():
    client = make_client()
    token = login(client, "broker")
    shipment_id = create_draft_shipment()

    response = client.post(
        f"/shipments/{shipment_id}/edit",
        data={"notes": "csrf ui form", "csrf_token": token},
        follow_redirects=False,
    )

    assert response.status_code == 303


def test_authenticated_form_post_without_csrf_field_is_rejected():
    client = make_client()
    login(client, "broker")
    shipment_id = create_draft_shipment()

    response = client.post(
        f"/shipments/{shipment_id}/edit",
        data={"notes": "missing token"},
        follow_redirects=False,
    )

    assert response.status_code == 403
    assert response.json()["code"] == "ERR-003"

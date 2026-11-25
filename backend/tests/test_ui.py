"""Tests for Jinja2 + HTMX server-rendered UI per Contract 2.2 ADR-003."""
import pytest
from starlette.testclient import TestClient
from backend.app.main import app

client = TestClient(app)


def test_ui_dashboard_page():
    """Verify that root / renders the full HTML dashboard."""
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "FreightOps AI" in response.text
    assert "Contract 2.2" in response.text
    assert "Jinja2 + HTMX (ADR-003)" in response.text
    assert "health-status-container" in response.text
    assert 'hx-get="/ui/partials/health-status"' in response.text


def test_ui_health_status_partial():
    """Verify that /ui/partials/health-status renders the HTMX fragment."""
    response = client.get("/ui/partials/health-status")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "PostgreSQL 16+" in response.text
    assert "FastAPI" in response.text
    assert "Modular Monolith" in response.text
    assert "HTMX Live Polling" in response.text


def test_ui_shipments_list():
    """Verify that /shipments renders the shipment table."""
    response = client.get("/shipments")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "Shipments" in response.text
    assert "Status" in response.text
    assert "+ New Intake" in response.text


def test_ui_shipment_new_page_and_submission():
    """Verify GET /shipments/new and POST /shipments/new intake form flow."""
    get_res = client.get("/shipments/new")
    assert get_res.status_code == 200
    assert "Unstructured Request Text" in get_res.text
    assert "Submit & Create Draft" in get_res.text

    import uuid
    unique_ref = f"UI-TEST-{uuid.uuid4().hex[:8]}"
    sample_tender = (
        f"Reference {unique_ref}\n"
        "Pickup: Dallas, TX 75201 on 2026-12-01 08:00\n"
        "Delivery: Atlanta, GA 30301 on 2026-12-03 16:00\n"
        "Equipment: Dry Van 53ft, Weight: 38,000 lbs, Commodity: Consumer Electronics"
    )
    post_res = client.post(
        "/shipments/new",
        data={"raw_text": sample_tender, "channel": "paste", "client_request_id": unique_ref},
        follow_redirects=False,
    )
    assert post_res.status_code == 303
    redirect_url = post_res.headers.get("location")
    assert "/shipments/" in redirect_url

    # Follow redirect to shipment detail page
    detail_res = client.get(redirect_url)
    assert detail_res.status_code == 200
    assert "Shipments" in detail_res.text
    assert "Run Validation" in detail_res.text
    assert "Shipment Specifications" in detail_res.text

    # Trigger HTMX validation via UI endpoint
    val_res = client.post(f"{redirect_url}/validation")
    assert val_res.status_code == 200
    assert "text/html" in val_res.headers.get("content-type", "")
    assert ("VALIDATION PASSED" in val_res.text or "VALIDATION FAILED" in val_res.text or "VALIDATION BLOCKED" in val_res.text)

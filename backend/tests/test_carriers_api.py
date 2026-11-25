"""Carrier discovery API tests."""
from starlette.testclient import TestClient

from backend.app.db.session import SessionLocal
from backend.app.main import app
from backend.app.services.demo_seed import seed_all_demo_data
from backend.tests.helpers import login

client = TestClient(app)


def _seed():
    with SessionLocal() as db:
        seed_all_demo_data(db)


def test_carrier_list_returns_synthetic_carriers():
    _seed()
    login(client, "viewer")

    response = client.get("/api/v1/carriers")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["total"] >= 16
    assert body["items"]
    first = body["items"][0]
    assert first["data_source"] == "synthetic"
    assert "summary" in first
    assert isinstance(first["equipment_types"], list)


def test_carrier_list_filters_by_equipment_and_region():
    _seed()
    login(client, "viewer")

    reefer = client.get("/api/v1/carriers", params={"equipment_type": "reefer"})
    assert reefer.status_code == 200
    for item in reefer.json()["items"]:
        assert "reefer" in item["summary"]["equipment_types"]

    texas = client.get(
        "/api/v1/carriers", params={"region_type": "state", "region_value": "TX"}
    )
    assert texas.status_code == 200
    assert texas.json()["items"]
    for item in texas.json()["items"]:
        assert "TX" in item["summary"]["service_states"]

    none = client.get(
        "/api/v1/carriers", params={"region_type": "state", "region_value": "FL"}
    )
    assert none.status_code == 200
    assert none.json()["items"] == []


def test_carrier_detail_returns_all_relationship_rows():
    _seed()
    login(client, "viewer")

    listing = client.get("/api/v1/carriers", params={"limit": 200}).json()
    item = next(i for i in listing["items"] if i["mc_number"] == "MC-DEMO-1001")
    response = client.get(f"/api/v1/carriers/{item['id']}")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["legal_name"] == "Apex Freight LLC"
    assert {e["equipment_type"] for e in body["equipment_types"]} == {"dry_van", "reefer"}
    assert {r["region_value"] for r in body["service_regions"]} == {"IL", "TX"}
    assert body["lane_rates"]
    assert body["availability"]


def test_carrier_detail_404():
    login(client, "viewer")
    response = client.get("/api/v1/carriers/00000000-0000-4000-8000-000000000000")
    assert response.status_code == 404
    assert response.json()["code"] == "ERR-004"

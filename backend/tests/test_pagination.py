"""Shipment pagination boundary tests (Task 003-BR, item 6)."""
from starlette.testclient import TestClient

from backend.app.main import app
from backend.tests.helpers import login


def make_client() -> TestClient:
    return TestClient(app)


def test_default_limit_is_50():
    client = make_client()
    login(client, "viewer")

    response = client.get("/api/v1/shipments")

    assert response.status_code == 200
    assert response.json()["limit"] == 50


def test_limit_boundaries():
    client = make_client()
    login(client, "viewer")

    assert client.get("/api/v1/shipments?limit=1").json()["limit"] == 1
    assert client.get("/api/v1/shipments?limit=200").json()["limit"] == 200
    assert client.get("/api/v1/shipments?limit=0").status_code == 422
    assert client.get("/api/v1/shipments?limit=201").status_code == 422


def test_offset_is_preserved():
    client = make_client()
    login(client, "viewer")

    response = client.get("/api/v1/shipments?limit=50&offset=5")

    assert response.status_code == 200
    payload = response.json()
    assert payload["limit"] == 50
    assert payload["offset"] == 5

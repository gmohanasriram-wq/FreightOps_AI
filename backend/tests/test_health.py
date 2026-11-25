"""Tests for the health check endpoints."""
import pytest
from starlette.testclient import TestClient
from backend.app.main import app
from backend.app.core.config import settings

client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "FreightOps AI" in response.text


def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert "llm_provider" in data
    assert data["llm_provider"] == "ready"
    assert data["version"] == settings.VERSION
    assert "database_details" in data
    assert "connected" in data["database_details"]
    assert "details" in data["database_details"]


def test_api_v1_health_endpoint():
    response = client.get(f"{settings.API_V1_STR}/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "database" in data
    assert data["database"] in ["ok", "unavailable"]

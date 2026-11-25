"""Session-cookie authentication integration tests (Task 003-BR, C-006)."""
import pytest
from starlette.testclient import TestClient

from backend.app.core.config import Settings
from backend.app.main import app
from backend.tests.helpers import DEMO_CREDENTIALS, login


def make_client() -> TestClient:
    return TestClient(app)


def get_set_cookie(response, name: str):
    """Return the raw Set-Cookie header for a named cookie, if present."""
    for header in response.headers.get_list("set-cookie"):
        if header.startswith(f"{name}="):
            return header
    return None


def test_login_issues_httponly_samesite_session_cookie():
    client = make_client()
    response = client.post("/api/v1/auth/login", json=DEMO_CREDENTIALS["broker"])
    assert response.status_code == 200

    session_cookie = get_set_cookie(response, "session_id")
    assert session_cookie is not None
    lowered = session_cookie.lower()
    assert "httponly" in lowered
    assert "samesite=lax" in lowered
    assert "path=/" in lowered
    # Development runs over plain HTTP, so Secure must be off here.
    assert "secure" not in lowered

    csrf_token = response.json()["csrf_token"]
    assert isinstance(csrf_token, str)
    assert len(csrf_token) == 32


def test_session_cookie_grants_access_to_protected_endpoint():
    client = make_client()
    login(client, "broker")
    response = client.get("/api/v1/shipments?limit=1")
    assert response.status_code == 200


def test_unauthenticated_request_is_rejected():
    client = make_client()
    response = client.get("/api/v1/shipments")
    assert response.status_code == 401
    assert response.json()["code"] == "ERR-002"


def test_invalid_password_is_rejected():
    client = make_client()
    response = client.post(
        "/api/v1/auth/login",
        json={"email": DEMO_CREDENTIALS["broker"]["email"], "password": "wrong-password"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ERR-002"


def test_x_user_email_header_alone_does_not_authenticate():
    client = make_client()
    response = client.get(
        "/api/v1/shipments",
        headers={"X-User-Email": "admin@freightops.com"},
    )
    assert response.status_code == 401
    assert response.json()["code"] == "ERR-002"

    me = client.get(
        "/api/v1/auth/me",
        headers={"X-User-Email": "admin@freightops.com"},
    )
    assert me.status_code == 401


def test_me_returns_session_bound_csrf_token():
    client = make_client()
    token = login(client, "broker")
    response = client.get("/api/v1/auth/me")
    assert response.status_code == 200
    assert response.json()["csrf_token"] == token


def test_logout_requires_csrf_and_revokes_session():
    client = make_client()
    token = login(client, "broker")
    old_session = client.cookies.get("session_id")
    assert old_session

    denied = client.post("/api/v1/auth/logout")
    assert denied.status_code == 403
    assert denied.json()["code"] == "ERR-003"
    assert "csrf" in (denied.json()["title"] + denied.json()["detail"]).lower()

    # The failed logout must not invalidate the session.
    assert client.get("/api/v1/shipments?limit=1").status_code == 200

    accepted = client.post("/api/v1/auth/logout", headers={"X-CSRF-Token": token})
    assert accepted.status_code == 204

    replay_client = make_client()
    replay_client.cookies.set("session_id", old_session)
    replay = replay_client.get("/api/v1/shipments?limit=1")
    assert replay.status_code == 401


def test_cookie_secure_is_enabled_outside_development():
    assert Settings(ENVIRONMENT="development").COOKIE_SECURE is False
    assert Settings(ENVIRONMENT="production", SESSION_COOKIE_SECURE=False).COOKIE_SECURE is True


def test_session_and_csrf_cookies_follow_secure_policy(monkeypatch):
    from backend.app.api.v1 import auth as auth_module

    client = make_client()
    response = client.post("/api/v1/auth/login", json=DEMO_CREDENTIALS["broker"])
    assert response.status_code == 200
    for name in ("session_id", "csrf_token"):
        assert "secure" not in get_set_cookie(response, name).lower()

    monkeypatch.setattr(auth_module.settings, "SESSION_COOKIE_SECURE", True)
    secure_client = make_client()
    secure_response = secure_client.post("/api/v1/auth/login", json=DEMO_CREDENTIALS["broker"])
    assert secure_response.status_code == 200
    for name in ("session_id", "csrf_token"):
        assert "secure" in get_set_cookie(secure_response, name).lower()

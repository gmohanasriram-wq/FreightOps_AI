"""Shared test helpers for authenticating through the real login endpoint."""

DEMO_CREDENTIALS = {
    "admin": {"email": "admin@freightops.com", "password": "adminpassword123"},
    "broker": {"email": "broker@freightops.com", "password": "brokerpassword123"},
    "viewer": {"email": "viewer@freightops.com", "password": "viewerpassword123"},
}


def login(client, role: str = "broker") -> str:
    """Log in through the real endpoint, set the session cookie, return the CSRF token."""
    response = client.post("/api/v1/auth/login", json=DEMO_CREDENTIALS[role])
    assert response.status_code == 200, response.text
    return response.json()["csrf_token"]


def csrf_headers(client, role: str = "broker") -> dict:
    """Log in as the given role and return state-changing request headers."""
    return {"X-CSRF-Token": login(client, role)}

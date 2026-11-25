"""Demo-user seeding must use explicit environment credentials (Task GIT-002)."""
from pathlib import Path

from backend.app.core import auth as auth_module
from backend.app.core.security import verify_password
from backend.tests.helpers import DEMO_CREDENTIALS

DEMO_FIELDS = (
    ("DEMO_ADMIN_EMAIL", "DEMO_ADMIN_PASSWORD"),
    ("DEMO_BROKER_EMAIL", "DEMO_BROKER_PASSWORD"),
    ("DEMO_VIEWER_EMAIL", "DEMO_VIEWER_PASSWORD"),
)
ROLES = ("admin", "broker", "viewer")
ENV_PASSWORDS = {
    "DEMO_ADMIN_PASSWORD": "test-admin-password",
    "DEMO_BROKER_PASSWORD": "test-broker-password",
    "DEMO_VIEWER_PASSWORD": "test-viewer-password",
}


def clear_demo_settings(monkeypatch):
    for email_field, password_field in DEMO_FIELDS:
        monkeypatch.setattr(auth_module.settings, email_field, None, raising=False)
        monkeypatch.setattr(auth_module.settings, password_field, None, raising=False)


def configure_demo_settings(monkeypatch):
    for index, (email_field, password_field) in enumerate(DEMO_FIELDS):
        monkeypatch.setattr(
            auth_module.settings, email_field, f"demo{index}@example.test", raising=False
        )
        monkeypatch.setattr(
            auth_module.settings, password_field, ENV_PASSWORDS[password_field], raising=False
        )


def test_demo_seeding_is_disabled_without_environment_credentials(monkeypatch):
    clear_demo_settings(monkeypatch)

    assert auth_module.build_demo_user_seeds() == []


def test_demo_seeding_requires_every_credential(monkeypatch):
    configure_demo_settings(monkeypatch)
    monkeypatch.setattr(auth_module.settings, "DEMO_VIEWER_PASSWORD", None, raising=False)

    assert auth_module.build_demo_user_seeds() == []


def test_demo_seeding_uses_explicit_environment_values(monkeypatch):
    configure_demo_settings(monkeypatch)

    seeds = auth_module.build_demo_user_seeds()

    assert [seed["role"] for seed in seeds] == list(ROLES)
    assert [seed["email"] for seed in seeds] == [
        "demo0@example.test",
        "demo1@example.test",
        "demo2@example.test",
    ]
    for seed, (_, password_field) in zip(seeds, DEMO_FIELDS):
        assert "password" not in seed
        assert verify_password(ENV_PASSWORDS[password_field], seed["password_hash"])


def test_test_fixture_credentials_cannot_activate_runtime_seeding(monkeypatch):
    clear_demo_settings(monkeypatch)

    assert DEMO_CREDENTIALS
    assert auth_module.build_demo_user_seeds() == []


def test_runtime_auth_module_does_not_import_test_fixtures():
    source = Path(auth_module.__file__).read_text(encoding="utf-8")

    assert "backend.tests" not in source
    assert "DEMO_CREDENTIALS" not in source


def test_seeding_skips_database_access_when_unconfigured(monkeypatch):
    monkeypatch.setattr(auth_module, "build_demo_user_seeds", lambda: [])

    auth_module.ensure_demo_users_seeded(None)

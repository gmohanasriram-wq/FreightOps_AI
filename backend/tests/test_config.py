"""Configuration security tests: no default database credentials (Task GIT-002)."""
import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def _clear_db_environment(monkeypatch):
    for name in ("DATABASE_URL", "POSTGRES_USER", "POSTGRES_PASSWORD"):
        monkeypatch.delenv(name, raising=False)


def test_missing_database_configuration_is_rejected(monkeypatch):
    _clear_db_environment(monkeypatch)

    with pytest.raises(ValidationError) as excinfo:
        Settings(_env_file=None)

    assert "Database credentials are not configured" in str(excinfo.value)


def test_partial_database_credentials_are_rejected(monkeypatch):
    _clear_db_environment(monkeypatch)

    with pytest.raises(ValidationError):
        Settings(_env_file=None, POSTGRES_USER="app_user")


def test_database_url_alone_is_accepted_and_normalized():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://app_user:app_pass@db:5432/app_db",
    )

    assert (
        settings.SQLALCHEMY_DATABASE_URI
        == "postgresql+psycopg://app_user:app_pass@db:5432/app_db"
    )


def test_component_credentials_build_uri_without_env_file():
    settings = Settings(
        _env_file=None,
        POSTGRES_USER="app_user",
        POSTGRES_PASSWORD="app_pass",
        POSTGRES_SERVER="db",
        POSTGRES_PORT=5432,
        POSTGRES_DB="app_db",
    )

    assert (
        settings.SQLALCHEMY_DATABASE_URI
        == "postgresql+psycopg://app_user:app_pass@db:5432/app_db"
    )


def test_config_source_has_no_hardcoded_credential_defaults():
    source = (ROOT / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")

    for field in ("POSTGRES_USER", "POSTGRES_PASSWORD"):
        assert not re.search(
            rf'{field}:\s*(?:Optional\[str\]|str)\s*=\s*["\']', source
        ), f"{field} must not have a literal default"


def test_runtime_source_contains_no_literal_database_password():
    literal = re.compile(r"POSTGRES_PASSWORD=(?!<|\$|\{)\S")

    for path in (ROOT / "backend" / "app").rglob("*.py"):
        assert not literal.search(path.read_text(encoding="utf-8")), path


def test_alembic_ini_contains_no_connection_url():
    text = (ROOT / "alembic.ini").read_text(encoding="utf-8")
    url_lines = [
        line for line in text.splitlines() if line.strip().startswith("sqlalchemy.url")
    ]

    assert url_lines, "alembic.ini must still declare sqlalchemy.url"
    for line in url_lines:
        assert line.split("=", 1)[1].strip() == ""


def test_llm_defaults_are_offline_and_secret_free():
    settings = Settings(
        _env_file=None,
        DATABASE_URL="postgresql://app_user:app_pass@db:5432/app_db",
    )

    assert settings.LLM_PROVIDER == "offline"
    assert settings.LLM_DEMO_MODE is True
    assert settings.LLM_API_KEY is None
    assert settings.TOP_N_RECOMMENDATIONS == 5


def test_docker_compose_requires_database_credentials():
    text = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

    assert "POSTGRES_USER:-" not in text
    assert "POSTGRES_PASSWORD:-" not in text
    assert "${POSTGRES_USER:?" in text
    assert "${POSTGRES_PASSWORD:?" in text

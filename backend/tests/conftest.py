"""Pytest configuration: package path and isolated test users."""
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

# Add freightops-ai to sys.path
root_dir = Path(__file__).resolve().parent.parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))


@pytest.fixture(scope="session", autouse=True)
def seed_test_users():
    """Create test users independently of the application's demo-seeding config.

    Test fixtures never feed runtime configuration: the application only seeds
    demo users from DEMO_* environment settings.
    """
    from backend.app.core.security import hash_password
    from backend.app.db.session import SessionLocal
    from backend.app.models.user import User
    from backend.tests.helpers import DEMO_CREDENTIALS

    with SessionLocal() as db:
        for role, credentials in DEMO_CREDENTIALS.items():
            existing = db.execute(
                select(User).where(User.email == credentials["email"])
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    User(
                        id=uuid.uuid4(),
                        email=credentials["email"],
                        display_name=role.title(),
                        role=role,
                        password_hash=hash_password(credentials["password"]),
                        is_active=True,
                    )
                )
        db.commit()

    yield

"""Authentication and single-tenant RBAC dependencies (Contract 2.2 §3 & §5)."""
import uuid
from dataclasses import dataclass
from typing import Callable, List, Optional
from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.core.security import hash_password, verify_csrf_token
from backend.app.db.session import get_db
from backend.app.models.user import User


@dataclass(frozen=True)
class SessionRecord:
    """Server-side session state bound to one session token."""
    user_id: uuid.UUID
    csrf_token: str


# In-memory session store mapping session_token -> SessionRecord
_ACTIVE_SESSIONS: dict[str, SessionRecord] = {}

# Demo-user profiles. Passwords are supplied exclusively through environment
# settings; no literal credentials are stored in source.
DEMO_USER_SPECS = (
    {
        "role": "admin",
        "display_name": "Admin Operator",
        "email_setting": "DEMO_ADMIN_EMAIL",
        "password_setting": "DEMO_ADMIN_PASSWORD",
    },
    {
        "role": "broker",
        "display_name": "Demo Broker",
        "email_setting": "DEMO_BROKER_EMAIL",
        "password_setting": "DEMO_BROKER_PASSWORD",
    },
    {
        "role": "viewer",
        "display_name": "Read-Only Viewer",
        "email_setting": "DEMO_VIEWER_EMAIL",
        "password_setting": "DEMO_VIEWER_PASSWORD",
    },
)


def build_demo_user_seeds() -> List[dict]:
    """Build demo-user rows from explicit environment settings.

    Returns an empty list unless every role has both an email and a password
    configured. This deliberately provides no predictable password fallback.
    """
    seeds: List[dict] = []
    for spec in DEMO_USER_SPECS:
        email = getattr(settings, spec["email_setting"], None)
        password = getattr(settings, spec["password_setting"], None)
        if not email or not password:
            return []
        seeds.append(
            {
                "email": email,
                "display_name": spec["display_name"],
                "role": spec["role"],
                "password_hash": hash_password(password),
            }
        )
    return seeds


def ensure_demo_users_seeded(db: Session):
    """Seed demo users only when explicit demo credentials are configured."""
    seeds = build_demo_user_seeds()
    if not seeds:
        return

    existing = db.execute(select(User).limit(1)).scalar_one_or_none()
    if existing is not None:
        return

    for u in seeds:
        user_row = User(
            id=uuid.uuid4(),
            email=u["email"],
            display_name=u["display_name"],
            role=u["role"],
            password_hash=u["password_hash"],
            is_active=True,
        )
        db.add(user_row)
    db.commit()


def register_session(session_token: str, user_id: uuid.UUID, csrf_token: str):
    """Register an active session and bind its CSRF token server-side."""
    _ACTIVE_SESSIONS[session_token] = SessionRecord(user_id=user_id, csrf_token=csrf_token)


def revoke_session(session_token: Optional[str]):
    """Revoke a session token, if present."""
    if session_token:
        _ACTIVE_SESSIONS.pop(session_token, None)


def get_session_record(session_token: Optional[str]) -> Optional[SessionRecord]:
    """Return the server-side session record for a token, if active."""
    if not session_token:
        return None
    return _ACTIVE_SESSIONS.get(session_token)


def get_session_csrf_token(session_token: Optional[str]) -> Optional[str]:
    """Return the CSRF token bound to an active session, if any."""
    record = get_session_record(session_token)
    return record.csrf_token if record else None


def _request_session_token(request: Request) -> Optional[str]:
    """Extract the session token from the cookie or the X-Session-ID header."""
    return request.cookies.get("session_id") or request.headers.get("X-Session-ID")


async def get_current_user_optional(
    request: Request,
    db: Session = Depends(get_db),
) -> Optional[User]:
    """Retrieve the authenticated user from the server-side session, or None."""
    ensure_demo_users_seeded(db)

    record = get_session_record(_request_session_token(request))
    if record is not None:
        user = db.get(User, record.user_id)
        if user and user.is_active:
            return user

    return None


async def get_current_user(
    current_user: Optional[User] = Depends(get_current_user_optional),
) -> User:
    """Enforce that user is authenticated."""
    if current_user is None:
        raise FreightOpsHTTPException(
            status_code=401,
            code="ERR-002",
            title="Unauthenticated",
            detail="Missing, expired, or invalid session credentials. Please log in.",
        )
    return current_user


async def require_csrf(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> User:
    """Enforce a session-bound X-CSRF-Token on cookie-authenticated state-changing requests.

    Requests authenticated only by the X-Session-ID header are not cookie-based and
    therefore are not forgeable by a cross-site browser request; CSRF applies to the
    session cookie path.
    """
    session_token = request.cookies.get("session_id")
    if not session_token:
        return current_user

    expected = get_session_csrf_token(session_token)
    submitted = request.headers.get("X-CSRF-Token")
    if not verify_csrf_token(submitted, expected):
        raise FreightOpsHTTPException(
            status_code=403,
            code="ERR-003",
            title="Forbidden",
            detail="CSRF validation failed: missing, invalid, or mismatched X-CSRF-Token for the authenticated session.",
        )
    return current_user


async def require_csrf_for_ui(request: Request) -> None:
    """Enforce CSRF on authenticated browser form and HTMX state-changing routes.

    Anonymous requests keep their pre-existing UI behavior; once a session cookie is
    present, the submitted token must match that session's server-side token.
    """
    session_token = request.cookies.get("session_id")
    if not session_token:
        return

    submitted = request.headers.get("X-CSRF-Token")
    if not submitted:
        form = await request.form()
        form_value = form.get("csrf_token")
        submitted = form_value if isinstance(form_value, str) else None

    expected = get_session_csrf_token(session_token)
    if not verify_csrf_token(submitted, expected):
        raise FreightOpsHTTPException(
            status_code=403,
            code="ERR-003",
            title="Forbidden",
            detail="CSRF validation failed: missing, invalid, or mismatched token for the authenticated session.",
        )


def require_role(allowed_roles: List[str]) -> Callable:
    """Dependency factory checking if current user has an approved role."""
    def role_checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in allowed_roles:
            raise FreightOpsHTTPException(
                status_code=403,
                code="ERR-003",
                title="Forbidden",
                detail=f"User role '{user.role}' lacks sufficient permissions for this operation. Required: {allowed_roles}",
            )
        return user

    return role_checker

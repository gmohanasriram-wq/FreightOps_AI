"""Local session authentication endpoints per Contract 2.2 §3 & §5.1."""
from fastapi import APIRouter, Depends, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.auth import (
    ensure_demo_users_seeded,
    get_current_user,
    get_session_csrf_token,
    register_session,
    require_csrf,
    revoke_session,
)
from backend.app.core.config import settings
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.core.security import (
    generate_csrf_token,
    generate_session_token,
    verify_password,
)
from backend.app.db.session import get_db
from backend.app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class AuthUserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    csrf_token: str


@router.post(
    "/login",
    response_model=AuthUserResponse,
    summary="Authenticate local user, issue session cookie and CSRF token",
)
def login(
    payload: LoginRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """Authenticate with email and password."""
    ensure_demo_users_seeded(db)

    user = db.execute(select(User).where(User.email == payload.email)).scalar_one_or_none()
    if not user or not user.is_active or not verify_password(payload.password, user.password_hash):
        raise FreightOpsHTTPException(
            status_code=401,
            code="ERR-002",
            title="Invalid Credentials",
            detail="The email or password provided is incorrect.",
        )

    # Issue session token & CSRF token
    session_token = generate_session_token()
    csrf_token = generate_csrf_token()
    register_session(session_token, user.id, csrf_token)

    # Set HttpOnly session cookie
    response.set_cookie(
        key="session_id",
        value=session_token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )
    response.set_cookie(
        key="csrf_token",
        value=csrf_token,
        httponly=False,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )

    return AuthUserResponse(
        id=str(user.id),
        email=user.email,
        display_name=user.display_name,
        role=user.role,
        csrf_token=csrf_token,
    )


@router.get(
    "/me",
    response_model=AuthUserResponse,
    summary="Get current authenticated user profile",
)
def get_me(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return profile and the session-bound CSRF token for the active session."""
    session_token = request.cookies.get("session_id") or request.headers.get("X-Session-ID")
    return AuthUserResponse(
        id=str(current_user.id),
        email=current_user.email,
        display_name=current_user.display_name,
        role=current_user.role,
        csrf_token=get_session_csrf_token(session_token) or "",
    )


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Terminate active session",
)
def logout(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    _csrf: User = Depends(require_csrf),
):
    """Invalidate the server-side session, then clear session cookies."""
    session_token = request.cookies.get("session_id") or request.headers.get("X-Session-ID")
    revoke_session(session_token)
    response.delete_cookie("session_id", path="/")
    response.delete_cookie("csrf_token", path="/")
    return None

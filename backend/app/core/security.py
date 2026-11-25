"""Security primitives: password hashing, token generation, CSRF validation."""
import hashlib
import hmac
import os
import secrets
from typing import Optional, Tuple


def hash_password(password: str) -> str:
    """Hash password using PBKDF2-HMAC-SHA256 with random salt (Contract 2.2 §5.1)."""
    salt = secrets.token_hex(16)
    iterations = 100_000
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2:sha256:{iterations}${salt}${key.hex()}"


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify plain password against stored hash."""
    try:
        header, salt, key_hex = password_hash.split("$")
        algorithm, iterations_str = header.split(":")[-2], header.split(":")[-1]
        iterations = int(iterations_str)
        expected_key = hashlib.pbkdf2_hmac(
            algorithm,
            plain_password.encode("utf-8"),
            salt.encode("utf-8"),
            iterations,
        )
        return hmac.compare_digest(expected_key.hex(), key_hex)
    except Exception:
        return False


def generate_session_token() -> str:
    """Generate cryptographically secure session identifier."""
    return secrets.token_urlsafe(32)


def generate_csrf_token() -> str:
    """Generate CSRF protection token."""
    return secrets.token_hex(16)


def verify_csrf_token(submitted: Optional[str], expected: Optional[str]) -> bool:
    """Compare a submitted CSRF token against the server-side session token in constant time."""
    if not submitted or not expected:
        return False
    return hmac.compare_digest(submitted, expected)

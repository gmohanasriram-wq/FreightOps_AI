"""Idempotency management with atomic in-flight locking and 60-second lease (DEF-05 & Contract 2.2 §7.2)."""
import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, Tuple
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.errors import FreightOpsHTTPException
from backend.app.models.idempotency import IdempotencyKey

IDEMPOTENCY_LEASE_SECONDS = 60


def compute_request_hash(payload_str: str) -> str:
    """Compute deterministic SHA-256 hash of raw request payload."""
    return hashlib.sha256(payload_str.encode("utf-8")).hexdigest()


def check_and_acquire_idempotency_key(
    db: Session,
    key: str,
    endpoint: str,
    request_payload_str: str,
) -> Tuple[bool, Optional[int], Optional[Dict[str, Any]]]:
    """Check existing idempotency key.
    
    Returns:
        (is_cached, cached_status, cached_body)
        If is_cached is True, caller should return cached response immediately.
        If is_cached is False, caller proceeds with business logic and calls store_idempotency_result.
    Raises:
        FreightOpsHTTPException(409, 'ERR-006') if key is currently in-flight.
    """
    req_hash = compute_request_hash(request_payload_str)
    now = datetime.now(timezone.utc)

    existing = db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key)).scalar_one_or_none()

    if existing is not None:
        if existing.status == "completed":
            return True, existing.response_status, existing.response_body
        elif existing.status == "in_progress":
            lease_age = (now - existing.created_at).total_seconds()
            if lease_age < IDEMPOTENCY_LEASE_SECONDS:
                raise FreightOpsHTTPException(
                    status_code=409,
                    code="ERR-006",
                    title="Duplicate Request in Flight",
                    detail="A request with this Idempotency-Key is currently being processed. Please retry shortly.",
                )
            else:
                # Reclaim stale lease (DEF-05)
                existing.status = "in_progress"
                existing.request_hash = req_hash
                existing.created_at = now
                existing.expires_at = now + timedelta(hours=24)
                db.flush()
                return False, None, None
        else: # failed
            existing.status = "in_progress"
            existing.request_hash = req_hash
            existing.created_at = now
            existing.expires_at = now + timedelta(hours=24)
            db.flush()
            return False, None, None

    # New idempotency key
    new_entry = IdempotencyKey(
        key=key,
        endpoint=endpoint,
        request_hash=req_hash,
        status="in_progress",
        expires_at=now + timedelta(hours=24),
    )
    db.add(new_entry)
    db.flush()
    return False, None, None


def store_idempotency_result(
    db: Session,
    key: str,
    status_code: int,
    body: Dict[str, Any],
):
    """Mark idempotency key as completed with cached response body."""
    entry = db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key)).scalar_one_or_none()
    if entry:
        entry.status = "completed"
        entry.response_status = status_code
        entry.response_body = body
        db.flush()


def release_idempotency_on_error(
    db: Session,
    key: str,
):
    """Mark idempotency key as failed so it can be retried safely."""
    entry = db.execute(select(IdempotencyKey).where(IdempotencyKey.key == key)).scalar_one_or_none()
    if entry:
        entry.status = "failed"
        db.flush()

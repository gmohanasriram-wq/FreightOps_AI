"""Intake API endpoints per Contract 2.2 §5.1."""
import hashlib
import uuid
from typing import Optional
from fastapi import APIRouter, Depends, Header, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.auth import get_current_user, require_csrf, require_role
from backend.app.core.errors import FreightOpsHTTPException
from backend.app.db.session import get_db
from backend.app.models.shipment import IntakeSubmission, Shipment
from backend.app.models.user import User
from backend.app.schemas.intake import (
    IntakeSubmissionCreate,
    IntakeSubmissionDetailResponse,
    IntakeSubmissionResponse,
)
from backend.app.services.audit import emit_audit_event
from backend.app.services.idempotency import (
    check_and_acquire_idempotency_key,
    release_idempotency_on_error,
    store_idempotency_result,
)
from backend.app.services.llm_gateway import llm_gateway

router = APIRouter(prefix="/intake", tags=["intake"])

MAX_INTAKE_PAYLOAD_BYTES = 100 * 1024  # 100 KB limit per FR-013 / ERR-009


@router.post(
    "/submissions",
    response_model=IntakeSubmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Accept unstructured text via paste or structured JSON payload",
)
def create_intake_submission(
    payload: IntakeSubmissionCreate,
    request: Request,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    current_user: User = Depends(require_role(["broker", "admin"])),
    _csrf: User = Depends(require_csrf),
    db: Session = Depends(get_db),
):
    """Persist intake submission and create linked draft shipment (Contract 2.2 §5.1, DF-01)."""
    # 1. Enforce Idempotency-Key header requirement
    if not idempotency_key or not idempotency_key.strip():
        raise FreightOpsHTTPException(
            status_code=422,
            code="ERR-001",
            title="Missing Idempotency-Key",
            detail="The 'Idempotency-Key' request header is required for state-changing intake submissions.",
        )

    # 2. Enforce 100 KB payload limit
    raw_bytes = payload.raw_text.encode("utf-8")
    if len(raw_bytes) > MAX_INTAKE_PAYLOAD_BYTES:
        raise FreightOpsHTTPException(
            status_code=413,
            code="ERR-009",
            title="Payload Too Large",
            detail=f"Intake submission payload ({len(raw_bytes)} bytes) exceeds the 100 KB maximum limit.",
        )

    # 3. Check Idempotency Key in-flight locking and cache
    is_cached, cached_status, cached_body = check_and_acquire_idempotency_key(
        db=db,
        key=idempotency_key,
        endpoint="/api/v1/intake/submissions",
        request_payload_str=payload.raw_text,
    )
    if is_cached and cached_body:
        return IntakeSubmissionResponse(**cached_body)

    try:
        # 4. Content hashing for deduplication (FR-009)
        raw_hash = hashlib.sha256(raw_bytes).hexdigest()
        formatted_hash = f"sha256:{raw_hash}"

        # Check existing submission by content hash
        existing = db.execute(
            select(IntakeSubmission).where(IntakeSubmission.content_hash == formatted_hash)
        ).scalar_one_or_none()

        if existing is not None:
            resp_data = IntakeSubmissionResponse(
                submission_id=existing.id,
                channel=existing.channel,
                content_hash=existing.content_hash,
                shipment_id=existing.shipment_id,
                received_at=existing.received_at,
                parse_metadata=existing.parse_metadata,
            )
            store_idempotency_result(db, idempotency_key, 201, resp_data.model_dump(mode="json"))
            db.commit()
            return resp_data

        # 5. Persist IntakeSubmission first
        submission_id = uuid.uuid4()
        submission = IntakeSubmission(
            id=submission_id,
            channel=payload.channel,
            raw_text=payload.raw_text,
            content_hash=formatted_hash,
            idempotency_key=idempotency_key,
            submitter_id=current_user.id,
            shipment_id=None,
        )
        db.add(submission)
        db.flush()

        # Audit event 1: intake.received
        trace_id = request.headers.get("X-Trace-ID") or f"trace-{uuid.uuid4().hex[:12]}"
        emit_audit_event(
            db=db,
            event_type="intake.received",
            actor_type="user",
            actor_id=current_user.id,
            trace_id=trace_id,
            payload={"submission_id": str(submission_id), "channel": payload.channel},
        )

        # 6. LLM extraction attempt vs Approved Decision 1 fallback
        extraction_result = llm_gateway.extract_shipment_fields(payload.raw_text)

        # Create draft shipment (DEF-01 / CRIT-01 draft tolerance)
        shipment_id = uuid.uuid4()
        draft_shipment = Shipment(
            id=shipment_id,
            customer_id=payload.customer_id,
            status="draft",
            source="intake_submission",
            intake_submission_id=submission_id,
            currency="USD",
            version=1,
            requirements={},
            created_by=current_user.id,
        )

        parse_metadata = {
            "model": "fallback_manual",
            "extracted_fields": [],
            "status": "unparsed_draft",
        }

        if extraction_result:
            # If extraction is ever enabled and succeeds:
            draft_shipment.commodity = extraction_result.get("commodity")
            draft_shipment.equipment_type = extraction_result.get("equipment_type")
            draft_shipment.weight_lbs = extraction_result.get("weight_lbs")
            parse_metadata = {
                "model": "gemini-2.5-flash",
                "extracted_fields": list(extraction_result.keys()),
                "status": "parsed",
            }

        db.add(draft_shipment)
        db.flush()

        # Link circular foreign key: submission.shipment_id
        submission.shipment_id = shipment_id
        submission.parse_metadata = parse_metadata
        db.flush()

        # Audit event 2: shipment.created
        emit_audit_event(
            db=db,
            event_type="shipment.created",
            actor_type="user",
            actor_id=current_user.id,
            shipment_id=shipment_id,
            trace_id=trace_id,
            payload={
                "status": "draft",
                "source": payload.channel,
                "intake_submission_id": str(submission_id),
            },
        )

        # Audit event 3: intake.parsed
        emit_audit_event(
            db=db,
            event_type="intake.parsed",
            actor_type="system",
            actor_id=None,
            shipment_id=shipment_id,
            trace_id=trace_id,
            payload={"parse_metadata": parse_metadata},
        )

        resp = IntakeSubmissionResponse(
            submission_id=submission_id,
            channel=payload.channel,
            content_hash=formatted_hash,
            shipment_id=shipment_id,
            received_at=submission.received_at,
            parse_metadata=parse_metadata,
        )

        store_idempotency_result(db, idempotency_key, 201, resp.model_dump(mode="json"))
        db.commit()
        return resp

    except Exception:
        db.rollback()
        release_idempotency_on_error(db, idempotency_key)
        raise


@router.get(
    "/submissions/{submission_id}",
    response_model=IntakeSubmissionDetailResponse,
    summary="Retrieve raw submission text, extraction metadata, and linked shipment ID",
)
def get_intake_submission(
    submission_id: uuid.UUID,
    current_user: User = Depends(require_role(["viewer", "broker", "admin"])),
    db: Session = Depends(get_db),
):
    """Retrieve raw submission record."""
    submission = db.get(IntakeSubmission, submission_id)
    if not submission:
        raise FreightOpsHTTPException(
            status_code=404,
            code="ERR-004",
            title="Intake Submission Not Found",
            detail=f"Intake submission '{submission_id}' does not exist.",
        )
    return submission

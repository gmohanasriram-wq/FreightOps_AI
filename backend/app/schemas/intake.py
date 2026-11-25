"""Pydantic schemas for intake submissions (Contract 2.2 §5.1)."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class IntakeSubmissionCreate(BaseModel):
    """Payload for POST /api/v1/intake/submissions."""
    channel: Literal["paste", "upload", "rest_api", "manual"] = Field(
        default="paste",
        description="Intake channel identifier",
    )
    raw_text: str = Field(
        ...,
        min_length=1,
        description="Unstructured intake text content",
    )
    customer_id: Optional[uuid.UUID] = Field(
        default=None,
        description="Optional customer UUID reference",
    )
    client_request_id: Optional[str] = Field(
        default=None,
        description="Client tracking identifier",
    )


class IntakeSubmissionResponse(BaseModel):
    """Response returned upon successful intake creation."""
    submission_id: uuid.UUID
    channel: str
    content_hash: str
    shipment_id: uuid.UUID
    received_at: datetime
    parse_metadata: Optional[Dict[str, Any]] = None


class IntakeSubmissionDetailResponse(BaseModel):
    """Full intake submission detail response."""
    id: uuid.UUID
    channel: str
    raw_text: str
    content_hash: str
    idempotency_key: Optional[str]
    submitter_id: Optional[uuid.UUID]
    shipment_id: Optional[uuid.UUID]
    parse_metadata: Optional[Dict[str, Any]]
    extracted_at: Optional[datetime]
    extraction_error: Optional[str]
    received_at: datetime
    created_at: datetime

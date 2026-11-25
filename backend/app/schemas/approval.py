"""Pydantic schemas for approval resources (docs/09 §5.6)."""
import uuid
from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.recommendation import RecommendationCandidateResponse


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject", "request_changes"]
    comment: Optional[str] = Field(default=None, max_length=2000)


class ApprovalSummary(BaseModel):
    approval_id: uuid.UUID
    shipment_id: uuid.UUID
    recommendation_id: uuid.UUID
    workflow_execution_id: Optional[uuid.UUID] = None
    status: Literal["pending", "approved", "rejected", "changes_requested", "cancelled"]
    requested_by: Optional[uuid.UUID] = None
    requested_at: datetime
    decided_by: Optional[uuid.UUID] = None
    decided_at: Optional[datetime] = None
    decision_comment: Optional[str] = None
    selected_candidate_id: Optional[uuid.UUID] = None
    resumed_at: Optional[datetime] = None


class ApprovalListResponse(BaseModel):
    items: List[ApprovalSummary]
    total: int
    limit: int
    offset: int


class ApprovalDetailResponse(ApprovalSummary):
    recommendation_status: Optional[str] = None
    candidates: List[RecommendationCandidateResponse] = Field(default_factory=list)


class ApprovalDecisionResponse(BaseModel):
    approval_id: uuid.UUID
    status: Literal["approved", "rejected", "changes_requested"]
    decided_by: Optional[uuid.UUID] = None
    decided_at: datetime
    workflow_execution_id: uuid.UUID
    workflow_status: str
    workflow_outcome: Optional[str] = None
    booking_proposal_id: Optional[uuid.UUID] = None
    selected_candidate_id: Optional[uuid.UUID] = None

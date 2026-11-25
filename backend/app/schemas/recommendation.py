"""Pydantic schemas for recommendation resources (docs/09 §5.5)."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


ELIGIBILITY_VALUES = Literal["eligible", "ineligible", "insufficient_data"]
RECOMMENDATION_STATUS_VALUES = Literal[
    "pending",
    "computing",
    "ready",
    "no_eligible_carriers",
    "no_rankable_candidates",
    "failed",
    "superseded",
]


class RecommendationExplanationResponse(BaseModel):
    template: str
    narration: Optional[str] = None
    provider: Optional[str] = None


class RecommendationCandidateResponse(BaseModel):
    candidate_id: uuid.UUID
    carrier_id: uuid.UUID
    carrier_name: str
    mc_number: Optional[str] = None
    rank: Optional[int] = None
    eligibility_status: ELIGIBILITY_VALUES
    ineligibility_codes: List[str] = Field(default_factory=list)
    composite_score: Optional[float] = None
    component_scores: Dict[str, Optional[float]] = Field(default_factory=dict)
    lane_rate_used: Optional[float] = None


class RecommendationSummary(BaseModel):
    recommendation_id: uuid.UUID
    shipment_id: uuid.UUID
    workflow_execution_id: Optional[uuid.UUID] = None
    status: RECOMMENDATION_STATUS_VALUES
    scoring_config_version: int
    superseded_by_id: Optional[uuid.UUID] = None
    created_at: datetime


class RecommendationListResponse(BaseModel):
    items: List[RecommendationSummary]
    total: int


class RecommendationResponse(BaseModel):
    recommendation_id: uuid.UUID
    shipment_id: uuid.UUID
    workflow_execution_id: Optional[uuid.UUID] = None
    status: RECOMMENDATION_STATUS_VALUES
    scoring_config_id: uuid.UUID
    scoring_config_version: int
    superseded_by_id: Optional[uuid.UUID] = None
    explanation: RecommendationExplanationResponse
    candidates: List[RecommendationCandidateResponse]
    ineligible_candidates: List[RecommendationCandidateResponse]
    created_at: datetime

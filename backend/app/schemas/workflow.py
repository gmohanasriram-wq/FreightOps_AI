"""Pydantic schemas for workflow and recommendation-trigger endpoints (docs/09 §5.5, §5.9)."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class RecommendationTriggerRequest(BaseModel):
    """Request body for triggering a recommendation workflow.

    The MVP runs with the active scoring configuration and the configured top-N
    presentation limit. Supplying a different value is rejected rather than
    silently ignored.
    """
    scoring_config_id: Optional[uuid.UUID] = None
    top_n: Optional[int] = Field(default=None, ge=1, le=50)


class WorkflowTriggerResponse(BaseModel):
    """Response returned when a recommendation workflow is started or reused."""
    workflow_execution_id: uuid.UUID
    shipment_id: uuid.UUID
    status: Literal[
        "queued",
        "running",
        "waiting_for_human",
        "resumption_pending",
        "completed",
        "failed",
        "cancelled",
        "timed_out",
    ]


class WorkflowErrorResponse(BaseModel):
    code: str
    message: str
    node: Optional[str] = None
    retryable: bool = False


class WorkflowExecutionResponse(BaseModel):
    """Operator-facing workflow execution projection (docs/09 §5.9)."""
    workflow_execution_id: uuid.UUID
    shipment_id: uuid.UUID
    status: str
    current_node: Optional[str] = None
    outcome: Optional[str] = None
    interrupted: bool = False
    trace_id: str
    graph_version: str
    attempt_count: int
    max_attempt_count: int
    node_execution_count: int
    llm_call_count: int
    cumulative_compute_seconds: int
    recommendation_id: Optional[uuid.UUID] = None
    recommendation_status: Optional[str] = None
    approval_id: Optional[uuid.UUID] = None
    approval_status: Optional[str] = None
    booking_proposal_id: Optional[uuid.UUID] = None
    error: Optional[WorkflowErrorResponse] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    state: Dict[str, Any] = Field(default_factory=dict)

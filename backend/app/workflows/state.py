"""Canonical, validated workflow state (docs/07 §5).

The Pydantic model is used directly as the LangGraph state schema, so every
node boundary validates the full state and rejects unknown fields. Values are
JSON-safe because the same projection is stored in
``workflow_executions.state``.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

GRAPH_VERSION = "2.0"

NODE_NAMES = (
    "start_execution",
    "load_shipment",
    "validate_shipment",
    "decide_validation_outcome",
    "normalize_requirements",
    "resolve_carrier_candidates",
    "filter_eligible_carriers",
    "score_candidates",
    "generate_explanation",
    "persist_recommendation",
    "request_human_approval",
    "apply_human_decision",
    "create_booking_proposal",
    "record_audit_event",
    "finalize_execution",
    "handle_failure",
)

EXECUTION_STATUSES = (
    "queued",
    "running",
    "waiting_for_human",
    "resumption_pending",
    "completed",
    "failed",
    "cancelled",
    "timed_out",
)

OUTCOMES = (
    "approved",
    "rejected",
    "changes_requested",
    "no_eligible_carriers",
    "no_rankable_candidates",
    "failed",
    "cancelled",
    "timed_out",
)

TERMINAL_EXECUTION_STATUSES = ("completed", "failed", "cancelled", "timed_out")

TIMEOUT_ERROR_CODES = (
    "MAX_COMPUTE_BUDGET_EXCEEDED",
    "MAX_CONTINUOUS_ATTEMPT_EXCEEDED",
    "WORKFLOW_TIMED_OUT",
)


class WorkflowState(BaseModel):
    """Canonical workflow state documented in docs/07 §5."""

    model_config = ConfigDict(extra="forbid")

    execution_id: str
    shipment_id: str
    trace_id: str
    graph_version: str = GRAPH_VERSION
    status: str = "queued"
    current_node: Optional[str] = None

    validation_result: Optional[Dict[str, Any]] = None
    requirements_snapshot: Optional[Dict[str, Any]] = None
    candidate_carrier_ids: List[str] = Field(default_factory=list)
    eligibility_results: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    ranked_candidates: List[Dict[str, Any]] = Field(default_factory=list)
    scoring_config_id: Optional[str] = None
    scoring_config_version: Optional[int] = None

    recommendation_id: Optional[str] = None
    recommendation_status: Optional[str] = None
    explanation: Optional[Dict[str, Any]] = None

    approval_id: Optional[str] = None
    approval_status: Optional[str] = None
    selected_candidate_id: Optional[str] = None
    human_decision: Optional[Dict[str, Any]] = None
    booking_proposal_id: Optional[str] = None

    error: Optional[Dict[str, Any]] = None
    node_execution_count: int = 0
    llm_call_count: int = 0
    node_attempts: Dict[str, int] = Field(default_factory=dict)
    idempotency: Dict[str, str] = Field(default_factory=dict)
    started_at: Optional[str] = None
    attempt_started_at: Optional[str] = None
    outcome: Optional[str] = None

    @field_validator("status")
    @classmethod
    def _known_status(cls, value: str) -> str:
        if value not in EXECUTION_STATUSES:
            raise ValueError(f"unknown workflow status '{value}'")
        return value

    @field_validator("current_node")
    @classmethod
    def _known_node(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in NODE_NAMES:
            raise ValueError(f"unknown workflow node '{value}'")
        return value

    @field_validator("outcome")
    @classmethod
    def _known_outcome(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and value not in OUTCOMES:
            raise ValueError(f"unknown workflow outcome '{value}'")
        return value


def is_terminal(status: str) -> bool:
    return status in TERMINAL_EXECUTION_STATUSES

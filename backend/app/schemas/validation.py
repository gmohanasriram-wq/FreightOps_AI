"""Pydantic schemas for validation endpoints (Contract 2.2 §5.3)."""
import uuid
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel


class ValidationIssueResponse(BaseModel):
    """Individual issue finding."""
    rule_code: str
    severity: Literal["info", "warning", "error", "critical"]
    field: str
    message: str


class ValidationRunResponse(BaseModel):
    """Response returned from POST and GET /api/v1/shipments/{id}/validation."""
    validation_run_id: uuid.UUID
    shipment_id: uuid.UUID
    rules_version: str
    result: Literal["passed", "passed_with_warnings", "failed"]
    checked_at: datetime
    issues: List[ValidationIssueResponse]

"""Export all 21 canonical SQLAlchemy 2.x models for FreightOps AI per Contract 2.2."""
from backend.app.models.base import Base
from backend.app.models.user import User
from backend.app.models.customer import Customer
from backend.app.models.facility import Facility
from backend.app.models.carrier import (
    Carrier,
    CarrierEquipmentType,
    CarrierServiceRegion,
    CarrierAvailability,
    CarrierLaneRate,
)
from backend.app.models.shipment import (
    Shipment,
    ShipmentStop,
    IntakeSubmission,
    ValidationRun,
)
from backend.app.models.scoring import ScoringConfig
from backend.app.models.recommendation import (
    Recommendation,
    RecommendationCandidate,
)
from backend.app.models.approval import (
    Approval,
    BookingProposal,
)
from backend.app.models.workflow import (
    WorkflowExecution,
    LLMInvocation,
)
from backend.app.models.audit import AuditEvent
from backend.app.models.idempotency import IdempotencyKey

__all__ = [
    "Base",
    # 1. Identity & Commercial
    "User",
    "Customer",
    "Facility",
    # 2. Carrier Domain
    "Carrier",
    "CarrierEquipmentType",
    "CarrierServiceRegion",
    "CarrierAvailability",
    "CarrierLaneRate",
    # 3. Shipment Core Aggregate
    "Shipment",
    "ShipmentStop",
    "IntakeSubmission",
    "ValidationRun",
    # 4. Scoring & Recommendations
    "ScoringConfig",
    "Recommendation",
    "RecommendationCandidate",
    # 5. Approvals & Proposals
    "Approval",
    "BookingProposal",
    # 6. Workflow & Observability
    "WorkflowExecution",
    "LLMInvocation",
    "AuditEvent",
    "IdempotencyKey",
]

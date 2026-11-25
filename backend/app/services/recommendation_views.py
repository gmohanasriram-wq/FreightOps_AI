"""Read-side serialization for recommendation and approval resources.

Presentation only: every value comes from a persisted, deterministic record. No
carrier fact, score, rate, or performance claim is synthesized here.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.eligibility.engine import ELIGIBLE
from backend.app.models.carrier import Carrier
from backend.app.models.recommendation import Recommendation, RecommendationCandidate
from backend.app.schemas.recommendation import (
    RecommendationCandidateResponse,
    RecommendationExplanationResponse,
    RecommendationResponse,
    RecommendationSummary,
)
from backend.app.services.recommendations import COMPONENT_ORDER


def _number(value) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def serialize_candidate(
    candidate: RecommendationCandidate,
    carrier: Optional[Carrier],
) -> RecommendationCandidateResponse:
    stored = candidate.component_scores or {}
    components: Dict[str, Optional[float]] = {
        name: _number(stored.get(name)) for name in COMPONENT_ORDER
    }
    return RecommendationCandidateResponse(
        candidate_id=candidate.id,
        carrier_id=candidate.carrier_id,
        carrier_name=carrier.legal_name if carrier is not None else str(candidate.carrier_id),
        mc_number=carrier.mc_number if carrier is not None else None,
        rank=candidate.rank,
        eligibility_status=candidate.eligibility,
        ineligibility_codes=list(candidate.ineligibility_codes or []),
        composite_score=_number(candidate.total_score),
        component_scores=components,
        lane_rate_used=_number(candidate.rate_quote),
    )


def _ordered_candidates(
    db: Session, recommendation: Recommendation
) -> List[RecommendationCandidate]:
    rows = list(
        db.scalars(
            select(RecommendationCandidate).where(
                RecommendationCandidate.recommendation_id == recommendation.id
            )
        ).all()
    )
    rows.sort(
        key=lambda row: (
            row.rank is None,
            row.rank if row.rank is not None else 0,
            str(row.carrier_id),
        )
    )
    return rows


def _carriers(db: Session, candidates: List[RecommendationCandidate]) -> Dict:
    ids = {row.carrier_id for row in candidates}
    if not ids:
        return {}
    return {
        carrier.id: carrier
        for carrier in db.scalars(select(Carrier).where(Carrier.id.in_(ids))).all()
    }


def serialize_recommendation(
    db: Session, recommendation: Recommendation
) -> RecommendationResponse:
    rows = _ordered_candidates(db, recommendation)
    carrier_map = _carriers(db, rows)
    eligible: List[RecommendationCandidateResponse] = []
    excluded: List[RecommendationCandidateResponse] = []
    for row in rows:
        view = serialize_candidate(row, carrier_map.get(row.carrier_id))
        if row.eligibility == ELIGIBLE:
            eligible.append(view)
        else:
            excluded.append(view)

    return RecommendationResponse(
        recommendation_id=recommendation.id,
        shipment_id=recommendation.shipment_id,
        workflow_execution_id=recommendation.workflow_execution_id,
        status=recommendation.status,
        scoring_config_id=recommendation.scoring_config_id,
        scoring_config_version=recommendation.config_version,
        superseded_by_id=recommendation.superseded_by_id,
        explanation=RecommendationExplanationResponse(
            template=recommendation.explanation_template,
            narration=recommendation.explanation_narration,
            provider=recommendation.explanation_provider,
        ),
        candidates=eligible,
        ineligible_candidates=excluded,
        created_at=recommendation.created_at,
    )


def serialize_recommendation_summary(
    recommendation: Recommendation,
) -> RecommendationSummary:
    return RecommendationSummary(
        recommendation_id=recommendation.id,
        shipment_id=recommendation.shipment_id,
        workflow_execution_id=recommendation.workflow_execution_id,
        status=recommendation.status,
        scoring_config_version=recommendation.config_version,
        superseded_by_id=recommendation.superseded_by_id,
        created_at=recommendation.created_at,
    )

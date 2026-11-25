"""Recommendation persistence: score every evaluated candidate and rank them.

Persists one row per evaluated carrier (D-021), never only the top five. Rankable
candidates receive rank and total; eligible-unrankable candidates keep explicit
nulls (D-024). Recommendation status distinguishes zero eligible carriers from
eligible-but-zero-rankable outcomes (D-033 Option A).
"""
from __future__ import annotations

import uuid
from collections import Counter
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.domain.eligibility.engine import ELIGIBLE
from backend.app.domain.scoring.engine import (
    DEFAULT_WEIGHTS,
    score_and_rank,
    weights_from_config,
)
from backend.app.models.recommendation import Recommendation, RecommendationCandidate
from backend.app.models.scoring import ScoringConfig
from backend.app.models.shipment import Shipment, ShipmentStop
from backend.app.services.audit import emit_audit_event
from backend.app.services.candidate_evaluation import evaluate_all_candidates

READY = "ready"
NO_ELIGIBLE_CARRIERS = "no_eligible_carriers"
NO_RANKABLE_CANDIDATES = "no_rankable_candidates"
SUPERSEDED = "superseded"
TERMINAL_STATUSES = (READY, NO_ELIGIBLE_CARRIERS, NO_RANKABLE_CANDIDATES)

DEFERRED_COMPONENTS = ("lane_familiarity", "reliability")
COMPONENT_ORDER = (
    "equipment_fit",
    "lane_familiarity",
    "capacity_timing",
    "rate_competitiveness",
    "reliability",
    "data_completeness",
)


class ActiveScoringConfigMissing(RuntimeError):
    """Raised when no active scoring configuration exists."""


def get_active_scoring_config(db: Session) -> ScoringConfig:
    config = db.scalars(
        select(ScoringConfig)
        .where(ScoringConfig.is_active.is_(True))
        .order_by(ScoringConfig.version.desc())
    ).first()
    if config is None:
        raise ActiveScoringConfigMissing("no active scoring configuration is configured")
    return config


def _component_payload(
    components: Mapping[str, Optional[Decimal]],
) -> Dict[str, Optional[str]]:
    """Deterministic JSONB representation.

    Scored values are four-decimal strings so JSONB storage cannot lose Decimal
    precision. ``rate_competitiveness`` is explicit null when no usable rate or
    ceiling exists (never zero). Deferred components are explicit null and are
    distinguishable by their canonical deferred status, documented in docs/16.
    """
    payload: Dict[str, Optional[str]] = {}
    for name in COMPONENT_ORDER:
        if name in DEFERRED_COMPONENTS:
            payload[name] = None
            continue
        value = components.get(name)
        payload[name] = format(value, "f") if value is not None else None
    return payload


def _eligible_outcome_count(scored: Sequence[Mapping[str, Any]]) -> int:
    return sum(
        1
        for row in scored
        if row["evaluation"]["eligibility"].eligibility == ELIGIBLE
    )


def _reason_counts(scored: Sequence[Mapping[str, Any]]) -> List[tuple[str, int]]:
    counter: Counter[str] = Counter()
    for row in scored:
        for code in row["evaluation"]["eligibility"].ineligibility_codes:
            counter[code] += 1
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))


def build_explanation_template(
    scored: Sequence[Mapping[str, Any]],
    shipment_context: Mapping[str, Any],
    status: str,
    *,
    top_n: int = 5,
) -> str:
    """Build a factual template from deterministic results only.

    No on-time performance, reliability, historical, or commercial claim is
    introduced. Narration may later paraphrase this text but cannot extend it.
    """
    total = len(scored)
    eligible = _eligible_outcome_count(scored)
    rankable = sum(1 for row in scored if row["rank"] is not None)
    lane = "{origin} -> {destination}".format(
        origin=shipment_context.get("lane_origin") or "origin not recorded",
        destination=shipment_context.get("lane_destination") or "destination not recorded",
    )
    currency = shipment_context.get("currency") or "USD"

    if status == READY:
        parts = [
            f"{total} carriers evaluated for {lane}; "
            f"{eligible} passed all deterministic eligibility filters and "
            f"{rankable} were rankable."
        ]
        for row in sorted(
            (item for item in scored if item["rank"] is not None),
            key=lambda item: item["rank"],
        )[:top_n]:
            carrier = row["evaluation"]["carrier"]
            quote = row["evaluation"].get("rate_quote")
            parts.append(
                f"Rank {row['rank']}: {carrier['legal_name']} ({carrier['mc_number']}) "
                f"scored {format(row['total'], 'f')} with a recorded flat rate of "
                f"{format(quote, 'f') if quote is not None else 'unavailable'} {currency}."
            )
        return " ".join(parts)

    if status == NO_RANKABLE_CANDIDATES:
        reasons = _reason_counts(scored)
        reason_text = (
            "; ".join(f"{code}: {count}" for code, count in reasons)
            if reasons
            else "no exclusion codes recorded"
        )
        return (
            f"{total} carriers evaluated for {lane}; {eligible} passed all deterministic "
            f"eligibility filters, but none had both a usable flat lane rate and a maximum "
            f"buy rate, so no candidate was ranked. Eligibility exclusion counts: {reason_text}."
        )

    reasons = _reason_counts(scored)
    reason_text = (
        "; ".join(f"{code}: {count}" for code, count in reasons)
        if reasons
        else "no exclusion codes recorded"
    )
    return (
        f"{total} carriers evaluated for {lane}; none passed all deterministic eligibility "
        f"filters. Exclusion counts: {reason_text}."
    )


def _supersede_prior(
    db: Session,
    shipment: Shipment,
    replacement: Recommendation,
    *,
    actor_id: Optional[uuid.UUID],
    workflow_execution_id: Optional[uuid.UUID],
) -> List[uuid.UUID]:
    prior = list(
        db.scalars(
            select(Recommendation)
            .where(
                Recommendation.shipment_id == shipment.id,
                Recommendation.id != replacement.id,
                Recommendation.status.in_(TERMINAL_STATUSES),
            )
            .order_by(Recommendation.created_at)
        ).all()
    )
    superseded: List[uuid.UUID] = []
    for old in prior:
        old.status = SUPERSEDED
        old.superseded_by_id = replacement.id
        superseded.append(old.id)
        emit_audit_event(
            db,
            event_type="recommendation.superseded",
            actor_type="system",
            actor_id=actor_id,
            shipment_id=shipment.id,
            workflow_execution_id=workflow_execution_id,
            payload={
                "recommendation_id": str(old.id),
                "superseded_by_id": str(replacement.id),
            },
        )
    return superseded


def persist_recommendation(
    db: Session,
    shipment: Shipment,
    stops: Optional[Sequence[ShipmentStop]] = None,
    *,
    scoring_config: Optional[ScoringConfig] = None,
    workflow_execution_id: Optional[uuid.UUID] = None,
    created_by: Optional[uuid.UUID] = None,
    explanation_template: Optional[str] = None,
    explanation_narration: Optional[str] = None,
    explanation_provider: Optional[str] = None,
    candidate_explanations: Optional[Mapping[str, str]] = None,
    top_n: int = 5,
    supersede: bool = True,
) -> Recommendation:
    """Evaluate, score, rank, and persist a recommendation atomically.

    The caller owns the transaction. Every evaluated carrier is persisted.
    """
    if stops is None:
        stops = list(
            db.scalars(
                select(ShipmentStop)
                .where(ShipmentStop.shipment_id == shipment.id)
                .order_by(ShipmentStop.sequence)
            ).all()
        )
    evaluation = evaluate_all_candidates(db, shipment, stops)
    config = scoring_config or get_active_scoring_config(db)
    weights = weights_from_config(config.weights or DEFAULT_WEIGHTS)
    scored = score_and_rank(evaluation["candidates"], evaluation["context"], weights)

    eligible_count = _eligible_outcome_count(scored)
    rankable_count = sum(1 for row in scored if row["rank"] is not None)
    if eligible_count == 0:
        status = NO_ELIGIBLE_CARRIERS
    elif rankable_count == 0:
        status = NO_RANKABLE_CANDIDATES
    else:
        status = READY

    template = explanation_template or build_explanation_template(
        scored, evaluation["context"], status, top_n=top_n
    )
    recommendation = Recommendation(
        shipment_id=shipment.id,
        workflow_execution_id=workflow_execution_id,
        status=status,
        scoring_config_id=config.id,
        config_version=config.version,
        explanation_template=template,
        explanation_narration=explanation_narration,
        explanation_provider=explanation_provider,
        created_by=created_by,
    )
    db.add(recommendation)
    db.flush()

    for row in scored:
        candidate_evaluation = row["evaluation"]
        outcome = candidate_evaluation["eligibility"]
        is_eligible = outcome.eligibility == ELIGIBLE
        payload = _component_payload(row["components"]) if is_eligible else {}
        explanation = None
        if candidate_explanations:
            explanation = candidate_explanations.get(
                str(candidate_evaluation["carrier"]["id"])
            )
        db.add(
            RecommendationCandidate(
                recommendation_id=recommendation.id,
                carrier_id=uuid.UUID(str(candidate_evaluation["carrier"]["id"])),
                rank=row["rank"],
                eligibility=outcome.eligibility,
                ineligibility_codes=list(outcome.ineligibility_codes),
                component_scores=payload,
                total_score=row["total"],
                rate_quote=candidate_evaluation.get("rate_quote"),
                explanation=explanation,
            )
        )
    db.flush()

    if supersede:
        _supersede_prior(
            db,
            shipment,
            recommendation,
            actor_id=created_by,
            workflow_execution_id=workflow_execution_id,
        )

    emit_audit_event(
        db,
        event_type="recommendation.generated",
        actor_type="system",
        actor_id=created_by,
        shipment_id=shipment.id,
        workflow_execution_id=workflow_execution_id,
        payload={
            "recommendation_id": str(recommendation.id),
            "status": status,
            "evaluated_candidates": len(scored),
            "eligible_candidates": eligible_count,
            "rankable_candidates": rankable_count,
            "scoring_config_id": str(config.id),
            "config_version": config.version,
        },
    )
    return recommendation

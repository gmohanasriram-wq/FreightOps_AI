"""Recommendation persistence and lifecycle tests (D-021, D-024, D-033)."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.recommendation import Recommendation, RecommendationCandidate
from backend.app.models.shipment import Shipment
from backend.app.services.demo_seed import DEMO_SHIPMENT_IDS, seed_all_demo_data
from backend.app.services.recommendations import (
    NO_ELIGIBLE_CARRIERS,
    NO_RANKABLE_CANDIDATES,
    READY,
    SUPERSEDED,
    persist_recommendation,
)


def _persist(key):
    with SessionLocal() as db:
        seed_all_demo_data(db)
        shipment = db.get(Shipment, DEMO_SHIPMENT_IDS[key])
        recommendation = persist_recommendation(db, shipment)
        db.commit()
        return recommendation.id


def _load(recommendation_id):
    with SessionLocal() as db:
        recommendation = db.get(Recommendation, recommendation_id)
        candidates = list(
            db.scalars(
                select(RecommendationCandidate)
                .where(RecommendationCandidate.recommendation_id == recommendation_id)
                .order_by(RecommendationCandidate.rank.nulls_last(), RecommendationCandidate.carrier_id)
            ).all()
        )
        return recommendation, candidates


def test_ready_recommendation_persists_every_candidate_and_ranks_all_rankable():
    recommendation_id = _persist("ready")
    recommendation, candidates = _load(recommendation_id)

    assert recommendation.status == READY
    assert recommendation.explanation_template
    assert recommendation.config_version >= 1
    assert len(candidates) == 16

    ranked = [candidate for candidate in candidates if candidate.rank is not None]
    assert len(ranked) >= 2
    assert [candidate.rank for candidate in ranked] == list(range(1, len(ranked) + 1))
    # Rank 1 is the best composite, not merely the lowest quote; the demo's
    # Hazless carrier has the lowest rankable quote (2000.00) and complete data.
    assert ranked[0].rate_quote == Decimal("2000.00")
    assert all(candidate.total_score is not None for candidate in ranked)

    eligible_unrankable = [
        candidate
        for candidate in candidates
        if candidate.eligibility == "eligible" and candidate.rank is None
    ]
    assert eligible_unrankable
    for candidate in eligible_unrankable:
        assert candidate.total_score is None
        assert candidate.rate_quote is None or candidate.rate_quote >= 0
        # Explicit rate unavailability, never zero or a neutral score.
        assert candidate.component_scores["rate_competitiveness"] is None

    ineligible = [
        candidate for candidate in candidates if candidate.eligibility != "eligible"
    ]
    assert ineligible
    for candidate in ineligible:
        assert candidate.rank is None
        assert candidate.total_score is None
        assert candidate.component_scores == {}
        assert candidate.ineligibility_codes


def test_component_payload_is_four_decimal_and_marks_deferred_components_null():
    recommendation_id = _persist("ready")
    _, candidates = _load(recommendation_id)
    ranked = sorted(
        (candidate for candidate in candidates if candidate.rank is not None),
        key=lambda candidate: candidate.rank,
    )
    row = ranked[0].component_scores
    assert row["equipment_fit"] == "1.0000"
    assert row["capacity_timing"] == "1.0000"
    assert row["data_completeness"] == "1.0000"
    assert row["rate_competitiveness"] == "0.2308"
    assert row["lane_familiarity"] is None
    assert row["reliability"] is None


def test_total_equals_weighted_sum_of_stored_components():
    recommendation_id = _persist("ready")
    _, candidates = _load(recommendation_id)
    for candidate in candidates:
        if candidate.rank is None:
            continue
        stored = candidate.component_scores
        expected = (
            Decimal("0.30") * Decimal(stored["equipment_fit"])
            + Decimal("0.25") * Decimal(stored["capacity_timing"])
            + Decimal("0.30") * Decimal(stored["rate_competitiveness"])
            + Decimal("0.15") * Decimal(stored["data_completeness"])
        ).quantize(Decimal("0.0001"))
        assert candidate.total_score == expected


def test_all_ineligible_carriers_produce_no_eligible_carriers_status():
    recommendation_id = _persist("no_eligible")
    recommendation, candidates = _load(recommendation_id)
    assert recommendation.status == NO_ELIGIBLE_CARRIERS
    assert len(candidates) == 16
    assert all(candidate.eligibility != "eligible" for candidate in candidates)
    assert all(candidate.rank is None and candidate.total_score is None for candidate in candidates)
    assert "none passed all deterministic eligibility filters" in recommendation.explanation_template


def test_eligible_but_zero_rankable_produces_distinct_status_and_null_ranks():
    recommendation_id = _persist("unrankable")
    recommendation, candidates = _load(recommendation_id)
    assert recommendation.status == NO_RANKABLE_CANDIDATES
    eligible = [candidate for candidate in candidates if candidate.eligibility == "eligible"]
    assert eligible
    assert all(candidate.rank is None for candidate in candidates)
    assert all(candidate.total_score is None for candidate in candidates)
    assert all(candidate.component_scores["rate_competitiveness"] is None for candidate in eligible)
    assert "none had both a usable flat lane rate and a maximum buy rate" in recommendation.explanation_template


def test_hazmat_temperature_combo_still_produces_rankable_apex():
    recommendation_id = _persist("combo")
    recommendation, candidates = _load(recommendation_id)
    assert recommendation.status == READY
    apex = next(
        candidate
        for candidate in candidates
        if candidate.ineligibility_codes == [] and candidate.rank == 1
    )
    assert apex.rate_quote == Decimal("3100.00")
    summit = next(
        candidate
        for candidate in candidates
        if "hazmat_not_authorized" in candidate.ineligibility_codes
    )
    assert summit.rank is None


def test_new_recommendation_supersedes_prior_terminal_recommendation():
    with SessionLocal() as db:
        seed_all_demo_data(db)
        shipment = db.get(Shipment, DEMO_SHIPMENT_IDS["ready"])
        first = persist_recommendation(db, shipment)
        db.commit()
        first_id = first.id

        second = persist_recommendation(db, shipment)
        db.commit()
        second_id = second.id

    first_reloaded, _ = _load(first_id)
    second_reloaded, _ = _load(second_id)
    assert first_reloaded.status == SUPERSEDED
    assert first_reloaded.superseded_by_id == second_id
    assert second_reloaded.status == READY


def test_persistence_is_deterministic_for_identical_inputs():
    first_id = _persist("ready")
    second_id = _persist("ready")
    _, first = _load(first_id)
    _, second = _load(second_id)

    def signature(candidates):
        return [
            (
                str(candidate.carrier_id),
                candidate.rank,
                candidate.total_score,
                candidate.rate_quote,
                tuple(candidate.ineligibility_codes),
                candidate.component_scores,
            )
            for candidate in candidates
        ]

    assert signature(first) == signature(second)

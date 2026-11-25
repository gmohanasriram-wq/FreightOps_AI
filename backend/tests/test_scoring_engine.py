"""Deterministic scoring and ranking tests (Task 004-H)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.app.domain.scoring.engine import (
    COMPONENT_NAMES,
    capacity_timing,
    data_completeness,
    equipment_fit,
    rate_competitiveness,
    q4,
    score_and_rank,
    score_candidate,
    weights_from_config,
)

PICKUP_START = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)
PICKUP_END = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)


def carrier_snapshot(**overrides):
    base = {
        "id": "carrier-1",
        "mc_number": "MC-001",
        "dot_number": "DOT-001",
        "authority_status_recorded": "active",
        "insurance_expiry_date": "2027-12-01",
        "primary_contact_name": "Dispatch",
        "primary_contact_email": "dispatch@example.invalid",
        "primary_contact_phone": "555-0100",
        "equipment_types": [
            {
                "id": "eq-1",
                "equipment_type": "dry_van",
                "max_weight_lbs": 45000,
                "trailer_lengths_ft": [53, 48],
                "is_active": True,
            }
        ],
        "service_regions": [
            {"id": "r1", "region_type": "state", "region_value": "IL", "is_active": True}
        ],
        "availability": [
            {
                "id": "a1",
                "available_from": "2026-11-30T00:00:00+00:00",
                "available_until": "2026-12-05T23:59:00+00:00",
            }
        ],
        "lane_rates": [],
    }
    base.update(overrides)
    return base


def shipment_context(**overrides):
    base = {
        "equipment_type": "dry_van",
        "weight_lbs": 40000,
        "currency": "USD",
        "max_buy_rate": Decimal("3000.00"),
        "target_sell_rate": Decimal("3500.00"),
        "requirements": {},
        "pickup_start": PICKUP_START,
        "pickup_end": PICKUP_END,
    }
    base.update(overrides)
    return base


def evaluation(**overrides):
    base = {
        "carrier": carrier_snapshot(),
        "eligibility": SimpleNamespace(eligibility="eligible"),
        "matched_equipment": carrier_snapshot()["equipment_types"][0],
        "rate_selection": SimpleNamespace(usable=True, rate_quote=Decimal("2400.00")),
    }
    base.update(overrides)
    return base


def test_all_four_components_and_total_for_complete_rankable_candidate():
    result = score_candidate(evaluation(), shipment_context())
    assert result.components["equipment_fit"] == Decimal("1.0000")
    assert result.components["capacity_timing"] == Decimal("1.0000")
    assert result.components["rate_competitiveness"] == Decimal("0.2000")
    assert result.components["data_completeness"] == Decimal("1.0000")
    assert result.total == Decimal("0.7600")
    assert result.rankable is True


def test_equipment_fit_weights_capacity_ratio():
    shipment = shipment_context(weight_lbs=50000)
    score = equipment_fit(
        carrier_snapshot(),
        shipment,
        {"max_weight_lbs": 40000, "trailer_lengths_ft": [53]},
    )
    assert score == Decimal("0.8000")


def test_equipment_fit_trailer_requirement_must_match():
    matched = score_candidate(
        evaluation(),
        shipment_context(requirements={"trailer_length_ft": 53}),
    )
    assert matched.components["equipment_fit"] == Decimal("1.0000")

    mismatched = score_candidate(
        evaluation(),
        shipment_context(requirements={"trailer_length_ft": 57}),
    )
    # (weight ratio 1.0 + trailer 0.0) / 2
    assert mismatched.components["equipment_fit"] == Decimal("0.5000")


def test_equipment_fit_without_applicable_dimensions_is_one_and_documented():
    # No cargo weight and no trailer requirement: the verified equipment-type
    # match is the only applicable fit evidence. Missing data is still visible
    # through data_completeness.
    shipment = shipment_context(weight_lbs=None)
    score = equipment_fit(carrier_snapshot(), shipment, {"max_weight_lbs": 45000})
    assert score == Decimal("1.0000")


def test_capacity_timing_scores_fraction_of_window_covered():
    score = capacity_timing(
        carrier_snapshot(
            availability=[
                {
                    "id": "a-partial",
                    "available_from": "2026-12-01T10:00:00+00:00",
                    "available_until": "2026-12-05T23:59:00+00:00",
                }
            ]
        ),
        shipment_context(),
    )
    # Two of four hours covered.
    assert score == Decimal("0.5000")


def test_capacity_timing_uses_best_overlapping_window():
    score = capacity_timing(
        carrier_snapshot(
            availability=[
                {
                    "id": "a-partial",
                    "available_from": "2026-12-01T10:00:00+00:00",
                    "available_until": "2026-12-02T00:00:00+00:00",
                },
                {
                    "id": "a-full",
                    "available_from": "2026-11-30T00:00:00+00:00",
                    "available_until": "2026-12-05T00:00:00+00:00",
                },
            ]
        ),
        shipment_context(),
    )
    assert score == Decimal("1.0000")


def test_capacity_timing_boundary_touch_is_zero_not_an_invented_score():
    score = capacity_timing(
        carrier_snapshot(
            availability=[
                {
                    "id": "a-touch",
                    "available_from": "2026-12-01T12:00:00+00:00",
                    "available_until": "2026-12-05T00:00:00+00:00",
                }
            ]
        ),
        shipment_context(),
    )
    assert score == Decimal("0.0000")


def test_capacity_timing_missing_window_is_zero():
    assert capacity_timing(carrier_snapshot(), shipment_context(pickup_start=None)) == Decimal("0.0000")


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("2400.00", Decimal("0.2000")),
        ("3000.00", Decimal("0.0000")),
        ("3600.00", Decimal("0.0000")),
        ("1500.00", Decimal("0.5000")),
    ],
)
def test_rate_competitiveness_is_clamped_ratio_under_ceiling(quote, expected):
    score = rate_competitiveness(
        shipment_context(),
        {"usable": True, "rate_quote": Decimal(quote)},
    )
    assert score == expected


def test_rate_competitiveness_missing_rate_is_null_not_zero():
    assert rate_competitiveness(shipment_context(), None) is None
    assert (
        rate_competitiveness(
            shipment_context(), {"usable": False, "rate_quote": None}
        )
        is None
    )


def test_rate_competitiveness_missing_ceiling_is_null_not_zero():
    assert (
        rate_competitiveness(
            shipment_context(max_buy_rate=None),
            {"usable": True, "rate_quote": Decimal("2400.00")},
        )
        is None
    )


def test_rate_competitiveness_zero_ceiling_is_handled_without_division():
    assert (
        rate_competitiveness(
            shipment_context(max_buy_rate=Decimal("0")),
            {"usable": True, "rate_quote": Decimal("0")},
        )
        == Decimal("1.0000")
    )
    assert (
        rate_competitiveness(
            shipment_context(max_buy_rate=Decimal("0")),
            {"usable": True, "rate_quote": Decimal("1")},
        )
        == Decimal("0.0000")
    )


def test_data_completeness_penalizes_missing_recorded_fields():
    without_contact = carrier_snapshot(primary_contact_email=None)
    score = data_completeness(
        without_contact,
        shipment_context(),
        without_contact["equipment_types"][0],
    )
    assert score == Decimal("0.8750")


def test_data_completeness_blank_string_counts_as_missing():
    without_contact = carrier_snapshot(primary_contact_name="   ")
    score = data_completeness(
        without_contact,
        shipment_context(),
        without_contact["equipment_types"][0],
    )
    assert score == Decimal("0.8750")


def test_data_completeness_adds_required_trailer_dimension():
    carrier = carrier_snapshot()
    score = data_completeness(
        carrier,
        shipment_context(requirements={"trailer_length_ft": 53}),
        carrier["equipment_types"][0],
    )
    # 8 of 9 required facts present (no trailer-length field is missing here,
    # the matched equipment row has [53, 48], so all 9 are present).
    assert score == Decimal("1.0000")

    empty_trailers = dict(carrier["equipment_types"][0], trailer_lengths_ft=[])
    score = data_completeness(
        carrier,
        shipment_context(requirements={"trailer_length_ft": 53}),
        empty_trailers,
    )
    assert score == Decimal("0.8889")


def test_missing_usable_rate_makes_total_and_rank_null_and_keeps_component_null():
    result = score_candidate(
        evaluation(rate_selection=SimpleNamespace(usable=False, rate_quote=None)),
        shipment_context(),
    )
    assert result.components["rate_competitiveness"] is None
    assert result.total is None
    assert result.rankable is False


def test_missing_ceiling_makes_total_and_rank_null_not_renormalized():
    result = score_candidate(
        evaluation(),
        shipment_context(max_buy_rate=None),
    )
    assert result.components["rate_competitiveness"] is None
    assert result.total is None
    assert result.rankable is False
    # Other components remain available for the audit record.
    assert result.components["equipment_fit"] is not None


def test_ineligible_candidate_is_not_scored():
    result = score_candidate(
        evaluation(eligibility=SimpleNamespace(eligibility="ineligible")),
        shipment_context(),
    )
    assert result.components == {}
    assert result.total is None
    assert result.rankable is False


def test_zero_is_a_real_score_and_is_not_replaced_with_null():
    result = score_candidate(
        evaluation(rate_selection=SimpleNamespace(usable=True, rate_quote=Decimal("9000.00"))),
        shipment_context(),
    )
    assert result.components["rate_competitiveness"] == Decimal("0.0000")
    assert result.total is not None
    assert result.rankable is True


def test_total_is_computed_from_four_decimal_components_round_half_up():
    # trailer requirement hit + weight ratio 1.0 => equipment 1.0000
    # capacity 1/3 => 0.3333; rate 1/6 => 0.1667; data completeness 8/8 => 1.0000
    carrier = carrier_snapshot(
        availability=[
            {
                "id": "a-third",
                "available_from": "2026-12-01T08:00:00+00:00",
                "available_until": "2026-12-01T09:20:00+00:00",
            }
        ]
    )
    result = score_candidate(
        {
            "carrier": carrier,
            "eligibility": SimpleNamespace(eligibility="eligible"),
            "matched_equipment": carrier["equipment_types"][0],
            "rate_selection": SimpleNamespace(usable=True, rate_quote=Decimal("2500.00")),
        },
        shipment_context(),
    )
    assert result.components["capacity_timing"] == Decimal("0.3333")
    assert result.components["rate_competitiveness"] == Decimal("0.1667")
    expected = (
        Decimal("0.30") * Decimal("1.0000")
        + Decimal("0.25") * Decimal("0.3333")
        + Decimal("0.30") * Decimal("0.1667")
        + Decimal("0.15") * Decimal("1.0000")
    ).quantize(Decimal("0.0001"))
    assert result.total == expected


def test_ranking_orders_total_desc_then_carrier_id_asc_and_ranks_all_rankable():
    evaluations = [
        evaluation(carrier=carrier_snapshot(id="carrier-c")),
        evaluation(carrier=carrier_snapshot(id="carrier-a")),
        evaluation(carrier=carrier_snapshot(id="carrier-b")),
        evaluation(rate_selection=SimpleNamespace(usable=False, rate_quote=None)),
        evaluation(eligibility=SimpleNamespace(eligibility="ineligible")),
    ]
    # Different rates to create a deterministic total order.
    evaluations[0]["rate_selection"] = SimpleNamespace(usable=True, rate_quote=Decimal("2700.00"))
    evaluations[1]["rate_selection"] = SimpleNamespace(usable=True, rate_quote=Decimal("2400.00"))
    evaluations[2]["rate_selection"] = SimpleNamespace(usable=True, rate_quote=Decimal("2550.00"))

    ranked = score_and_rank(evaluations, shipment_context())
    ordered = sorted(
        [row for row in ranked if row["rank"] is not None],
        key=lambda row: row["rank"],
    )
    assert [row["evaluation"]["carrier"]["id"] for row in ordered] == [
        "carrier-a",
        "carrier-b",
        "carrier-c",
    ]
    assert [row["rank"] for row in ordered] == [1, 2, 3]
    assert all(row["rank"] is None for row in ranked if not row["rankable"])


def test_equal_totals_tie_break_on_carrier_id_ascending():
    evaluations = [
        evaluation(carrier=carrier_snapshot(id="carrier-z")),
        evaluation(carrier=carrier_snapshot(id="carrier-m")),
        evaluation(carrier=carrier_snapshot(id="carrier-a")),
    ]
    ranked = score_and_rank(evaluations, shipment_context())
    ordered = sorted(
        [row for row in ranked if row["rank"] is not None],
        key=lambda row: row["rank"],
    )
    assert [row["evaluation"]["carrier"]["id"] for row in ordered] == [
        "carrier-a",
        "carrier-m",
        "carrier-z",
    ]


def test_weights_from_config_parses_strings_and_defaults_missing_components():
    weights = weights_from_config({"equipment_fit": "0.4", "rate_competitiveness": "0.2"})
    assert weights["equipment_fit"] == Decimal("0.4")
    assert weights["rate_competitiveness"] == Decimal("0.2")
    assert weights["capacity_timing"] == Decimal("0.25")
    assert weights["data_completeness"] == Decimal("0.15")
    assert tuple(weights) == COMPONENT_NAMES


def test_custom_weights_change_total_without_renormalization():
    weights = {name: Decimal("0.25") for name in COMPONENT_NAMES}
    result = score_candidate(evaluation(), shipment_context(), weights)
    # 0.25 * (1.0 + 1.0 + 0.2 + 1.0) = 0.8
    assert result.total == Decimal("0.8000")


def test_q4_uses_round_half_up():
    assert q4(Decimal("0.12345")) == Decimal("0.1235")
    assert q4(Decimal("0.12344")) == Decimal("0.1234")

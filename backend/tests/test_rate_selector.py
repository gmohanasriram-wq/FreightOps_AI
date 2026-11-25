"""Lane-rate selection unit tests for D-022 through D-026."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from backend.app.domain.rates.selector import (
    CURRENCY_MISMATCH,
    INCOMPLETE_INPUT,
    NO_FLAT_RATE,
    NO_MATCHING_RATE,
    NOT_EFFECTIVE,
    select_lane_rate,
)

PICKUP = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)


def rate(**overrides):
    base = {
        "id": "rate-1",
        "origin_region": "Chicago, IL",
        "destination_region": "Dallas, TX",
        "equipment_type": "dry_van",
        "flat_rate": "2450.00",
        "rate_per_mile": None,
        "min_rate": None,
        "currency": "USD",
        "effective_date": "2026-11-01",
        "expiration_date": "2026-12-31",
        "is_active": True,
    }
    base.update(overrides)
    return base


def select(rates, **overrides):
    params = {
        "lane_origin": "Chicago, IL",
        "lane_destination": "Dallas, TX",
        "equipment_type": "dry_van",
        "shipment_currency": "USD",
        "pickup_start": PICKUP,
    }
    params.update(overrides)
    return select_lane_rate({"lane_rates": rates}, **params)


def test_selects_exact_active_flat_rate():
    result = select([rate()])
    assert result.usable is True
    assert result.rate_quote == Decimal("2450.00")
    assert result.rate_id == "rate-1"


def test_lane_matching_is_normalized_whitespace_and_case():
    result = select([rate(origin_region="  chicago,   il ", destination_region="DALLAS, TX")])
    assert result.usable is True


def test_inactive_rate_is_ignored():
    result = select([rate(is_active=False)])
    assert result.usable is False
    assert result.reason == NO_MATCHING_RATE


def test_wrong_equipment_is_not_used():
    result = select([rate(equipment_type="reefer")])
    assert result.usable is False
    assert result.reason == NO_MATCHING_RATE


def test_wrong_destination_is_not_used():
    result = select([rate(destination_region="Austin, TX")])
    assert result.usable is False
    assert result.reason == NO_MATCHING_RATE


def test_currency_mismatch_is_not_used_and_no_fx_occurs():
    result = select([rate(currency="EUR")])
    assert result.usable is False
    assert result.reason == CURRENCY_MISMATCH


def test_per_mile_only_rate_is_not_usable():
    result = select([rate(flat_rate=None, rate_per_mile="2.10")])
    assert result.usable is False
    assert result.reason == NO_FLAT_RATE


def test_min_rate_is_metadata_only():
    result = select([rate(min_rate="9999.00")])
    assert result.usable is True
    assert result.rate_quote == Decimal("2450.00")


def test_rate_not_yet_effective_is_not_used():
    result = select([rate(effective_date="2026-12-02")])
    assert result.usable is False
    assert result.reason == NOT_EFFECTIVE


def test_expired_rate_is_not_used():
    result = select([rate(expiration_date="2026-11-30")])
    assert result.usable is False
    assert result.reason == NOT_EFFECTIVE


def test_effective_and_expiration_boundaries_are_inclusive():
    result = select([rate(effective_date="2026-12-01", expiration_date="2026-12-01")])
    assert result.usable is True


def test_missing_pickup_window_is_incomplete_input():
    result = select([rate()], pickup_start=None)
    assert result.usable is False
    assert result.reason == INCOMPLETE_INPUT


def test_naive_pickup_is_interpreted_as_utc():
    result = select([rate()], pickup_start=datetime(2026, 12, 1, 8))
    assert result.usable is True


def test_deterministic_tie_break_lowest_flat_then_id():
    result = select(
        [
            rate(id="rate-b", flat_rate="2500.00"),
            rate(id="rate-a", flat_rate="2400.00"),
        ]
    )
    assert result.rate_id == "rate-a"
    assert result.rate_quote == Decimal("2400.00")

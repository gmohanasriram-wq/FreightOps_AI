"""Eligibility engine unit tests for all seven hard filters and precedence."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timezone

import pytest

from backend.app.domain.eligibility.engine import (
    CARRIER_INACTIVE,
    CARRIER_SUSPENDED,
    EQUIPMENT_MISMATCH,
    HAZMAT_NOT_AUTHORIZED,
    INSURANCE_EXPIRED,
    INELIGIBLE,
    INSUFFICIENT_DATA,
    MISSING_DATA,
    NO_CAPACITY,
    REGION_NOT_SERVED,
    TEMPERATURE_NOT_SUPPORTED,
    ELIGIBLE,
    evaluate_carrier,
)

PICKUP_START = datetime(2026, 12, 1, 8, tzinfo=timezone.utc)
PICKUP_END = datetime(2026, 12, 1, 12, tzinfo=timezone.utc)


def carrier_snapshot(**overrides):
    base = {
        "id": "carrier-1",
        "status": "active",
        "insurance_expiry_date": "2027-12-01",
        "hazmat_authorized": False,
        "temperature_capable": False,
        "equipment_types": [
            {
                "id": "eq-1",
                "equipment_type": "dry_van",
                "max_weight_lbs": 45000,
                "trailer_lengths_ft": [53],
                "is_active": True,
            }
        ],
        "service_regions": [
            {"id": "r1", "region_type": "state", "region_value": "IL", "is_active": True},
            {"id": "r2", "region_type": "state", "region_value": "TX", "is_active": True},
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
        "origin_state": "IL",
        "destination_state": "TX",
        "pickup_start": PICKUP_START,
        "pickup_end": PICKUP_END,
        "requirements": {},
    }
    base.update(overrides)
    return base


def test_eligible_when_all_filters_pass():
    outcome = evaluate_carrier(carrier_snapshot(), shipment_context())
    assert outcome.eligibility == ELIGIBLE
    assert outcome.ineligibility_codes == ()
    assert outcome.missing_data is False
    assert outcome.matched_equipment["id"] == "eq-1"


def test_equipment_mismatch_is_ineligible():
    carrier = carrier_snapshot(
        equipment_types=[
            {
                "id": "eq-reefer",
                "equipment_type": "reefer",
                "max_weight_lbs": 44000,
                "trailer_lengths_ft": [53],
                "is_active": True,
            }
        ]
    )
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (EQUIPMENT_MISMATCH,)


def test_no_active_equipment_rows_is_insufficient_data():
    carrier = carrier_snapshot(equipment_types=[])
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INSUFFICIENT_DATA
    assert outcome.ineligibility_codes == (MISSING_DATA,)
    assert outcome.missing_data is True


def test_inactive_equipment_row_is_unknown_not_mismatch():
    carrier = carrier_snapshot(
        equipment_types=[
            {
                "id": "eq-inactive",
                "equipment_type": "dry_van",
                "max_weight_lbs": 45000,
                "trailer_lengths_ft": [53],
                "is_active": False,
            }
        ]
    )
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INSUFFICIENT_DATA
    assert outcome.ineligibility_codes == (MISSING_DATA,)


def test_region_not_served_when_active_rows_exist_but_do_not_cover_lane():
    carrier = carrier_snapshot(
        service_regions=[
            {"id": "r1", "region_type": "state", "region_value": "TX", "is_active": True}
        ]
    )
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (REGION_NOT_SERVED,)


def test_no_active_service_regions_is_insufficient_data():
    carrier = carrier_snapshot(service_regions=[])
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INSUFFICIENT_DATA
    assert outcome.ineligibility_codes == (MISSING_DATA,)


def test_no_availability_rows_is_no_capacity():
    carrier = carrier_snapshot(availability=[])
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (NO_CAPACITY,)


def test_non_overlapping_availability_is_no_capacity():
    carrier = carrier_snapshot(
        availability=[
            {
                "id": "a-late",
                "available_from": "2026-12-10T00:00:00+00:00",
                "available_until": "2026-12-20T00:00:00+00:00",
            }
        ]
    )
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (NO_CAPACITY,)


def test_availability_boundary_touch_is_inclusive_overlap():
    carrier = carrier_snapshot(
        availability=[
            {
                "id": "a-boundary",
                "available_from": PICKUP_END,
                "available_until": PICKUP_END,
            }
        ]
    )
    outcome = evaluate_carrier(carrier, shipment_context())
    # CHECK constraint prevents equal from/until in the database, but the
    # engine's inclusive comparison must still treat a touching window as overlap.
    assert outcome.eligibility == ELIGIBLE


def test_null_insurance_is_insufficient_data():
    carrier = carrier_snapshot(insurance_expiry_date=None)
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INSUFFICIENT_DATA
    assert outcome.ineligibility_codes == (MISSING_DATA,)


def test_insurance_expiry_equal_to_pickup_date_is_valid():
    carrier = carrier_snapshot(insurance_expiry_date="2026-12-01")
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == ELIGIBLE


def test_insurance_expired_before_pickup_date_is_ineligible():
    carrier = carrier_snapshot(insurance_expiry_date="2026-11-30")
    outcome = evaluate_carrier(carrier, shipment_context())
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (INSURANCE_EXPIRED,)


@pytest.mark.parametrize(
    ("status", "code"),
    [("inactive", CARRIER_INACTIVE), ("suspended", CARRIER_SUSPENDED)],
)
def test_carrier_status_failures(status, code):
    outcome = evaluate_carrier(carrier_snapshot(status=status), shipment_context())
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (code,)


def test_hazmat_filter_applies_only_when_required():
    not_required = evaluate_carrier(
        carrier_snapshot(hazmat_authorized=False),
        shipment_context(requirements={"hazmat": False}),
    )
    assert not_required.eligibility == ELIGIBLE

    required = evaluate_carrier(
        carrier_snapshot(hazmat_authorized=False),
        shipment_context(requirements={"hazmat": True}),
    )
    assert required.eligibility == INELIGIBLE
    assert required.ineligibility_codes == (HAZMAT_NOT_AUTHORIZED,)


def test_temperature_filter_applies_only_with_numeric_bound():
    no_bound = evaluate_carrier(
        carrier_snapshot(temperature_capable=False),
        shipment_context(requirements={"temperature_range": {"min_f": None, "max_f": None}}),
    )
    assert no_bound.eligibility == ELIGIBLE

    required = evaluate_carrier(
        carrier_snapshot(temperature_capable=False),
        shipment_context(requirements={"temperature_range": {"min_f": 34.0}}),
    )
    assert required.eligibility == INELIGIBLE
    assert required.ineligibility_codes == (TEMPERATURE_NOT_SUPPORTED,)


def test_precedence_keeps_all_failures_and_adds_missing_data():
    carrier = carrier_snapshot(
        equipment_types=[],
        service_regions=[
            {"id": "r1", "region_type": "state", "region_value": "TX", "is_active": True}
        ],
        availability=[],
        insurance_expiry_date=None,
        status="inactive",
        hazmat_authorized=False,
        temperature_capable=False,
    )
    outcome = evaluate_carrier(
        carrier,
        shipment_context(
            requirements={"hazmat": True, "temperature_range": {"max_f": 0.0}}
        ),
    )
    assert outcome.eligibility == INELIGIBLE
    assert outcome.ineligibility_codes == (
        REGION_NOT_SERVED,
        NO_CAPACITY,
        CARRIER_INACTIVE,
        HAZMAT_NOT_AUTHORIZED,
        TEMPERATURE_NOT_SUPPORTED,
        MISSING_DATA,
    )
    assert outcome.failure_codes == (
        REGION_NOT_SERVED,
        NO_CAPACITY,
        CARRIER_INACTIVE,
        HAZMAT_NOT_AUTHORIZED,
        TEMPERATURE_NOT_SUPPORTED,
    )


def test_missing_pickup_window_is_missing_data():
    outcome = evaluate_carrier(
        carrier_snapshot(), shipment_context(pickup_start=None, pickup_end=None)
    )
    assert outcome.eligibility == INSUFFICIENT_DATA
    assert outcome.ineligibility_codes == (MISSING_DATA,)

"""Deterministic eligibility engine (D-027 through D-032).

Pure functions only: no database access, no network, no LLM. Every carrier in the
broad candidate universe is evaluated against exactly seven hard filters. The
engine never removes a carrier and never invents missing carrier facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

ELIGIBLE = "eligible"
INELIGIBLE = "ineligible"
INSUFFICIENT_DATA = "insufficient_data"

EQUIPMENT_MISMATCH = "equipment_mismatch"
REGION_NOT_SERVED = "region_not_served"
NO_CAPACITY = "no_capacity"
INSURANCE_EXPIRED = "insurance_expired"
CARRIER_INACTIVE = "carrier_inactive"
CARRIER_SUSPENDED = "carrier_suspended"
HAZMAT_NOT_AUTHORIZED = "hazmat_not_authorized"
TEMPERATURE_NOT_SUPPORTED = "temperature_not_supported"
MISSING_DATA = "missing_data"

# Canonical Appendix A.2 ordering.
CANONICAL_CODE_ORDER: Tuple[str, ...] = (
    EQUIPMENT_MISMATCH,
    REGION_NOT_SERVED,
    NO_CAPACITY,
    INSURANCE_EXPIRED,
    CARRIER_INACTIVE,
    CARRIER_SUSPENDED,
    HAZMAT_NOT_AUTHORIZED,
    TEMPERATURE_NOT_SUPPORTED,
    MISSING_DATA,
)
ORDER_INDEX = {code: index for index, code in enumerate(CANONICAL_CODE_ORDER)}

STATUS_PASSED = "passed"
STATUS_FAILED = "failed"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class EligibilityOutcome:
    eligibility: str
    ineligibility_codes: Tuple[str, ...] = ()
    failure_codes: Tuple[str, ...] = ()
    missing_data: bool = False
    filter_results: Mapping[str, str] = field(default_factory=dict)
    matched_equipment: Optional[Mapping[str, Any]] = None


def canonical_codes(codes: Iterable[str]) -> Tuple[str, ...]:
    """Deduplicate codes and return them in canonical Appendix A.2 order."""
    return tuple(sorted(set(codes), key=lambda code: ORDER_INDEX.get(code, 999)))


def _as_utc(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _parse_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _active(rows: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
    return [row for row in rows if bool(row.get("is_active", True))]


def _requires_hazmat(requirements: Mapping[str, Any]) -> bool:
    return requirements.get("hazmat") is True


def _temperature_required(requirements: Mapping[str, Any]) -> bool:
    temp_range = requirements.get("temperature_range")
    if not isinstance(temp_range, Mapping):
        return False
    return _decimal(temp_range.get("min_f")) is not None or _decimal(
        temp_range.get("max_f")
    ) is not None


class _Accumulator:
    def __init__(self) -> None:
        self.failures: set[str] = set()
        self.unknown = False
        self.filter_results: Dict[str, str] = {}

    def fail(self, filter_name: str, code: str) -> None:
        self.failures.add(code)
        self.filter_results[filter_name] = STATUS_FAILED

    def miss(self, filter_name: str) -> None:
        self.unknown = True
        self.filter_results[filter_name] = STATUS_UNKNOWN

    def passed(self, filter_name: str) -> None:
        self.filter_results[filter_name] = STATUS_PASSED

    def not_applicable(self, filter_name: str) -> None:
        self.filter_results[filter_name] = STATUS_NOT_APPLICABLE


def evaluate_carrier(
    carrier: Mapping[str, Any],
    shipment: Mapping[str, Any],
) -> EligibilityOutcome:
    """Evaluate one carrier against all seven hard filters.

    ``carrier`` is a serialized carrier snapshot; ``shipment`` is a shipment
    context containing ``equipment_type``, ``lane_origin``, ``lane_destination``,
    ``requirements``, and the first pickup ``pickup_start`` / ``pickup_end``.
    """
    acc = _Accumulator()
    requirements = shipment.get("requirements") or {}
    if not isinstance(requirements, Mapping):
        requirements = {}

    equipment_rows = list(carrier.get("equipment_types") or [])
    active_equipment = _active(equipment_rows)
    requested_equipment = shipment.get("equipment_type")
    matched_equipment: Optional[Mapping[str, Any]] = None

    # 1. Equipment hard filter.
    if not requested_equipment:
        acc.miss("equipment")
    elif not active_equipment:
        # D-028: no active relationship rows means unknown, not a mismatch.
        acc.miss("equipment")
    else:
        matches = [
            row for row in active_equipment if row.get("equipment_type") == requested_equipment
        ]
        if not matches:
            acc.fail("equipment", EQUIPMENT_MISMATCH)
        else:
            matched_equipment = sorted(
                matches,
                key=lambda row: (
                    -(int(row.get("max_weight_lbs") or 0)),
                    str(row.get("id") or ""),
                ),
            )[0]
            acc.passed("equipment")

    # 2. Service-region hard filter. MVP supports state rows; non-state rows are
    # retained as recorded facts but do not prove state coverage.
    region_rows = _active(carrier.get("service_regions") or [])
    origin_state = shipment.get("origin_state")
    destination_state = shipment.get("destination_state")
    if not origin_state or not destination_state:
        acc.miss("service_region")
    elif not region_rows:
        acc.miss("service_region")
    else:
        served_states = {
            str(row.get("region_value") or "").strip().upper()
            for row in region_rows
            if row.get("region_type") == "state"
        }
        if (
            str(origin_state).strip().upper() not in served_states
            or str(destination_state).strip().upper() not in served_states
        ):
            acc.fail("service_region", REGION_NOT_SERVED)
        else:
            acc.passed("service_region")

    # 3. Capacity / availability hard filter (D-031).
    pickup_start = _as_utc(shipment.get("pickup_start"))
    pickup_end = _as_utc(shipment.get("pickup_end")) or pickup_start
    availability_rows = list(carrier.get("availability") or [])
    if pickup_start is None:
        acc.miss("capacity")
    elif not availability_rows:
        acc.fail("capacity", NO_CAPACITY)
    else:
        overlapping = False
        for row in availability_rows:
            available_from = _as_utc(row.get("available_from"))
            available_until = _as_utc(row.get("available_until"))
            if available_from is None or available_until is None:
                continue
            # Inclusive any-overlap on the first pickup window.
            if available_from <= pickup_end and available_until >= pickup_start:
                overlapping = True
                break
        if overlapping:
            acc.passed("capacity")
        else:
            acc.fail("capacity", NO_CAPACITY)

    # 4. Insurance validity hard filter (D-032).
    insurance_expiry = _parse_date(carrier.get("insurance_expiry_date"))
    if pickup_start is None:
        acc.miss("insurance")
    elif insurance_expiry is None:
        acc.miss("insurance")
    elif insurance_expiry < pickup_start.date():
        acc.fail("insurance", INSURANCE_EXPIRED)
    else:
        acc.passed("insurance")

    # 5. Carrier status hard filter.
    status = carrier.get("status")
    if status == "active":
        acc.passed("carrier_status")
    elif status == "inactive":
        acc.fail("carrier_status", CARRIER_INACTIVE)
    elif status == "suspended":
        acc.fail("carrier_status", CARRIER_SUSPENDED)
    else:
        acc.miss("carrier_status")

    # 6. Hazmat hard filter (D-030: only when explicitly required).
    if not _requires_hazmat(requirements):
        acc.not_applicable("hazmat")
    elif not bool(carrier.get("hazmat_authorized")):
        acc.fail("hazmat", HAZMAT_NOT_AUTHORIZED)
    else:
        acc.passed("hazmat")

    # 7. Temperature hard filter (D-030: only when a numeric bound exists).
    if not _temperature_required(requirements):
        acc.not_applicable("temperature")
    elif not bool(carrier.get("temperature_capable")):
        acc.fail("temperature", TEMPERATURE_NOT_SUPPORTED)
    else:
        acc.passed("temperature")

    failure_codes = canonical_codes(acc.failures)
    all_codes = canonical_codes(set(failure_codes) | ({MISSING_DATA} if acc.unknown else set()))

    if failure_codes:
        eligibility = INELIGIBLE
    elif acc.unknown:
        eligibility = INSUFFICIENT_DATA
    else:
        eligibility = ELIGIBLE

    return EligibilityOutcome(
        eligibility=eligibility,
        ineligibility_codes=all_codes,
        failure_codes=failure_codes,
        missing_data=acc.unknown,
        filter_results=dict(acc.filter_results),
        matched_equipment=matched_equipment,
    )

"""Deterministic lane-rate selection (D-022 through D-026)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping, Optional, Sequence, Tuple

NO_MATCHING_RATE = "no_matching_rate"
NO_FLAT_RATE = "no_flat_rate"
NOT_EFFECTIVE = "not_effective"
CURRENCY_MISMATCH = "currency_mismatch"
INCOMPLETE_INPUT = "incomplete_input"
SELECTED = "selected"

_WHITESPACE = re.compile(r"\s+")


def normalize_lane(value: Optional[str]) -> str:
    """Normalize a lane label for exact comparison without inventing aliases."""
    if value is None:
        return ""
    return _WHITESPACE.sub(" ", str(value).strip()).casefold()


def normalize_currency(value: Optional[str]) -> str:
    return (str(value).strip().upper() if value is not None else "")


def _as_date(value: Any) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


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


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


@dataclass(frozen=True)
class RateSelection:
    usable: bool
    reason: str
    rate_quote: Optional[Decimal] = None
    rate_id: Optional[str] = None
    currency: Optional[str] = None
    considered_count: int = 0


def select_lane_rate(
    carrier: Mapping[str, Any],
    *,
    lane_origin: Optional[str],
    lane_destination: Optional[str],
    equipment_type: Optional[str],
    shipment_currency: Optional[str],
    pickup_start: Any,
) -> RateSelection:
    """Select the one usable flat lane rate under D-022 through D-026.

    Rules enforced:
    - Active lane-rate rows only.
    - Exact normalized origin, destination, equipment, and currency.
    - Pickup UTC date must fall inside the effective/expiration window.
    - Per-mile-only rates are not usable and mileage is never fabricated.
    - ``min_rate`` is metadata only and never used as a quote.
    - No FX conversion. No fallback to a different lane or currency.
    """
    pickup = _as_utc(pickup_start)
    origin = normalize_lane(lane_origin)
    destination = normalize_lane(lane_destination)
    equipment = (equipment_type or "").strip().lower()
    currency = normalize_currency(shipment_currency)

    if not origin or not destination or not equipment or not currency or pickup is None:
        return RateSelection(usable=False, reason=INCOMPLETE_INPUT)

    pickup_date = pickup.date()
    usable_rows: list[Tuple[Decimal, str, Mapping[str, Any]]] = []
    saw_lane_match = False
    saw_currency_mismatch = False
    saw_per_mile_only = False
    saw_not_effective = False

    for row in carrier.get("lane_rates") or []:
        if not bool(row.get("is_active", True)):
            continue
        if normalize_lane(row.get("origin_region")) != origin:
            continue
        if normalize_lane(row.get("destination_region")) != destination:
            continue
        if str(row.get("equipment_type") or "").strip().lower() != equipment:
            continue

        saw_lane_match = True
        if normalize_currency(row.get("currency")) != currency:
            saw_currency_mismatch = True
            continue

        effective = _as_date(row.get("effective_date"))
        expiration = _as_date(row.get("expiration_date"))
        if effective is not None and pickup_date < effective:
            saw_not_effective = True
            continue
        if expiration is not None and pickup_date > expiration:
            saw_not_effective = True
            continue

        flat = _decimal(row.get("flat_rate"))
        if flat is None:
            # Per-mile-only rows are never converted into a flat quote.
            saw_per_mile_only = True
            continue
        usable_rows.append((flat, str(row.get("id") or ""), row))

    if not usable_rows:
        if saw_lane_match and saw_currency_mismatch:
            reason = CURRENCY_MISMATCH
        elif saw_lane_match and saw_per_mile_only and not saw_currency_mismatch:
            reason = NO_FLAT_RATE
        elif saw_lane_match and saw_not_effective:
            reason = NOT_EFFECTIVE
        else:
            reason = NO_MATCHING_RATE
        return RateSelection(usable=False, reason=reason)

    flat, rate_id, row = sorted(usable_rows, key=lambda item: (item[0], item[1]))[0]
    return RateSelection(
        usable=True,
        reason=SELECTED,
        rate_quote=flat,
        rate_id=rate_id,
        currency=normalize_currency(row.get("currency")),
        considered_count=len(usable_rows),
    )

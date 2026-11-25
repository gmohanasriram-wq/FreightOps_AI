"""Four-component deterministic scoring and ranking (Task 004-H formulas).

Decimal arithmetic, ROUND_HALF_UP, four decimal places. A null score is never
converted to zero. Missing usable rates produce an unrankable candidate with a
null total; weights are never renormalized.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from backend.app.domain.eligibility.engine import ELIGIBLE

FOUR_PLACES = Decimal("0.0001")
ZERO = Decimal("0")
ONE = Decimal("1")

COMPONENT_NAMES: Tuple[str, ...] = (
    "equipment_fit",
    "capacity_timing",
    "rate_competitiveness",
    "data_completeness",
)

DEFAULT_WEIGHTS: Dict[str, Decimal] = {
    "equipment_fit": Decimal("0.30"),
    "capacity_timing": Decimal("0.25"),
    "rate_competitiveness": Decimal("0.30"),
    "data_completeness": Decimal("0.15"),
}


def q4(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def _decimal(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    return parsed if parsed.is_finite() else None


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


def _present(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def weights_from_config(raw: Mapping[str, Any]) -> Dict[str, Decimal]:
    weights: Dict[str, Decimal] = {}
    for name in COMPONENT_NAMES:
        value = _decimal(raw.get(name)) if raw else None
        weights[name] = value if value is not None else DEFAULT_WEIGHTS[name]
    return weights


def equipment_fit(
    carrier: Mapping[str, Any],
    shipment: Mapping[str, Any],
    matched_equipment: Optional[Mapping[str, Any]],
) -> Decimal:
    """Grade recorded capacity fit; the equipment-type hard gate already passed.

    Only dimensions supported by recorded schema facts are graded. If neither a
    weight ceiling nor a trailer-length requirement yields a dimension, the
    candidate receives 1.0000 because the verified equipment-type match is the
    only applicable fit evidence. Missing max weight and trailer data are still
    penalized in ``data_completeness``.
    """
    dimensions: List[Decimal] = []
    if matched_equipment is not None:
        max_weight = _decimal(matched_equipment.get("max_weight_lbs"))
        cargo_weight = _decimal(shipment.get("weight_lbs"))
        if max_weight is not None and max_weight > 0 and cargo_weight is not None and cargo_weight > 0:
            dimensions.append(min(ONE, max_weight / cargo_weight))

    requirements = shipment.get("requirements") or {}
    trailer_requirement = requirements.get("trailer_length_ft") if isinstance(requirements, Mapping) else None
    if isinstance(trailer_requirement, int) and not isinstance(trailer_requirement, bool) and trailer_requirement > 0:
        lengths = (
            matched_equipment.get("trailer_lengths_ft")
            if matched_equipment is not None
            else None
        )
        lengths = list(lengths or [])
        # Missing/empty trailer data never earns credit.
        dimensions.append(ONE if trailer_requirement in lengths else ZERO)

    if not dimensions:
        return q4(ONE)
    return q4(sum(dimensions, ZERO) / Decimal(len(dimensions)))


def capacity_timing(
    carrier: Mapping[str, Any],
    shipment: Mapping[str, Any],
) -> Decimal:
    pickup_start = _as_utc(shipment.get("pickup_start"))
    pickup_end = _as_utc(shipment.get("pickup_end")) or pickup_start
    if pickup_start is None or pickup_end is None:
        return q4(ZERO)

    best = ZERO
    duration_seconds = Decimal(str((pickup_end - pickup_start).total_seconds()))
    for row in carrier.get("availability") or []:
        available_from = _as_utc(row.get("available_from"))
        available_until = _as_utc(row.get("available_until"))
        if available_from is None or available_until is None:
            continue

        if duration_seconds <= 0:
            if available_from <= pickup_start <= available_until:
                best = max(best, ONE)
            continue

        overlap_start = max(pickup_start, available_from)
        overlap_end = min(pickup_end, available_until)
        overlap_seconds = Decimal(
            str(max(0.0, (overlap_end - overlap_start).total_seconds()))
        )
        best = max(best, min(ONE, overlap_seconds / duration_seconds))
    return q4(max(ZERO, min(ONE, best)))


def rate_competitiveness(
    shipment: Mapping[str, Any],
    rate_selection: Optional[Mapping[str, Any]],
) -> Optional[Decimal]:
    if not rate_selection or not rate_selection.get("usable"):
        return None
    quote = _decimal(rate_selection.get("rate_quote"))
    max_buy = _decimal(shipment.get("max_buy_rate"))
    if quote is None or max_buy is None:
        return None
    if max_buy < 0:
        return None
    if max_buy == 0:
        return q4(ONE if quote == 0 else ZERO)
    score = (max_buy - quote) / max_buy
    return q4(max(ZERO, min(ONE, score)))


def data_completeness(
    carrier: Mapping[str, Any],
    shipment: Mapping[str, Any],
    matched_equipment: Optional[Mapping[str, Any]],
) -> Decimal:
    base_fields = (
        "mc_number",
        "dot_number",
        "authority_status_recorded",
        "insurance_expiry_date",
        "primary_contact_name",
        "primary_contact_email",
        "primary_contact_phone",
    )
    present = sum(1 for field in base_fields if _present(carrier.get(field)))
    denominator = len(base_fields)

    denominator += 1
    if matched_equipment is not None and matched_equipment.get("max_weight_lbs") is not None:
        present += 1

    requirements = shipment.get("requirements") or {}
    trailer_requirement = requirements.get("trailer_length_ft") if isinstance(requirements, Mapping) else None
    if isinstance(trailer_requirement, int) and not isinstance(trailer_requirement, bool) and trailer_requirement > 0:
        denominator += 1
        lengths = (
            matched_equipment.get("trailer_lengths_ft")
            if matched_equipment is not None
            else None
        )
        if lengths and len(list(lengths)) > 0:
            present += 1

    return q4(Decimal(present) / Decimal(denominator))


@dataclass(frozen=True)
class ScoreResult:
    components: Mapping[str, Optional[Decimal]]
    total: Optional[Decimal]
    rankable: bool


def score_candidate(
    evaluation: Mapping[str, Any],
    shipment: Mapping[str, Any],
    weights: Optional[Mapping[str, Decimal]] = None,
) -> ScoreResult:
    """Score one evaluated candidate. Non-eligible candidates are not scored."""
    outcome = evaluation["eligibility"]
    if outcome.eligibility != ELIGIBLE:
        return ScoreResult(components={}, total=None, rankable=False)

    carrier = evaluation["carrier"]
    matched = evaluation.get("matched_equipment")
    selection = evaluation.get("rate_selection")
    selection_dict: Optional[Mapping[str, Any]] = None
    if selection is not None:
        selection_dict = {
            "usable": selection.usable,
            "rate_quote": selection.rate_quote,
        }

    components: Dict[str, Optional[Decimal]] = {
        "equipment_fit": equipment_fit(carrier, shipment, matched),
        "capacity_timing": capacity_timing(carrier, shipment),
        "rate_competitiveness": rate_competitiveness(shipment, selection_dict),
        "data_completeness": data_completeness(carrier, shipment, matched),
    }
    if components["rate_competitiveness"] is None:
        return ScoreResult(components=components, total=None, rankable=False)

    resolved_weights = dict(weights or DEFAULT_WEIGHTS)
    total = sum(
        (resolved_weights[name] * components[name] for name in COMPONENT_NAMES),  # type: ignore[operator]
        ZERO,
    )
    total = q4(max(ZERO, min(ONE, total)))
    return ScoreResult(components=components, total=total, rankable=True)


def score_and_rank(
    evaluations: Sequence[Mapping[str, Any]],
    shipment: Mapping[str, Any],
    weights: Optional[Mapping[str, Decimal]] = None,
) -> List[Dict[str, Any]]:
    """Score every evaluation and assign ranks to every rankable candidate.

    Tie-break: total descending, then carrier_id ascending. Ineligible,
    insufficient-data, and eligible-unrankable candidates keep rank=None.
    """
    scored: List[Dict[str, Any]] = []
    for evaluation in evaluations:
        result = score_candidate(evaluation, shipment, weights)
        scored.append(
            {
                "evaluation": evaluation,
                "components": result.components,
                "total": result.total,
                "rankable": result.rankable,
                "rank": None,
            }
        )

    rankable = [row for row in scored if row["rankable"] and row["total"] is not None]
    rankable.sort(
        key=lambda row: (-row["total"], str(row["evaluation"]["carrier"]["id"]))
    )
    for index, row in enumerate(rankable, start=1):
        row["rank"] = index
    return scored

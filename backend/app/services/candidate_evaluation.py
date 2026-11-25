"""Candidate evaluation service: shipment context + deterministic filters/rates."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence

from sqlalchemy.orm import Session

from backend.app.domain.eligibility.engine import (
    ELIGIBLE,
    EligibilityOutcome,
    evaluate_carrier,
)
from backend.app.domain.rates.selector import RateSelection, select_lane_rate
from backend.app.models.shipment import Shipment, ShipmentStop
from backend.app.services.carriers import carrier_to_snapshot, load_all_carriers


def _lane_label(city: Optional[str], state: Optional[str]) -> Optional[str]:
    if city and state:
        return f"{city}, {state}"
    if state:
        return state
    return None


def build_shipment_context(
    shipment: Shipment,
    stops: Sequence[ShipmentStop],
) -> Dict[str, Any]:
    """Build the pure-Python shipment context consumed by eligibility/scoring."""
    ordered = sorted(stops, key=lambda stop: stop.sequence)
    pickups = [stop for stop in ordered if stop.stop_type == "pickup"]
    deliveries = [stop for stop in ordered if stop.stop_type == "delivery"]
    first_pickup = pickups[0] if pickups else None
    last_delivery = deliveries[-1] if deliveries else None

    origin_state = first_pickup.state if first_pickup else None
    destination_state = last_delivery.state if last_delivery else None
    derived_origin = _lane_label(
        first_pickup.city if first_pickup else None,
        first_pickup.state if first_pickup else None,
    )
    derived_destination = _lane_label(
        last_delivery.city if last_delivery else None,
        last_delivery.state if last_delivery else None,
    )

    return {
        "shipment_id": str(shipment.id),
        "equipment_type": shipment.equipment_type,
        "weight_lbs": shipment.weight_lbs,
        "currency": shipment.currency,
        "target_sell_rate": shipment.target_sell_rate,
        "max_buy_rate": shipment.max_buy_rate,
        "lane_origin": shipment.lane_origin or derived_origin,
        "lane_destination": shipment.lane_destination or derived_destination,
        "origin_state": origin_state,
        "destination_state": destination_state,
        "requirements": dict(shipment.requirements or {}),
        "pickup_start": first_pickup.window_start if first_pickup else None,
        "pickup_end": first_pickup.window_end if first_pickup else None,
        "delivery_start": last_delivery.window_start if last_delivery else None,
        "delivery_end": last_delivery.window_end if last_delivery else None,
        "stops": [
            {
                "id": str(stop.id),
                "sequence": stop.sequence,
                "stop_type": stop.stop_type,
                "name": stop.name,
                "city": stop.city,
                "state": stop.state,
                "postal_code": stop.postal_code,
                "window_start": stop.window_start.isoformat() if stop.window_start else None,
                "window_end": stop.window_end.isoformat() if stop.window_end else None,
            }
            for stop in ordered
        ],
    }


def evaluate_candidate_snapshot(
    carrier: Mapping[str, Any],
    shipment_context: Mapping[str, Any],
) -> Dict[str, Any]:
    """Evaluate one carrier snapshot and attach its rate selection."""
    outcome = evaluate_carrier(carrier, shipment_context)
    selection: Optional[RateSelection] = None
    if outcome.eligibility == ELIGIBLE:
        selection = select_lane_rate(
            carrier,
            lane_origin=shipment_context.get("lane_origin"),
            lane_destination=shipment_context.get("lane_destination"),
            equipment_type=shipment_context.get("equipment_type"),
            shipment_currency=shipment_context.get("currency"),
            pickup_start=shipment_context.get("pickup_start"),
        )

    # A usable quote still cannot be scored without a maximum buy ceiling.
    has_ceiling = shipment_context.get("max_buy_rate") is not None
    rankable = bool(
        outcome.eligibility == ELIGIBLE
        and selection is not None
        and selection.usable
        and has_ceiling
    )
    if outcome.eligibility != ELIGIBLE:
        unrankable_reason = None
    elif selection is None or not selection.usable:
        unrankable_reason = selection.reason if selection is not None else "no_matching_rate"
    elif not has_ceiling:
        unrankable_reason = "missing_rate_ceiling"
    else:
        unrankable_reason = None

    return {
        "carrier": carrier,
        "eligibility": outcome,
        "rate_selection": selection,
        "rankable": rankable,
        "unrankable_reason": unrankable_reason,
        "rate_quote": selection.rate_quote if selection is not None else None,
        "rate_id": selection.rate_id if selection is not None else None,
        "matched_equipment": outcome.matched_equipment,
    }


def evaluate_all_candidates(
    db: Session,
    shipment: Shipment,
    stops: Sequence[ShipmentStop],
) -> Dict[str, Any]:
    """Evaluate every carrier in the broad universe (D-027).

    Returns the shipment context and one evaluated record per carrier. No
    carrier is pre-filtered and none is dropped from the result.
    """
    context = build_shipment_context(shipment, stops)
    carriers = load_all_carriers(db)
    candidates = [
        evaluate_candidate_snapshot(carrier_to_snapshot(carrier), context)
        for carrier in carriers
    ]
    return {
        "context": context,
        "candidates": candidates,
        "evaluated_count": len(candidates),
    }

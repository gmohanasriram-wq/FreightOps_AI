"""Integration tests for candidate evaluation against the synthetic demo universe."""
from sqlalchemy import select

from backend.app.db.session import SessionLocal
from backend.app.models.shipment import Shipment, ShipmentStop
from backend.app.services.candidate_evaluation import evaluate_all_candidates
from backend.app.services.demo_seed import DEMO_SHIPMENT_IDS, seed_all_demo_data


def _evaluate(key):
    with SessionLocal() as db:
        seed_all_demo_data(db)
        shipment = db.get(Shipment, DEMO_SHIPMENT_IDS[key])
        stops = db.scalars(
            select(ShipmentStop)
            .where(ShipmentStop.shipment_id == shipment.id)
            .order_by(ShipmentStop.sequence)
        ).all()
        result = evaluate_all_candidates(db, shipment, list(stops))
    return result


def _by_mc(result):
    return {
        candidate["carrier"]["mc_number"]: candidate
        for candidate in result["candidates"]
    }


def test_all_seeded_carriers_are_evaluated_and_preserved():
    result = _evaluate("ready")
    assert result["evaluated_count"] == 16
    mc_numbers = set(_by_mc(result))
    assert "MC-DEMO-1001" in mc_numbers
    assert "MC-DEMO-1016" in mc_numbers


def test_ready_shipment_eligibility_mix_and_rankability():
    result = _evaluate("ready")
    candidates = _by_mc(result)

    apex = candidates["MC-DEMO-1001"]
    assert apex["eligibility"].eligibility == "eligible"
    assert apex["rankable"] is True
    assert str(apex["rate_quote"]) == "2450.00"

    blue = candidates["MC-DEMO-1002"]
    assert blue["rankable"] is True
    assert str(blue["rate_quote"]) == "2600.00"

    norate = candidates["MC-DEMO-1006"]
    assert norate["eligibility"].eligibility == "eligible"
    assert norate["rankable"] is False
    assert norate["rate_quote"] is None
    assert norate["rate_selection"].reason == "no_matching_rate"

    assert candidates["MC-DEMO-1003"]["eligibility"].ineligibility_codes == (
        "carrier_inactive",
    )
    assert candidates["MC-DEMO-1004"]["eligibility"].ineligibility_codes == (
        "equipment_mismatch",
    )
    assert candidates["MC-DEMO-1005"]["eligibility"].ineligibility_codes == (
        "region_not_served",
    )
    assert candidates["MC-DEMO-1007"]["eligibility"].eligibility == "insufficient_data"
    assert candidates["MC-DEMO-1007"]["eligibility"].ineligibility_codes == (
        "missing_data",
    )
    assert candidates["MC-DEMO-1010"]["eligibility"].ineligibility_codes == (
        "no_capacity",
    )
    assert candidates["MC-DEMO-1011"]["eligibility"].eligibility == "insufficient_data"
    assert candidates["MC-DEMO-1012"]["eligibility"].eligibility == "insufficient_data"
    assert candidates["MC-DEMO-1013"]["eligibility"].ineligibility_codes == (
        "insurance_expired",
    )
    assert candidates["MC-DEMO-1016"]["eligibility"].ineligibility_codes == (
        "carrier_suspended",
    )

    assert candidates["MC-DEMO-1014"]["eligibility"].eligibility == "eligible"
    assert candidates["MC-DEMO-1014"]["rankable"] is False
    assert candidates["MC-DEMO-1014"]["rate_selection"].reason == "currency_mismatch"

    assert candidates["MC-DEMO-1015"]["eligibility"].eligibility == "eligible"
    assert candidates["MC-DEMO-1015"]["rankable"] is False
    assert candidates["MC-DEMO-1015"]["rate_selection"].reason == "no_flat_rate"


def test_no_eligible_shipment_has_zero_eligible_candidates():
    result = _evaluate("no_eligible")
    assert not any(
        c["eligibility"].eligibility == "eligible" for c in result["candidates"]
    )


def test_unrankable_shipment_has_eligible_but_zero_rankable_candidates():
    result = _evaluate("unrankable")
    eligible = [
        c for c in result["candidates"] if c["eligibility"].eligibility == "eligible"
    ]
    assert eligible
    assert all(c["rankable"] is False for c in eligible)


def test_combo_shipment_applies_hazmat_and_temperature_filters():
    result = _evaluate("combo")
    candidates = _by_mc(result)

    apex = candidates["MC-DEMO-1001"]
    assert apex["eligibility"].eligibility == "eligible"
    assert apex["rankable"] is True

    summit = candidates["MC-DEMO-1004"]
    assert summit["eligibility"].ineligibility_codes == ("hazmat_not_authorized",)

    tempcold = candidates["MC-DEMO-1009"]
    assert tempcold["eligibility"].ineligibility_codes == (
        "hazmat_not_authorized",
        "temperature_not_supported",
    )

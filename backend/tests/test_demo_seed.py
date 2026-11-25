"""Synthetic demo seeding tests: idempotency, labeling, and relationship data."""
from datetime import datetime, timezone

from sqlalchemy import func, select

from backend.app.db.session import SessionLocal
from backend.app.models.carrier import (
    Carrier,
    CarrierAvailability,
    CarrierLaneRate,
    CarrierServiceRegion,
)
from backend.app.models.scoring import ScoringConfig
from backend.app.models.shipment import Shipment, ShipmentStop
from backend.app.services.demo_seed import (
    CARRIER_SPECS,
    DEMO_SHIPMENT_IDS,
    _ns,
    seed_all_demo_data,
)


def test_demo_seed_is_idempotent_and_labels_synthetic_data():
    with SessionLocal() as db:
        first = seed_all_demo_data(db)

    with SessionLocal() as db:
        second = seed_all_demo_data(db)

        assert first["carriers"] == second["carriers"] == len(CARRIER_SPECS)
        assert first["shipments"] == second["shipments"] == 4

        for spec in CARRIER_SPECS:
            carrier = db.get(Carrier, _ns(f"carrier-{spec['key']}"))
            assert carrier is not None, spec["key"]
            assert carrier.data_source == "synthetic"
            assert "SYNTHETIC" in (carrier.notes or "")

        count = db.scalar(
            select(func.count()).select_from(Carrier).where(
                Carrier.data_source == "synthetic"
            )
        )
        assert count == len(CARRIER_SPECS)


def test_demo_seed_creates_active_scoring_config_and_relationships():
    with SessionLocal() as db:
        seed_all_demo_data(db)

        active_configs = db.scalars(
            select(ScoringConfig).where(ScoringConfig.is_active.is_(True))
        ).all()
        assert len(active_configs) == 1
        assert active_configs[0].weights["equipment_fit"] == "0.30"
        assert active_configs[0].weights["data_completeness"] == "0.15"

        rate_count = db.scalar(select(func.count()).select_from(CarrierLaneRate))
        region_count = db.scalar(select(func.count()).select_from(CarrierServiceRegion))
        availability_count = db.scalar(select(func.count()).select_from(CarrierAvailability))
        assert rate_count >= 10
        assert region_count >= len(CARRIER_SPECS)
        assert availability_count == len(CARRIER_SPECS)


def test_demo_seed_refreshes_shipment_windows_and_preserves_validated_status():
    with SessionLocal() as db:
        seed_all_demo_data(db)

        shipment = db.get(Shipment, DEMO_SHIPMENT_IDS["ready"])
        assert shipment is not None
        assert shipment.status == "validated"
        assert shipment.reference_number == "DEMO-READY-1001"
        assert shipment.lane_origin == "Chicago, IL"
        assert shipment.lane_destination == "Dallas, TX"

        stops = db.scalars(
            select(ShipmentStop)
            .where(ShipmentStop.shipment_id == shipment.id)
            .order_by(ShipmentStop.sequence)
        ).all()
        assert [s.stop_type for s in stops] == ["pickup", "delivery"]
        assert stops[0].window_start > datetime.now(timezone.utc)
        assert stops[1].window_end > stops[0].window_start

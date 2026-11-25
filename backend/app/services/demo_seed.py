"""Idempotent synthetic demo data (clearly labeled, never real carrier facts).

The seed is safe to run repeatedly. It only mutates rows it created and marks
every carrier with ``data_source='synthetic'``. Availability windows and demo
shipment stop windows are refreshed on each run so the demo remains executable.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from backend.app.models.carrier import (
    Carrier,
    CarrierAvailability,
    CarrierEquipmentType,
    CarrierLaneRate,
    CarrierServiceRegion,
)
from backend.app.models.customer import Customer
from backend.app.models.facility import Facility
from backend.app.models.scoring import ScoringConfig
from backend.app.models.shipment import Shipment, ShipmentStop

SYNTHETIC_NOTE = "SYNTHETIC DEMO DATA - not a real carrier or real-world record."

SCORING_WEIGHTS = {
    "equipment_fit": "0.30",
    "capacity_timing": "0.25",
    "rate_competitiveness": "0.30",
    "data_completeness": "0.15",
}


def _ns(name: str) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"https://freightops.local/demo/{name}")


CUSTOMER_ID = _ns("customer-northwind")
ORIGIN_FACILITY_ID = _ns("facility-chicago")
DESTINATION_FACILITY_ID = _ns("facility-dallas")

DEMO_SHIPMENT_IDS = {
    "ready": _ns("shipment-ready-1001"),
    "no_eligible": _ns("shipment-no-eligible-1002"),
    "unrankable": _ns("shipment-unrankable-1003"),
    "combo": _ns("shipment-combo-1004"),
}


def _utc(days: int, hour: int, minute: int = 0) -> datetime:
    base = datetime.now(timezone.utc) + timedelta(days=days)
    return base.replace(hour=hour, minute=minute, second=0, microsecond=0)


CARRIER_SPECS: List[Dict[str, Any]] = [
    {
        "key": "apex",
        "legal_name": "Apex Freight LLC",
        "mc_number": "MC-DEMO-1001",
        "dot_number": "DOT-DEMO-1001",
        "status": "active",
        "insurance_days": 365,
        "hazmat": True,
        "temperature": True,
        "equipment": [
            {"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53, 48]},
            {"type": "reefer", "max_weight_lbs": 44000, "trailers": [53]},
        ],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2450.00"},
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "reefer", "flat": "3100.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "blue",
        "legal_name": "Blue Line Transport Inc.",
        "mc_number": "MC-DEMO-1002",
        "dot_number": "DOT-DEMO-1002",
        "status": "active",
        "insurance_days": 240,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 43000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2600.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "redline",
        "legal_name": "Redline Carriers",
        "mc_number": "MC-DEMO-1003",
        "dot_number": "DOT-DEMO-1003",
        "status": "inactive",
        "insurance_days": 365,
        "hazmat": True,
        "temperature": True,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "1800.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "summit",
        "legal_name": "Summit Reefer Services",
        "mc_number": "MC-DEMO-1004",
        "dot_number": "DOT-DEMO-1004",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": True,
        "equipment": [{"type": "reefer", "max_weight_lbs": 44000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "reefer", "flat": "2900.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "gulf",
        "legal_name": "Gulf Coast Freight",
        "mc_number": "MC-DEMO-1005",
        "dot_number": "DOT-DEMO-1005",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2300.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "norate",
        "legal_name": "No Rate Logistics",
        "mc_number": "MC-DEMO-1006",
        "dot_number": "DOT-DEMO-1006",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 44000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "noins",
        "legal_name": "Unconfirmed Insurance Co.",
        "mc_number": "MC-DEMO-1007",
        "dot_number": "DOT-DEMO-1007",
        "status": "active",
        "insurance_days": None,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 44000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2100.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "hazless",
        "legal_name": "Hazmat-Limited Haulers",
        "mc_number": "MC-DEMO-1008",
        "dot_number": "DOT-DEMO-1008",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2000.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "tempcold",
        "legal_name": "Ambient Reefer Lines",
        "mc_number": "MC-DEMO-1009",
        "dot_number": "DOT-DEMO-1009",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "reefer", "max_weight_lbs": 44000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "reefer", "flat": "2200.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "nocap",
        "legal_name": "Future Capacity Carriers",
        "mc_number": "MC-DEMO-1010",
        "dot_number": "DOT-DEMO-1010",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "1950.00"},
        ],
        "availability": [(20, 40)],
        "contacts": True,
    },
    {
        "key": "ghost",
        "legal_name": "Unverified Carrier Record",
        "mc_number": "MC-DEMO-1011",
        "dot_number": None,
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [],
        "regions": [],
        "rates": [],
        "availability": [(-1, 365)],
        "contacts": False,
    },
    {
        "key": "inactiveeq",
        "legal_name": "Inactive Equipment Carrier",
        "mc_number": "MC-DEMO-1012",
        "dot_number": "DOT-DEMO-1012",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [
            {"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53], "is_active": False}
        ],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2050.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "expiredins",
        "legal_name": "Expired Insurance Carriers",
        "mc_number": "MC-DEMO-1013",
        "dot_number": "DOT-DEMO-1013",
        "status": "active",
        "insurance_days": -1,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "1900.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "wrongcurrency",
        "legal_name": "Euro Lane Carriers",
        "mc_number": "MC-DEMO-1014",
        "dot_number": "DOT-DEMO-1014",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "2000.00", "currency": "EUR"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "permile",
        "legal_name": "Per-Mile Only Carriers",
        "mc_number": "MC-DEMO-1015",
        "dot_number": "DOT-DEMO-1015",
        "status": "active",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "per_mile": "2.10"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
    {
        "key": "suspended",
        "legal_name": "Suspended Authority Lines",
        "mc_number": "MC-DEMO-1016",
        "dot_number": "DOT-DEMO-1016",
        "status": "suspended",
        "insurance_days": 365,
        "hazmat": False,
        "temperature": False,
        "equipment": [{"type": "dry_van", "max_weight_lbs": 45000, "trailers": [53]}],
        "regions": ["IL", "TX"],
        "rates": [
            {"origin": "Chicago, IL", "destination": "Dallas, TX", "equipment": "dry_van", "flat": "1850.00"},
        ],
        "availability": [(-1, 365)],
        "contacts": True,
    },
]


def ensure_scoring_config(db: Session) -> ScoringConfig:
    """Return the active scoring configuration, creating version 1 if needed."""
    active = db.scalars(
        select(ScoringConfig).where(ScoringConfig.is_active.is_(True))
    ).first()
    if active is not None:
        return active

    existing = db.scalars(select(ScoringConfig).where(ScoringConfig.version == 1)).first()
    now = datetime.now(timezone.utc)
    if existing is not None:
        existing.weights = dict(SCORING_WEIGHTS)
        existing.is_active = True
        existing.activated_at = now
        db.flush()
        return existing

    config = ScoringConfig(
        id=_ns("scoring-config-v1"),
        version=1,
        name="MVP four-component scoring v1",
        weights=dict(SCORING_WEIGHTS),
        is_active=True,
        activated_at=now,
    )
    db.add(config)
    db.flush()
    return config


def ensure_customer_and_facilities(db: Session) -> tuple[Customer, Facility, Facility]:
    customer = db.get(Customer, CUSTOMER_ID)
    if customer is None:
        customer = Customer(
            id=CUSTOMER_ID,
            name="Northwind Retail Group (Synthetic Demo)",
            reference_code="CUST-DEMO-001",
            contact_name="Demo Customer Contact",
            contact_email="demo.customer@example.invalid",
            contact_phone="555-0100",
            notes=SYNTHETIC_NOTE,
            is_active=True,
        )
        db.add(customer)
        db.flush()

    origin = db.get(Facility, ORIGIN_FACILITY_ID)
    if origin is None:
        origin = Facility(
            id=ORIGIN_FACILITY_ID,
            customer_id=customer.id,
            name="Chicago Distribution Center (Synthetic Demo)",
            code="FAC-CHI-DEMO",
            facility_type="distribution_center",
            address_line1="100 Logistics Blvd",
            city="Chicago",
            state="IL",
            postal_code="60601",
            country="US",
            timezone="America/Chicago",
            contact_name="Chicago Dispatch",
            contact_phone="312-555-0100",
            appointment_required=True,
        )
        db.add(origin)
        db.flush()

    destination = db.get(Facility, DESTINATION_FACILITY_ID)
    if destination is None:
        destination = Facility(
            id=DESTINATION_FACILITY_ID,
            customer_id=customer.id,
            name="Dallas Fulfillment Center (Synthetic Demo)",
            code="FAC-DAL-DEMO",
            facility_type="warehouse",
            address_line1="500 Freight Way",
            city="Dallas",
            state="TX",
            postal_code="75201",
            country="US",
            timezone="America/Chicago",
            contact_name="Dallas Receiving",
            contact_phone="214-555-0200",
            appointment_required=False,
        )
        db.add(destination)
        db.flush()

    return customer, origin, destination


def _upsert_carrier(db: Session, spec: Dict[str, Any]) -> Carrier:
    carrier_id = _ns(f"carrier-{spec['key']}")
    carrier = db.get(Carrier, carrier_id)
    today = date.today()
    insurance = (
        today + timedelta(days=spec["insurance_days"])
        if spec.get("insurance_days") is not None
        else None
    )

    if carrier is None:
        carrier = Carrier(
            id=carrier_id,
            legal_name=spec["legal_name"],
            mc_number=spec["mc_number"],
            dot_number=spec.get("dot_number"),
            status=spec["status"],
            authority_status_recorded="active" if spec["status"] == "active" else spec["status"],
            insurance_expiry_date=insurance,
            hazmat_authorized=bool(spec.get("hazmat")),
            temperature_capable=bool(spec.get("temperature")),
            primary_contact_name=spec["legal_name"] + " Dispatch" if spec.get("contacts") else None,
            primary_contact_email=(
                f"dispatch+{spec['key']}@example.invalid" if spec.get("contacts") else None
            ),
            primary_contact_phone=(
                "555-01" + str(len(spec["key"])).zfill(2) if spec.get("contacts") else None
            ),
            data_source="synthetic",
            last_verified_at=datetime.now(timezone.utc),
            notes=SYNTHETIC_NOTE,
        )
        db.add(carrier)
        db.flush()
    else:
        carrier.legal_name = spec["legal_name"]
        carrier.mc_number = spec["mc_number"]
        carrier.dot_number = spec.get("dot_number")
        carrier.status = spec["status"]
        carrier.authority_status_recorded = (
            "active" if spec["status"] == "active" else spec["status"]
        )
        carrier.insurance_expiry_date = insurance
        carrier.hazmat_authorized = bool(spec.get("hazmat"))
        carrier.temperature_capable = bool(spec.get("temperature"))
        carrier.data_source = "synthetic"
        carrier.last_verified_at = datetime.now(timezone.utc)
        carrier.notes = SYNTHETIC_NOTE
        db.flush()

    existing_equipment = {row.equipment_type: row for row in (carrier.equipment_types or [])}
    for item in spec["equipment"]:
        row = existing_equipment.get(item["type"])
        if row is None:
            row = CarrierEquipmentType(
                id=_ns(f"carrier-{spec['key']}-equipment-{item['type']}"),
                carrier_id=carrier.id,
                equipment_type=item["type"],
                max_weight_lbs=item.get("max_weight_lbs"),
                trailer_lengths_ft=item.get("trailers"),
                is_active=item.get("is_active", True),
            )
            db.add(row)
        else:
            row.max_weight_lbs = item.get("max_weight_lbs")
            row.trailer_lengths_ft = item.get("trailers")
            row.is_active = item.get("is_active", True)
    db.flush()

    existing_regions = {
        (row.region_type, row.region_value): row for row in (carrier.service_regions or [])
    }
    for state in spec["regions"]:
        row = existing_regions.get(("state", state))
        if row is None:
            db.add(
                CarrierServiceRegion(
                    id=_ns(f"carrier-{spec['key']}-region-{state}"),
                    carrier_id=carrier.id,
                    region_type="state",
                    region_value=state,
                    is_active=True,
                )
            )
        else:
            row.is_active = True
    db.flush()

    existing_rates = {
        (row.origin_region, row.destination_region, row.equipment_type): row
        for row in (carrier.lane_rates or [])
    }
    for rate in spec["rates"]:
        key = (rate["origin"], rate["destination"], rate["equipment"])
        row = existing_rates.get(key)
        values = {
            "flat_rate": Decimal(rate["flat"]) if rate.get("flat") is not None else None,
            "rate_per_mile": (
                Decimal(rate["per_mile"]) if rate.get("per_mile") is not None else None
            ),
            "currency": rate.get("currency", "USD"),
            "source": "synthetic",
            "is_active": True,
            "effective_date": today - timedelta(days=30),
            "expiration_date": today + timedelta(days=365),
        }
        if row is None:
            row = CarrierLaneRate(
                id=_ns(f"carrier-{spec['key']}-rate-{rate['equipment']}"),
                carrier_id=carrier.id,
                origin_region=rate["origin"],
                destination_region=rate["destination"],
                equipment_type=rate["equipment"],
                min_rate=None,
                **values,
            )
            db.add(row)
        else:
            for field, value in values.items():
                setattr(row, field, value)
    db.flush()

    # Availability is carrier-wide and refreshed to the current demo clock.
    db.execute(
        delete(CarrierAvailability).where(CarrierAvailability.carrier_id == carrier.id)
    )
    for start_days, end_days in spec["availability"]:
        db.add(
            CarrierAvailability(
                id=_ns(f"carrier-{spec['key']}-availability-{start_days}-{end_days}"),
                carrier_id=carrier.id,
                available_from=_utc(start_days, 0),
                available_until=_utc(end_days, 23, 59),
                notes=SYNTHETIC_NOTE,
            )
        )
    db.flush()
    return carrier


def seed_demo_carriers(db: Session) -> int:
    for spec in CARRIER_SPECS:
        _upsert_carrier(db, spec)
    db.flush()
    return len(CARRIER_SPECS)


def _stop(
    shipment_id: uuid.UUID,
    sequence: int,
    stop_type: str,
    facility: Facility,
    window_start: datetime,
    window_end: datetime,
) -> ShipmentStop:
    return ShipmentStop(
        id=_ns(f"shipment-{shipment_id}-stop-{sequence}"),
        shipment_id=shipment_id,
        facility_id=facility.id,
        sequence=sequence,
        stop_type=stop_type,
        name=facility.name,
        address_line1=facility.address_line1,
        city=facility.city,
        state=facility.state,
        postal_code=facility.postal_code,
        country="US",
        window_start=window_start,
        window_end=window_end,
        appointment_required=facility.appointment_required,
        contact_name=facility.contact_name,
        contact_phone=facility.contact_phone,
    )


def _upsert_demo_shipment(
    db: Session,
    *,
    key: str,
    reference: str,
    origin: Facility,
    destination: Facility,
    equipment_type: str,
    commodity: str,
    weight_lbs: int,
    target_sell_rate: Optional[str],
    max_buy_rate: Optional[str],
    requirements: Dict[str, Any],
    notes: str,
) -> Shipment:
    shipment_id = DEMO_SHIPMENT_IDS[key]
    shipment = db.get(Shipment, shipment_id)
    if shipment is None:
        shipment = Shipment(
            id=shipment_id,
            customer_id=CUSTOMER_ID,
            origin_facility_id=origin.id,
            destination_facility_id=destination.id,
            status="validated",
            source="manual",
            reference_number=reference,
            commodity=commodity,
            equipment_type=equipment_type,
            weight_lbs=weight_lbs,
            target_sell_rate=Decimal(target_sell_rate) if target_sell_rate else None,
            max_buy_rate=Decimal(max_buy_rate) if max_buy_rate else None,
            currency="USD",
            lane_origin=f"{origin.city}, {origin.state}",
            lane_destination=f"{destination.city}, {destination.state}",
            requirements=requirements,
            notes=notes,
            version=1,
        )
        db.add(shipment)
        db.flush()
    else:
        shipment.customer_id = CUSTOMER_ID
        shipment.origin_facility_id = origin.id
        shipment.destination_facility_id = destination.id
        shipment.commodity = commodity
        shipment.equipment_type = equipment_type
        shipment.weight_lbs = weight_lbs
        shipment.target_sell_rate = (
            Decimal(target_sell_rate) if target_sell_rate else None
        )
        shipment.max_buy_rate = Decimal(max_buy_rate) if max_buy_rate else None
        shipment.currency = "USD"
        shipment.lane_origin = f"{origin.city}, {origin.state}"
        shipment.lane_destination = f"{destination.city}, {destination.state}"
        shipment.requirements = requirements
        shipment.notes = notes
        # Demo shipments are synthetic seed fixtures with fixed UUIDs. Seeding
        # refreshes them to a runnable state so a repeated demo never resumes a
        # stale workflow. User-created shipments are never touched here.
        shipment.status = "validated"
        shipment.frozen_at = None
        db.flush()

    db.execute(delete(ShipmentStop).where(ShipmentStop.shipment_id == shipment.id))
    db.flush()
    db.add(
        _stop(
            shipment.id,
            1,
            "pickup",
            origin,
            _utc(2, 8),
            _utc(2, 12),
        )
    )
    db.add(
        _stop(
            shipment.id,
            2,
            "delivery",
            destination,
            _utc(4, 8),
            _utc(4, 17),
        )
    )
    db.flush()
    return shipment


def seed_demo_shipments(db: Session) -> int:
    customer, origin, destination = ensure_customer_and_facilities(db)

    _upsert_demo_shipment(
        db,
        key="ready",
        reference="DEMO-READY-1001",
        origin=origin,
        destination=destination,
        equipment_type="dry_van",
        commodity="Palletized consumer goods",
        weight_lbs=42000,
        target_sell_rate="3200.00",
        max_buy_rate="2600.00",
        requirements={
            "trailer_length_ft": 53,
            "hazmat": False,
            "appointment": True,
            "notes": "Synthetic demo load. Dock appointment required.",
        },
        notes="SYNTHETIC DEMO SHIPMENT - eligible and rankable candidates expected.",
    )

    _upsert_demo_shipment(
        db,
        key="no_eligible",
        reference="DEMO-INELIGIBLE-1002",
        origin=origin,
        destination=destination,
        equipment_type="flatbed",
        commodity="Steel coils",
        weight_lbs=18000,
        target_sell_rate="3000.00",
        max_buy_rate="2200.00",
        requirements={"hazmat": False},
        notes="SYNTHETIC DEMO SHIPMENT - no seeded carrier has flatbed equipment.",
    )

    _upsert_demo_shipment(
        db,
        key="unrankable",
        reference="DEMO-UNRANKABLE-1003",
        origin=origin,
        destination=destination,
        equipment_type="dry_van",
        commodity="Packaged food products",
        weight_lbs=30000,
        target_sell_rate="2500.00",
        max_buy_rate=None,
        requirements={"hazmat": False},
        notes="SYNTHETIC DEMO SHIPMENT - eligible carriers, no max buy ceiling, so unrankable.",
    )

    _upsert_demo_shipment(
        db,
        key="combo",
        reference="DEMO-COMBO-1004",
        origin=origin,
        destination=destination,
        equipment_type="reefer",
        commodity="Temperature-controlled chemical samples",
        weight_lbs=24000,
        target_sell_rate="3800.00",
        max_buy_rate="3300.00",
        requirements={
            "hazmat": True,
            "temperature_range": {"min_f": -10.0, "max_f": 0.0},
            "trailer_length_ft": 53,
        },
        notes="SYNTHETIC DEMO SHIPMENT - exercises hazmat and temperature filters.",
    )

    return 4


def seed_all_demo_data(db: Session) -> Dict[str, int]:
    """Seed all synthetic demo data in one transaction."""
    config = ensure_scoring_config(db)
    carrier_count = seed_demo_carriers(db)
    shipment_count = seed_demo_shipments(db)
    db.commit()
    return {
        "carriers": carrier_count,
        "shipments": shipment_count,
        "scoring_config_version": config.version,
    }

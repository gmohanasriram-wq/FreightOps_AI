"""Deterministic Validation Engine per Contract 2.2 §5.3 / Component Architecture §4.6.

Architectural Guarantee:
- Performs NO network calls.
- Performs NO database writes.
- Makes NO LLM calls.
- Returns ordered ValidationIssue objects with canonical severity (info, warning, error, critical).
"""
import re
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Tuple
from pydantic import BaseModel, Field

RULES_VERSION = "2026.1"

REEFER_COMMODITY_KEYWORDS = [
    "frozen",
    "refrigerated",
    "produce",
    "poultry",
    "ice cream",
    "meat",
    "dairy",
    "seafood",
    "fresh",
    "chilled",
]

HAZMAT_COMMODITY_KEYWORDS = [
    "chemical",
    "flammable",
    "corrosive",
    "explosive",
    "acid",
    "poison",
    "toxic",
    "radioactive",
    "hazmat",
    "battery",
]


class ValidationIssue(BaseModel):
    """Canonical validation issue finding."""
    rule_code: str
    severity: Literal["info", "warning", "error", "critical"]
    field: str
    message: str


class ValidationEngine:
    """Pure, deterministic validation engine."""

    @staticmethod
    def validate(shipment: Dict[str, Any], stops: List[Dict[str, Any]]) -> Tuple[str, List[ValidationIssue]]:
        """Validate a shipment aggregate.
        
        Returns:
            (result_status, issues)
            result_status is one of: 'passed', 'passed_with_warnings', 'failed'
        """
        issues: List[ValidationIssue] = []

        # ---------------------------------------------------------------------
        # 1. Required-Field Validation (Category A)
        # ---------------------------------------------------------------------
        if not shipment.get("customer_id"):
            issues.append(
                ValidationIssue(
                    rule_code="REQ-CUST",
                    severity="error",
                    field="customer_id",
                    message="Customer account is required before shipment can be validated.",
                )
            )

        equipment_type = shipment.get("equipment_type")
        if not equipment_type:
            issues.append(
                ValidationIssue(
                    rule_code="REQ-EQP",
                    severity="error",
                    field="equipment_type",
                    message="Equipment type ('dry_van', 'reefer', 'flatbed') is required.",
                )
            )

        commodity = shipment.get("commodity")
        if not commodity or not str(commodity).strip():
            issues.append(
                ValidationIssue(
                    rule_code="REQ-COMM",
                    severity="error",
                    field="commodity",
                    message="Commodity description is required.",
                )
            )

        weight_lbs = shipment.get("weight_lbs")
        if weight_lbs is None:
            issues.append(
                ValidationIssue(
                    rule_code="REQ-WGT",
                    severity="error",
                    field="weight_lbs",
                    message="Cargo weight in pounds is required.",
                )
            )

        if not stops or len(stops) < 2:
            issues.append(
                ValidationIssue(
                    rule_code="REQ-STOPS",
                    severity="critical",
                    field="stops",
                    message="Shipment must have at least one pickup stop and one delivery stop.",
                )
            )

        pickup_stops = [s for s in stops if s.get("stop_type") == "pickup"]
        delivery_stops = [s for s in stops if s.get("stop_type") == "delivery"]

        if not pickup_stops:
            issues.append(
                ValidationIssue(
                    rule_code="REQ-PKUP",
                    severity="critical",
                    field="stops",
                    message="At least one pickup stop is required.",
                )
            )

        if not delivery_stops:
            issues.append(
                ValidationIssue(
                    rule_code="REQ-DELV",
                    severity="critical",
                    field="stops",
                    message="At least one delivery stop is required.",
                )
            )

        for stop in stops:
            seq = stop.get("sequence", "?")
            required_stop_fields = [
                ("name", "Facility name"),
                ("address_line1", "Street address"),
                ("city", "City"),
                ("state", "State"),
                ("postal_code", "Postal code"),
            ]
            for f_name, f_label in required_stop_fields:
                if not stop.get(f_name) or not str(stop.get(f_name)).strip():
                    issues.append(
                        ValidationIssue(
                            rule_code="REQ-ADDR",
                            severity="error",
                            field=f"stops[{seq}].{f_name}",
                            message=f"{f_label} is required on stop {seq} (DEF-01).",
                        )
                    )

            if not stop.get("window_start") or not stop.get("window_end"):
                issues.append(
                    ValidationIssue(
                        rule_code="REQ-WNDW",
                        severity="error",
                        field=f"stops[{seq}].window",
                        message=f"Schedule window start and end times are required on stop {seq}.",
                    )
                )

        # ---------------------------------------------------------------------
        # 2. Type and Range Validation (Category B)
        # ---------------------------------------------------------------------
        if weight_lbs is not None:
            try:
                w_val = int(weight_lbs)
                if w_val <= 0:
                    issues.append(
                        ValidationIssue(
                            rule_code="RNG-WGT-MIN",
                            severity="critical",
                            field="weight_lbs",
                            message=f"Cargo weight ({w_val} lbs) must be greater than 0 lbs.",
                        )
                    )
                elif w_val > 45000:
                    issues.append(
                        ValidationIssue(
                            rule_code="RNG-WGT-MAX",
                            severity="error",
                            field="weight_lbs",
                            message=f"Cargo weight ({w_val} lbs) exceeds maximum legal highway payload (45,000 lbs).",
                        )
                    )
            except (ValueError, TypeError):
                issues.append(
                    ValidationIssue(
                        rule_code="RNG-WGT-MIN",
                        severity="critical",
                        field="weight_lbs",
                        message="Weight must be a valid integer.",
                    )
                )

        target_sell = shipment.get("target_sell_rate")
        if target_sell is not None:
            try:
                if float(target_sell) < 0:
                    issues.append(
                        ValidationIssue(
                            rule_code="RNG-RATE-SELL",
                            severity="error",
                            field="target_sell_rate",
                            message="Target sell rate cannot be negative.",
                        )
                    )
            except (ValueError, TypeError):
                pass

        max_buy = shipment.get("max_buy_rate")
        if max_buy is not None:
            try:
                if float(max_buy) < 0:
                    issues.append(
                        ValidationIssue(
                            rule_code="RNG-RATE-BUY",
                            severity="error",
                            field="max_buy_rate",
                            message="Maximum buy rate cannot be negative.",
                        )
                    )
            except (ValueError, TypeError):
                pass

        # Temperature range validation
        reqs = shipment.get("requirements") or {}
        if isinstance(reqs, dict):
            temp_range = reqs.get("temperature_range")
            if isinstance(temp_range, dict):
                min_f = temp_range.get("min_f")
                max_f = temp_range.get("max_f")
                if min_f is not None and max_f is not None:
                    try:
                        min_val, max_val = float(min_f), float(max_f)
                        if min_val < -20.0 or max_val > 80.0:
                            issues.append(
                                ValidationIssue(
                                    rule_code="RNG-TMP-VAL",
                                    severity="error",
                                    field="requirements.temperature_range",
                                    message=f"Temperature range ({min_val}°F to {max_val}°F) must be within valid transport limits (-20°F to 80°F).",
                                )
                            )
                        if min_val > max_val:
                            issues.append(
                                ValidationIssue(
                                    rule_code="RNG-TMP-ORD",
                                    severity="critical",
                                    field="requirements.temperature_range",
                                    message=f"Minimum temperature ({min_val}°F) cannot exceed maximum temperature ({max_val}°F).",
                                )
                            )
                    except (ValueError, TypeError):
                        pass

        # Stop sequences validation
        if stops:
            sequences = [s.get("sequence") for s in stops if s.get("sequence") is not None]
            expected_seqs = list(range(1, len(stops) + 1))
            if sorted(sequences) != expected_seqs:
                issues.append(
                    ValidationIssue(
                        rule_code="RNG-STOP-SEQ",
                        severity="critical",
                        field="stops.sequence",
                        message=f"Stop sequences must be sequential integers starting at 1 without gaps or duplicates (got {sequences}).",
                    )
                )

        # ---------------------------------------------------------------------
        # 3. Cross-Field Validation (Category C)
        # ---------------------------------------------------------------------
        # Pickups must precede deliveries
        if pickup_stops and delivery_stops:
            max_pickup_seq = max(s.get("sequence", 0) for s in pickup_stops)
            min_delivery_seq = min(s.get("sequence", 9999) for s in delivery_stops)
            if max_pickup_seq >= min_delivery_seq:
                issues.append(
                    ValidationIssue(
                        rule_code="XFL-STOP-ORD",
                        severity="critical",
                        field="stops",
                        message=f"All pickup stops must precede delivery stops (highest pickup sequence {max_pickup_seq} >= lowest delivery sequence {min_delivery_seq}).",
                    )
                )

        # Time windows on individual stops
        for stop in stops:
            seq = stop.get("sequence", "?")
            w_start = stop.get("window_start")
            w_end = stop.get("window_end")
            if w_start and w_end:
                try:
                    dt_start = w_start if isinstance(w_start, datetime) else datetime.fromisoformat(str(w_start).replace("Z", "+00:00"))
                    dt_end = w_end if isinstance(w_end, datetime) else datetime.fromisoformat(str(w_end).replace("Z", "+00:00"))
                    if dt_start > dt_end:
                        issues.append(
                            ValidationIssue(
                                rule_code="XFL-TIME-STOP",
                                severity="error",
                                field=f"stops[{seq}].window",
                                message=f"Stop {seq} arrival window_start ({w_start}) cannot be after window_end ({w_end}).",
                            )
                        )
                except Exception:
                    pass

        # Lane schedule window: first pickup vs last delivery
        if pickup_stops and delivery_stops:
            sorted_pickups = sorted(pickup_stops, key=lambda s: s.get("sequence", 0))
            sorted_deliveries = sorted(delivery_stops, key=lambda s: s.get("sequence", 0))
            first_p_start = sorted_pickups[0].get("window_start")
            last_d_end = sorted_deliveries[-1].get("window_end")
            if first_p_start and last_d_end:
                try:
                    dt_p = first_p_start if isinstance(first_p_start, datetime) else datetime.fromisoformat(str(first_p_start).replace("Z", "+00:00"))
                    dt_d = last_d_end if isinstance(last_d_end, datetime) else datetime.fromisoformat(str(last_d_end).replace("Z", "+00:00"))
                    if dt_p >= dt_d:
                        issues.append(
                            ValidationIssue(
                                rule_code="XFL-TIME-LANE",
                                severity="critical",
                                field="stops",
                                message="Final delivery window end must be scheduled after initial pickup window start.",
                            )
                        )
                except Exception:
                    pass

        # Facility identity check
        orig_fac = shipment.get("origin_facility_id")
        dest_fac = shipment.get("destination_facility_id")
        if orig_fac and dest_fac and orig_fac == dest_fac:
            issues.append(
                ValidationIssue(
                    rule_code="XFL-FAC-SAME",
                    severity="warning",
                    field="destination_facility_id",
                    message="Origin and destination facilities are identical; verify whether this is an intracity transfer.",
                )
            )

        # Margin warning
        if target_sell is not None and max_buy is not None:
            try:
                if float(max_buy) > float(target_sell):
                    issues.append(
                        ValidationIssue(
                            rule_code="XFL-RATE-MRG",
                            severity="warning",
                            field="max_buy_rate",
                            message=f"Maximum buy rate (${float(max_buy):.2f}) exceeds target sell rate (${float(target_sell):.2f}), indicating projected negative margin.",
                        )
                    )
            except (ValueError, TypeError):
                pass

        # ---------------------------------------------------------------------
        # 4. Business-Rule Validation (Category D)
        # ---------------------------------------------------------------------
        if commodity:
            comm_lower = str(commodity).lower()
            is_reefer_cargo = any(k in comm_lower for k in REEFER_COMMODITY_KEYWORDS)
            if is_reefer_cargo and equipment_type and equipment_type != "reefer":
                issues.append(
                    ValidationIssue(
                        rule_code="BIZ-REEFER-REQ",
                        severity="error",
                        field="equipment_type",
                        message=f"Commodity '{commodity}' indicates temperature-sensitive cargo requiring 'reefer' equipment (got '{equipment_type}').",
                    )
                )

            is_hazmat_cargo = any(k in comm_lower for k in HAZMAT_COMMODITY_KEYWORDS)
            if is_hazmat_cargo and not reqs.get("hazmat"):
                issues.append(
                    ValidationIssue(
                        rule_code="BIZ-HAZMAT-CAP",
                        severity="warning",
                        field="requirements.hazmat",
                        message=f"Commodity '{commodity}' may contain hazardous materials, but hazmat requirement flag is false.",
                    )
                )

        if equipment_type == "reefer":
            temp_range = reqs.get("temperature_range")
            if not temp_range or not isinstance(temp_range, dict) or temp_range.get("min_f") is None:
                issues.append(
                    ValidationIssue(
                        rule_code="BIZ-REEFER-TMP",
                        severity="error",
                        field="requirements.temperature_range",
                        message="Reefer equipment selected but required temperature_range setpoint is missing in requirements.",
                    )
                )

        for stop in stops:
            seq = stop.get("sequence", "?")
            if stop.get("appointment_required") and not stop.get("contact_phone"):
                issues.append(
                    ValidationIssue(
                        rule_code="BIZ-APPT-REQ",
                        severity="warning",
                        field=f"stops[{seq}].contact_phone",
                        message=f"Stop {seq} requires appointment scheduling but no on-site contact phone is provided.",
                    )
                )

        # ---------------------------------------------------------------------
        # 5. Severity Composition and Result
        # ---------------------------------------------------------------------
        has_blocking = any(i.severity in ("critical", "error") for i in issues)
        has_warnings = any(i.severity == "warning" for i in issues)

        if has_blocking:
            result_status = "failed"
        elif has_warnings:
            result_status = "passed_with_warnings"
        else:
            result_status = "passed"

        return result_status, issues

"""Comprehensive verification tests for the 21-table Contract 2.2 schema and Alembic migration."""
import uuid
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from backend.app.db.session import engine

CANONICAL_21_TABLES = {
    "users",
    "customers",
    "facilities",
    "carriers",
    "carrier_equipment_types",
    "carrier_service_regions",
    "carrier_availability",
    "carrier_lane_rates",
    "shipments",
    "shipment_stops",
    "validation_runs",
    "intake_submissions",
    "recommendations",
    "recommendation_candidates",
    "approvals",
    "booking_proposals",
    "workflow_executions",
    "audit_events",
    "scoring_configs",
    "idempotency_keys",
    "llm_invocations",
}


def test_all_21_canonical_tables_exist():
    """Assert that all 21 canonical tables (and alembic_version) exist in the public schema."""
    with engine.connect() as conn:
        res = conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE';"
            )
        )
        existing_tables = {row[0] for row in res.fetchall()}

    assert "alembic_version" in existing_tables
    missing_tables = CANONICAL_21_TABLES - existing_tables
    assert not missing_tables, f"Missing canonical tables in database: {missing_tables}"
    print(f"Verified all {len(CANONICAL_21_TABLES)} canonical tables exist.")


def test_primary_keys_and_data_types():
    """Assert that each canonical table has a primary key named 'id' with expected types."""
    with engine.connect() as conn:
        for table in CANONICAL_21_TABLES:
            pk_res = conn.execute(
                text(
                    "SELECT c.column_name, c.data_type "
                    "FROM information_schema.table_constraints tc "
                    "JOIN information_schema.constraint_column_usage ccu "
                    "  ON tc.constraint_name = ccu.constraint_name "
                    "JOIN information_schema.columns c "
                    "  ON c.table_name = tc.table_name AND c.column_name = ccu.column_name "
                    "WHERE tc.constraint_type = 'PRIMARY KEY' "
                    "  AND tc.table_schema = 'public' "
                    "  AND tc.table_name = :tbl;"
                ),
                {"tbl": table},
            ).fetchall()

            assert len(pk_res) == 1, f"Table {table} does not have exactly 1 PK column (got {pk_res})"
            col_name, data_type = pk_res[0]
            assert col_name == "id", f"Table {table} PK is named '{col_name}', expected 'id'"

            if table == "audit_events":
                assert data_type == "bigint", f"audit_events.id must be bigint (got {data_type})"
            else:
                assert data_type == "uuid", f"{table}.id must be uuid (got {data_type})"


def test_circular_foreign_keys():
    """Assert that the circular FK between shipments and intake_submissions is present."""
    with engine.connect() as conn:
        fks = conn.execute(
            text(
                "SELECT tc.table_name, kcu.column_name, ccu.table_name AS foreign_table_name, ccu.column_name AS foreign_column_name "
                "FROM information_schema.table_constraints AS tc "
                "JOIN information_schema.key_column_usage AS kcu "
                "  ON tc.constraint_name = kcu.constraint_name "
                "JOIN information_schema.constraint_column_usage AS ccu "
                "  ON ccu.constraint_name = tc.constraint_name "
                "WHERE tc.constraint_type = 'FOREIGN KEY' "
                "  AND tc.table_name IN ('shipments', 'intake_submissions');"
            )
        ).fetchall()

    fk_map = {(row[0], row[1]): (row[2], row[3]) for row in fks}
    # shipments.intake_submission_id -> intake_submissions.id
    assert ("shipments", "intake_submission_id") in fk_map
    assert fk_map[("shipments", "intake_submission_id")] == ("intake_submissions", "id")

    # intake_submissions.shipment_id -> shipments.id
    assert ("intake_submissions", "shipment_id") in fk_map
    assert fk_map[("intake_submissions", "shipment_id")] == ("shipments", "id")


def test_partial_unique_indexes_exist():
    """Verify that all required partial unique indexes exist in PostgreSQL."""
    with engine.connect() as conn:
        res = conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE schemaname = 'public' "
                "  AND indexname IN ("
                "    'uq_carrier_lane_rates_active', "
                "    'uq_scoring_configs_active', "
                "    'uq_booking_proposals_active_shipment', "
                "    'uq_audit_events_idempotency_key'"
                "  );"
            )
        ).fetchall()

    found_indexes = {row[0]: row[1] for row in res}
    assert "uq_carrier_lane_rates_active" in found_indexes
    assert "uq_scoring_configs_active" in found_indexes
    assert "uq_booking_proposals_active_shipment" in found_indexes
    assert "uq_audit_events_idempotency_key" in found_indexes

    # Verify partial WHERE conditions
    assert "is_active = true" in found_indexes["uq_scoring_configs_active"]
    assert "is_active = true" in found_indexes["uq_carrier_lane_rates_active"]
    assert "proposed" in found_indexes["uq_booking_proposals_active_shipment"] and "accepted" in found_indexes["uq_booking_proposals_active_shipment"]
    assert "idempotency_key IS NOT NULL" in found_indexes["uq_audit_events_idempotency_key"]


def test_scoring_config_partial_unique_enforcement():
    """Verify that uq_scoring_configs_active prevents multiple active configs while allowing multiple inactive."""
    with engine.connect() as conn:
        with conn.begin():
            # Isolate the test from any active config created by application seeding.
            conn.execute(text("UPDATE scoring_configs SET is_active = false"))
            next_version = (
                conn.execute(text("SELECT COALESCE(MAX(version), 0) + 1 FROM scoring_configs")).scalar()
                or 1
            )

            # Insert first active config
            conn.execute(
                text(
                    "INSERT INTO scoring_configs (id, version, name, weights, is_active) "
                    "VALUES (gen_random_uuid(), :v1, 'Default v1', '{\"rate_competitiveness\": 0.3}', true);"
                ),
                {"v1": next_version},
            )

            # Insert an inactive config (should succeed)
            conn.execute(
                text(
                    "INSERT INTO scoring_configs (id, version, name, weights, is_active) "
                    "VALUES (gen_random_uuid(), :v2, 'Candidate v2', '{\"rate_competitiveness\": 0.4}', false);"
                ),
                {"v2": next_version + 1},
            )

            # Attempting to insert second active config must raise unique violation
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO scoring_configs (id, version, name, weights, is_active) "
                        "VALUES (gen_random_uuid(), :v3, 'Conflict v3', '{\"rate_competitiveness\": 0.5}', true);"
                    ),
                    {"v3": next_version + 2},
                )


def test_audit_events_immutability_trigger():
    """Verify that the trigger blocks UPDATE and DELETE on audit_events."""
    # 1. Verify UPDATE is blocked
    with engine.connect() as conn:
        with conn.begin():
            insert_res = conn.execute(
                text(
                    "INSERT INTO audit_events ("
                    "  event_type, actor_type, trace_id, payload, created_at"
                    ") VALUES ("
                    "  'workflow.started', 'system', 'test-trace-123', '{\"step\": 1}'::jsonb, NOW()"
                    ") RETURNING id;"
                )
            )
            event_id = insert_res.scalar()
            assert event_id is not None

            with pytest.raises(DBAPIError) as update_exc:
                conn.execute(
                    text("UPDATE audit_events SET trace_id = 'tampered' WHERE id = :id;"),
                    {"id": event_id},
                )
            assert "audit_events is append-only: UPDATE and DELETE are prohibited" in str(update_exc.value)

    # 2. Verify DELETE is blocked (in fresh transaction)
    with engine.connect() as conn:
        with conn.begin():
            insert_res = conn.execute(
                text(
                    "INSERT INTO audit_events ("
                    "  event_type, actor_type, trace_id, payload, created_at"
                    ") VALUES ("
                    "  'workflow.started', 'system', 'test-trace-456', '{\"step\": 1}'::jsonb, NOW()"
                    ") RETURNING id;"
                )
            )
            event_id = insert_res.scalar()
            assert event_id is not None

            with pytest.raises(DBAPIError) as delete_exc:
                conn.execute(
                    text("DELETE FROM audit_events WHERE id = :id;"),
                    {"id": event_id},
                )
            assert "audit_events is append-only: UPDATE and DELETE are prohibited" in str(delete_exc.value)


def test_audit_insert_succeeds_and_returns_id():
    """Verify that INSERT into audit_events succeeds, generates bigserial ID, and is queryable."""
    with engine.connect() as conn:
        with conn.begin():
            res = conn.execute(
                text(
                    "INSERT INTO audit_events ("
                    "  event_type, actor_type, trace_id, payload, created_at"
                    ") VALUES ("
                    "  'shipment.created', 'system', 'trace-audit-001', '{\"test\": true}'::jsonb, NOW()"
                    ") RETURNING id, event_type, actor_type, trace_id;"
                )
            )
            row = res.fetchone()
            assert row is not None
            assert row[0] is not None and isinstance(row[0], int)
            assert row[1] == "shipment.created"
            assert row[2] == "system"
            assert row[3] == "trace-audit-001"


def test_audit_idempotency_key_duplicate_rejected():
    """Verify that uq_audit_events_idempotency_key rejects duplicate non-null keys but allows NULLs."""
    test_key = f"audit-test-key-{uuid.uuid4()}"
    with engine.connect() as conn:
        with conn.begin():
            # 1. Insert first event with test_key
            conn.execute(
                text(
                    "INSERT INTO audit_events ("
                    "  event_type, actor_type, trace_id, idempotency_key, payload, created_at"
                    ") VALUES ("
                    "  'workflow.started', 'system', 'trace-audit-002', :key, '{\"n\": 1}'::jsonb, NOW()"
                    ");"
                ),
                {"key": test_key},
            )

            # 2. Duplicate insert with same key must raise IntegrityError
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO audit_events ("
                        "  event_type, actor_type, trace_id, idempotency_key, payload, created_at"
                        ") VALUES ("
                        "  'workflow.completed', 'system', 'trace-audit-003', :key, '{\"n\": 2}'::jsonb, NOW()"
                        ");"
                    ),
                    {"key": test_key},
                )

    # 3. Multiple NULL keys are permitted
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text(
                    "INSERT INTO audit_events (event_type, actor_type, trace_id, idempotency_key, payload, created_at) "
                    "VALUES ('workflow.started', 'system', 'trace-audit-004', NULL, '{\"n\": 1}'::jsonb, NOW()), "
                    "       ('workflow.started', 'system', 'trace-audit-005', NULL, '{\"n\": 2}'::jsonb, NOW());"
                )
            )


def test_booking_proposal_active_partial_unique():
    """Verify uq_booking_proposals_active_shipment prevents multiple 'proposed'/'accepted' proposals for same shipment."""
    with engine.connect() as conn:
        with conn.begin():
            # Create prerequisite shipment, carrier, approval
            shipment_id = conn.execute(
                text("INSERT INTO shipments (status, source) VALUES ('draft', 'manual') RETURNING id;")
            ).scalar()
            carrier_id = conn.execute(
                text(
                    "INSERT INTO carriers (legal_name, status) VALUES ('Test Carrier Inc', 'active') RETURNING id;"
                )
            ).scalar()
            scoring_config_id = conn.execute(
                text(
                    "INSERT INTO scoring_configs (version, name, weights, is_active) "
                    "VALUES (999, 'Test Config', '{}'::jsonb, false) RETURNING id;"
                )
            ).scalar()
            rec_id = conn.execute(
                text(
                    "INSERT INTO recommendations (shipment_id, status, scoring_config_id, config_version, explanation_template) "
                    "VALUES (:s_id, 'ready', :sc_id, 1, 'Template') RETURNING id;"
                ),
                {"s_id": shipment_id, "sc_id": scoring_config_id},
            ).scalar()
            approval_1 = conn.execute(
                text(
                    "INSERT INTO approvals (shipment_id, recommendation_id, status) "
                    "VALUES (:s_id, :r_id, 'pending') RETURNING id;"
                ),
                {"s_id": shipment_id, "r_id": rec_id},
            ).scalar()
            approval_2 = conn.execute(
                text(
                    "INSERT INTO approvals (shipment_id, recommendation_id, status) "
                    "VALUES (:s_id, :r_id, 'pending') RETURNING id;"
                ),
                {"s_id": shipment_id, "r_id": rec_id},
            ).scalar()

            # Insert first proposed proposal
            conn.execute(
                text(
                    "INSERT INTO booking_proposals (shipment_id, approval_id, carrier_id, proposal_number, status, snapshot) "
                    "VALUES (:s_id, :a_id, :c_id, 'BP-TEST-001', 'proposed', '{}'::jsonb);"
                ),
                {"s_id": shipment_id, "a_id": approval_1, "c_id": carrier_id},
            )

            # Insert second proposed proposal for SAME shipment must fail
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO booking_proposals (shipment_id, approval_id, carrier_id, proposal_number, status, snapshot) "
                        "VALUES (:s_id, :a_id, :c_id, 'BP-TEST-002', 'proposed', '{}'::jsonb);"
                    ),
                    {"s_id": shipment_id, "a_id": approval_2, "c_id": carrier_id},
                )


def test_carrier_lane_rates_active_partial_unique():
    """Verify uq_carrier_lane_rates_active prevents multiple active rates for same carrier, lane, and equipment."""
    with engine.connect() as conn:
        with conn.begin():
            carrier_id = conn.execute(
                text("INSERT INTO carriers (legal_name, status) VALUES ('Lane Carrier', 'active') RETURNING id;")
            ).scalar()

            # First active rate
            conn.execute(
                text(
                    "INSERT INTO carrier_lane_rates (carrier_id, origin_region, destination_region, "
                    "equipment_type, flat_rate, is_active) "
                    "VALUES (:cid, 'CA', 'TX', 'dry_van', 2500.00, true);"
                ),
                {"cid": carrier_id},
            )

            # Inactive rate on same lane allowed
            conn.execute(
                text(
                    "INSERT INTO carrier_lane_rates (carrier_id, origin_region, destination_region, "
                    "equipment_type, flat_rate, is_active) "
                    "VALUES (:cid, 'CA', 'TX', 'dry_van', 2400.00, false);"
                ),
                {"cid": carrier_id},
            )

            # Second active rate on same lane must raise IntegrityError
            with pytest.raises(IntegrityError):
                conn.execute(
                    text(
                        "INSERT INTO carrier_lane_rates (carrier_id, origin_region, destination_region, "
                        "equipment_type, flat_rate, is_active) "
                        "VALUES (:cid, 'CA', 'TX', 'dry_van', 2600.00, true);"
                    ),
                    {"cid": carrier_id},
                )


def test_shipment_draft_nullability_and_defaults():
    """Verify DEF-01 draft tolerance: shipment can be created with customer_id=NULL, facilities=NULL, equipment=NULL."""
    with engine.connect() as conn:
        with conn.begin():
            res = conn.execute(
                text(
                    "INSERT INTO shipments ("
                    "  status, source, customer_id, origin_facility_id, destination_facility_id, equipment_type"
                    ") VALUES ("
                    "  'draft', 'manual', NULL, NULL, NULL, NULL"
                    ") RETURNING id, status, source, version, currency, created_at;"
                )
            )
            row = res.fetchone()
            assert row is not None
            assert row[0] is not None
            assert row[1] == "draft"  # Default status
            assert row[2] == "manual"
            assert row[3] == 1  # Default version
            assert row[4] == "USD"  # Default currency
            assert row[5] is not None  # created_at populated by server default


def test_declarative_models_metadata_registration():
    """Verify that all 21 canonical models are registered in Base.metadata."""
    from backend.app.models import (
        Base,
        User,
        Customer,
        Facility,
        Carrier,
        CarrierEquipmentType,
        CarrierServiceRegion,
        CarrierAvailability,
        CarrierLaneRate,
        Shipment,
        ShipmentStop,
        ValidationRun,
        IntakeSubmission,
        Recommendation,
        RecommendationCandidate,
        Approval,
        BookingProposal,
        WorkflowExecution,
        AuditEvent,
        ScoringConfig,
        IdempotencyKey,
        LLMInvocation,
    )
    assert len(Base.metadata.tables) == 21
    for table_name in CANONICAL_21_TABLES:
        assert table_name in Base.metadata.tables, f"{table_name} missing from Base.metadata"



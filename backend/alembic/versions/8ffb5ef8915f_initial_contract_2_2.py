"""initial_contract_2_2

Revision ID: 8ffb5ef8915f
Revises: 
Create Date: 2026-11-25 12:58:22.819160

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '8ffb5ef8915f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # -------------------------------------------------------------------------
    # LEVEL 0: Independent Root Tables
    # -------------------------------------------------------------------------
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('email', sa.String(), nullable=False),
        sa.Column('password_hash', sa.String(), nullable=False),
        sa.Column('display_name', sa.String(), nullable=False),
        sa.Column('role', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("role IN ('admin', 'broker', 'viewer')", name='chk_users_role'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_users_email'), 'users', ['email'], unique=True)

    op.create_table(
        'customers',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('reference_code', sa.String(), nullable=False),
        sa.Column('contact_name', sa.String(), nullable=True),
        sa.Column('contact_email', sa.String(), nullable=True),
        sa.Column('contact_phone', sa.String(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_customers_reference_code'), 'customers', ['reference_code'], unique=True)

    op.create_table(
        'carriers',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('legal_name', sa.String(), nullable=False),
        sa.Column('dba_name', sa.String(), nullable=True),
        sa.Column('mc_number', sa.String(), nullable=True),
        sa.Column('dot_number', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('authority_status_recorded', sa.String(), nullable=True),
        sa.Column('insurance_expiry_date', sa.Date(), nullable=True),
        sa.Column('hazmat_authorized', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('temperature_capable', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('primary_contact_name', sa.String(), nullable=True),
        sa.Column('primary_contact_email', sa.String(), nullable=True),
        sa.Column('primary_contact_phone', sa.String(), nullable=True),
        sa.Column('data_source', sa.String(), server_default=sa.text("'synthetic'"), nullable=False),
        sa.Column('last_verified_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('active', 'inactive', 'suspended')", name='chk_carriers_status'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_carriers_dot_number'), 'carriers', ['dot_number'], unique=False)
    op.create_index(op.f('ix_carriers_mc_number'), 'carriers', ['mc_number'], unique=False)
    op.create_index(op.f('ix_carriers_status'), 'carriers', ['status'], unique=False)

    op.create_table(
        'scoring_configs',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('weights', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('activated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('version')
    )
    op.create_index(
        'uq_scoring_configs_active',
        'scoring_configs',
        ['is_active'],
        unique=True,
        postgresql_where=sa.text('is_active = true')
    )

    op.create_table(
        'idempotency_keys',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('key', sa.String(), nullable=False),
        sa.Column('endpoint', sa.String(), nullable=False),
        sa.Column('request_hash', sa.String(), nullable=False),
        sa.Column('status', sa.String(), server_default=sa.text("'in_progress'"), nullable=False),
        sa.Column('response_status', sa.Integer(), nullable=True),
        sa.Column('response_body', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('in_progress', 'completed', 'failed')", name='chk_idempotency_keys_status'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_idempotency_keys_created_at'), 'idempotency_keys', ['created_at'], unique=False)
    op.create_index(op.f('ix_idempotency_keys_key'), 'idempotency_keys', ['key'], unique=True)

    # -------------------------------------------------------------------------
    # LEVEL 1: Facility & Carrier Sub-Entities
    # -------------------------------------------------------------------------
    op.create_table(
        'facilities',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('code', sa.String(), nullable=True),
        sa.Column('facility_type', sa.String(), server_default=sa.text("'warehouse'"), nullable=False),
        sa.Column('address_line1', sa.String(), nullable=False),
        sa.Column('address_line2', sa.String(), nullable=True),
        sa.Column('city', sa.String(), nullable=False),
        sa.Column('state', sa.String(), nullable=False),
        sa.Column('postal_code', sa.String(), nullable=False),
        sa.Column('country', sa.String(), server_default=sa.text("'US'"), nullable=False),
        sa.Column('timezone', sa.String(), server_default=sa.text("'UTC'"), nullable=False),
        sa.Column('contact_name', sa.String(), nullable=True),
        sa.Column('contact_email', sa.String(), nullable=True),
        sa.Column('contact_phone', sa.String(), nullable=True),
        sa.Column('operating_hours', sa.String(), nullable=True),
        sa.Column('appointment_required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("facility_type IN ('warehouse', 'plant', 'distribution_center', 'cross_dock', 'cold_storage', 'other')", name='chk_facilities_type'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_facilities_code'), 'facilities', ['code'], unique=True)
    op.create_index(op.f('ix_facilities_customer_id'), 'facilities', ['customer_id'], unique=False)

    op.create_table(
        'carrier_equipment_types',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('carrier_id', sa.UUID(), nullable=False),
        sa.Column('equipment_type', sa.String(), nullable=False),
        sa.Column('max_weight_lbs', sa.Integer(), nullable=True),
        sa.Column('trailer_lengths_ft', sa.ARRAY(sa.Integer()), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("equipment_type IN ('dry_van', 'reefer', 'flatbed')", name='chk_carrier_equipment_type'),
        sa.CheckConstraint('max_weight_lbs IS NULL OR max_weight_lbs > 0', name='chk_carrier_equipment_max_weight'),
        sa.ForeignKeyConstraint(['carrier_id'], ['carriers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('carrier_id', 'equipment_type', name='uq_carrier_equipment_type')
    )
    op.create_index(op.f('ix_carrier_equipment_types_carrier_id'), 'carrier_equipment_types', ['carrier_id'], unique=False)

    op.create_table(
        'carrier_service_regions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('carrier_id', sa.UUID(), nullable=False),
        sa.Column('region_type', sa.String(), nullable=False),
        sa.Column('region_value', sa.String(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("region_type IN ('state', 'metro', 'radius_miles', 'postal_prefix')", name='chk_carrier_service_region_type'),
        sa.ForeignKeyConstraint(['carrier_id'], ['carriers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('carrier_id', 'region_type', 'region_value', name='uq_carrier_service_region')
    )
    op.create_index(op.f('ix_carrier_service_regions_carrier_id'), 'carrier_service_regions', ['carrier_id'], unique=False)

    op.create_table(
        'carrier_availability',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('carrier_id', sa.UUID(), nullable=False),
        sa.Column('available_from', sa.DateTime(timezone=True), nullable=False),
        sa.Column('available_until', sa.DateTime(timezone=True), nullable=False),
        sa.Column('origin_region', sa.String(), nullable=True),
        sa.Column('destination_region', sa.String(), nullable=True),
        sa.Column('equipment_type', sa.String(), nullable=True),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('available_until > available_from', name='chk_carrier_availability_dates'),
        sa.ForeignKeyConstraint(['carrier_id'], ['carriers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_carrier_availability_carrier_id'), 'carrier_availability', ['carrier_id'], unique=False)

    op.create_table(
        'carrier_lane_rates',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('carrier_id', sa.UUID(), nullable=False),
        sa.Column('origin_region', sa.String(), nullable=False),
        sa.Column('destination_region', sa.String(), nullable=False),
        sa.Column('equipment_type', sa.String(), nullable=False),
        sa.Column('flat_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('rate_per_mile', sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column('min_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=3), server_default=sa.text("'USD'"), nullable=False),
        sa.Column('source', sa.String(), server_default=sa.text("'synthetic'"), nullable=False),
        sa.Column('effective_date', sa.Date(), nullable=True),
        sa.Column('expiration_date', sa.Date(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("equipment_type IN ('dry_van', 'reefer', 'flatbed')", name='chk_carrier_lane_rates_equipment'),
        sa.CheckConstraint('flat_rate IS NOT NULL OR rate_per_mile IS NOT NULL', name='chk_lane_rates_has_rate'),
        sa.CheckConstraint('flat_rate IS NULL OR flat_rate >= 0', name='chk_carrier_lane_rates_flat_rate'),
        sa.CheckConstraint('min_rate IS NULL OR min_rate >= 0', name='chk_carrier_lane_rates_min_rate'),
        sa.CheckConstraint('rate_per_mile IS NULL OR rate_per_mile >= 0', name='chk_carrier_lane_rates_rate_per_mile'),
        sa.ForeignKeyConstraint(['carrier_id'], ['carriers.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_carrier_lane_rates_carrier_id'), 'carrier_lane_rates', ['carrier_id'], unique=False)
    op.create_index(
        'uq_carrier_lane_rates_active',
        'carrier_lane_rates',
        ['carrier_id', 'origin_region', 'destination_region', 'equipment_type'],
        unique=True,
        postgresql_where=sa.text('is_active = true')
    )

    # -------------------------------------------------------------------------
    # LEVEL 2: Core Aggregate, Stops, Intake, and Workflow Executions
    # Note: Circular FK between shipments & intake_submissions is handled by
    # creating shipments without the intake_submission_id FK, creating intake_submissions,
    # and then adding the foreign key constraint.
    # -------------------------------------------------------------------------
    op.create_table(
        'shipments',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('customer_id', sa.UUID(), nullable=True),
        sa.Column('origin_facility_id', sa.UUID(), nullable=True),
        sa.Column('destination_facility_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('source', sa.String(), nullable=False),
        sa.Column('intake_submission_id', sa.UUID(), nullable=True),
        sa.Column('reference_number', sa.String(), nullable=True),
        sa.Column('po_number', sa.String(), nullable=True),
        sa.Column('commodity', sa.String(), nullable=True),
        sa.Column('equipment_type', sa.String(), nullable=True),
        sa.Column('weight_lbs', sa.Integer(), nullable=True),
        sa.Column('target_sell_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('max_buy_rate', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('currency', sa.String(length=3), server_default=sa.text("'USD'"), nullable=False),
        sa.Column('lane_origin', sa.String(), nullable=True),
        sa.Column('lane_destination', sa.String(), nullable=True),
        sa.Column('requirements', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('notes', sa.String(), nullable=True),
        sa.Column('version', sa.Integer(), server_default=sa.text('1'), nullable=False),
        sa.Column('frozen_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("equipment_type IS NULL OR equipment_type IN ('dry_van', 'reefer', 'flatbed')", name='chk_shipments_equipment_type'),
        sa.CheckConstraint("source IN ('intake_submission', 'manual')", name='chk_shipments_source'),
        sa.CheckConstraint("status IN ('draft', 'intake_received', 'validation_failed', 'validated', 'sourcing', 'recommendation_ready', 'pending_approval', 'approved', 'booking_proposed', 'booked', 'cancelled', 'closed')", name='chk_shipments_status'),
        sa.CheckConstraint('max_buy_rate IS NULL OR max_buy_rate >= 0', name='chk_shipments_max_buy_rate'),
        sa.CheckConstraint('target_sell_rate IS NULL OR target_sell_rate >= 0', name='chk_shipments_target_sell_rate'),
        sa.CheckConstraint('weight_lbs IS NULL OR weight_lbs > 0', name='chk_shipments_weight_lbs'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['customer_id'], ['customers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['destination_facility_id'], ['facilities.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['origin_facility_id'], ['facilities.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('intake_submission_id')
    )
    op.create_index(op.f('ix_shipments_customer_id'), 'shipments', ['customer_id'], unique=False)
    op.create_index(op.f('ix_shipments_status'), 'shipments', ['status'], unique=False)

    op.create_table(
        'intake_submissions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('channel', sa.String(), nullable=False),
        sa.Column('raw_text', sa.String(), nullable=False),
        sa.Column('content_hash', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('submitter_id', sa.UUID(), nullable=True),
        sa.Column('shipment_id', sa.UUID(), nullable=True),
        sa.Column('parse_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('extracted_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('extraction_error', sa.String(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("channel IN ('paste', 'upload', 'rest_api', 'manual')", name='chk_intake_submissions_channel'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['submitter_id'], ['users.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shipment_id')
    )
    op.create_index(op.f('ix_intake_submissions_content_hash'), 'intake_submissions', ['content_hash'], unique=True)
    op.create_index(op.f('ix_intake_submissions_idempotency_key'), 'intake_submissions', ['idempotency_key'], unique=True)

    # Attach the deferred foreign key constraint from shipments to intake_submissions
    op.create_foreign_key(
        'fk_shipments_intake_submission_id',
        'shipments',
        'intake_submissions',
        ['intake_submission_id'],
        ['id'],
        ondelete='RESTRICT',
    )

    op.create_table(
        'shipment_stops',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('shipment_id', sa.UUID(), nullable=False),
        sa.Column('facility_id', sa.UUID(), nullable=True),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('stop_type', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('address_line1', sa.String(), nullable=True),
        sa.Column('address_line2', sa.String(), nullable=True),
        sa.Column('city', sa.String(), nullable=True),
        sa.Column('state', sa.String(), nullable=True),
        sa.Column('postal_code', sa.String(), nullable=True),
        sa.Column('country', sa.String(), server_default=sa.text("'US'"), nullable=False),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('appointment_required', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('contact_name', sa.String(), nullable=True),
        sa.Column('contact_phone', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("stop_type IN ('pickup', 'delivery')", name='chk_shipment_stops_type'),
        sa.CheckConstraint('sequence >= 1', name='chk_shipment_stops_sequence'),
        sa.ForeignKeyConstraint(['facility_id'], ['facilities.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('shipment_id', 'sequence', name='uq_shipment_stops_sequence')
    )
    op.create_index(op.f('ix_shipment_stops_shipment_id'), 'shipment_stops', ['shipment_id'], unique=False)

    op.create_table(
        'workflow_executions',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('shipment_id', sa.UUID(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('current_node', sa.String(), nullable=True),
        sa.Column('graph_version', sa.String(), server_default=sa.text("'1.0'"), nullable=False),
        sa.Column('state', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('attempt_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('max_attempt_count', sa.Integer(), server_default=sa.text('3'), nullable=False),
        sa.Column('cumulative_compute_seconds', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('llm_call_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('node_execution_count', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('lease_token', sa.UUID(), nullable=True),
        sa.Column('lease_epoch', sa.Integer(), server_default=sa.text('0'), nullable=False),
        sa.Column('lease_owner', sa.String(), nullable=True),
        sa.Column('lease_expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('error_message', sa.String(), nullable=True),
        sa.Column('trace_id', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('attempt_started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint(
            "current_node IS NULL OR current_node IN ("
            "'start_execution', 'load_shipment', 'validate_shipment', 'decide_validation_outcome', "
            "'normalize_requirements', 'resolve_carrier_candidates', 'filter_eligible_carriers', "
            "'score_candidates', 'generate_explanation', 'persist_recommendation', "
            "'request_human_approval', 'apply_human_decision', 'create_booking_proposal', "
            "'record_audit_event', 'finalize_execution', 'handle_failure')",
            name='chk_workflow_executions_current_node'
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'waiting_for_human', 'resumption_pending', 'completed', 'failed', 'cancelled', 'timed_out')",
            name='chk_workflow_executions_status'
        ),
        sa.CheckConstraint('cumulative_compute_seconds >= 0 AND cumulative_compute_seconds <= 900', name='chk_workflow_executions_compute_budget'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key')
    )
    op.create_index('idx_workflow_executions_lease', 'workflow_executions', ['lease_expires_at'], unique=False)
    op.create_index('idx_workflow_executions_trace', 'workflow_executions', ['trace_id'], unique=False)
    op.create_index(op.f('ix_workflow_executions_shipment_id'), 'workflow_executions', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_workflow_executions_status'), 'workflow_executions', ['status'], unique=False)

    # -------------------------------------------------------------------------
    # LEVEL 3: Validation Runs, Recommendations, and LLM Telemetry
    # -------------------------------------------------------------------------
    op.create_table(
        'validation_runs',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('shipment_id', sa.UUID(), nullable=False),
        sa.Column('result', sa.String(), nullable=False),
        sa.Column('issues', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column('rules_version', sa.String(), nullable=False),
        sa.Column('triggered_by_user_id', sa.UUID(), nullable=True),
        sa.Column('workflow_execution_id', sa.UUID(), nullable=True),
        sa.Column('checked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("result IN ('passed', 'passed_with_warnings', 'failed')", name='chk_validation_runs_result'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['triggered_by_user_id'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_validation_runs_shipment_checked', 'validation_runs', ['shipment_id', sa.literal_column('checked_at DESC')], unique=False)
    op.create_index(op.f('ix_validation_runs_shipment_id'), 'validation_runs', ['shipment_id'], unique=False)

    op.create_table(
        'llm_invocations',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('workflow_execution_id', sa.UUID(), nullable=True),
        sa.Column('operation', sa.String(), nullable=False),
        sa.Column('provider', sa.String(), server_default=sa.text("'mock'"), nullable=False),
        sa.Column('model_identifier', sa.String(), nullable=True),
        sa.Column('prompt_tokens', sa.Integer(), nullable=True),
        sa.Column('completion_tokens', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('error_code', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("operation IN ('extract_shipment_fields', 'narrate_explanation')", name='chk_llm_invocations_operation'),
        sa.CheckConstraint("status IN ('success', 'error')", name='chk_llm_invocations_status'),
        sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_llm_invocations_operation'), 'llm_invocations', ['operation'], unique=False)
    op.create_index(op.f('ix_llm_invocations_workflow_execution_id'), 'llm_invocations', ['workflow_execution_id'], unique=False)

    op.create_table(
        'recommendations',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('shipment_id', sa.UUID(), nullable=False),
        sa.Column('workflow_execution_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('scoring_config_id', sa.UUID(), nullable=False),
        sa.Column('config_version', sa.Integer(), nullable=False),
        sa.Column('explanation_template', sa.String(), nullable=False),
        sa.Column('explanation_narration', sa.String(), nullable=True),
        sa.Column('explanation_provider', sa.String(), nullable=True),
        sa.Column('superseded_by_id', sa.UUID(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'computing', 'ready', 'no_eligible_carriers', 'failed', 'superseded')", name='chk_recommendations_status'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['scoring_config_id'], ['scoring_configs.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['superseded_by_id'], ['recommendations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('workflow_execution_id')
    )
    op.create_index(op.f('ix_recommendations_shipment_id'), 'recommendations', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_recommendations_status'), 'recommendations', ['status'], unique=False)

    # -------------------------------------------------------------------------
    # LEVEL 4: Candidates & Approvals
    # -------------------------------------------------------------------------
    op.create_table(
        'recommendation_candidates',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('recommendation_id', sa.UUID(), nullable=False),
        sa.Column('carrier_id', sa.UUID(), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('eligibility', sa.String(), nullable=False),
        sa.Column('ineligibility_codes', sa.ARRAY(sa.String()), server_default=sa.text("'{}'"), nullable=False),
        sa.Column('component_scores', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('total_score', sa.Numeric(precision=6, scale=4), nullable=True),
        sa.Column('rate_quote', sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column('explanation', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("eligibility IN ('eligible', 'ineligible', 'insufficient_data')", name='chk_candidates_eligibility'),
        sa.CheckConstraint('rate_quote IS NULL OR rate_quote >= 0', name='chk_candidates_rate_quote'),
        sa.CheckConstraint('total_score IS NULL OR (total_score >= 0 AND total_score <= 1)', name='chk_candidates_total_score'),
        sa.ForeignKeyConstraint(['carrier_id'], ['carriers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('recommendation_id', 'carrier_id', name='uq_recommendation_candidates_carrier')
    )
    op.create_index('idx_candidates_recommendation_rank', 'recommendation_candidates', ['recommendation_id', 'rank'], unique=False)
    op.create_index(op.f('ix_recommendation_candidates_carrier_id'), 'recommendation_candidates', ['carrier_id'], unique=False)
    op.create_index(op.f('ix_recommendation_candidates_recommendation_id'), 'recommendation_candidates', ['recommendation_id'], unique=False)

    op.create_table(
        'approvals',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('recommendation_id', sa.UUID(), nullable=False),
        sa.Column('shipment_id', sa.UUID(), nullable=False),
        sa.Column('workflow_execution_id', sa.UUID(), nullable=True),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('requested_by', sa.UUID(), nullable=True),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('decided_by', sa.UUID(), nullable=True),
        sa.Column('decided_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('decision_comment', sa.String(), nullable=True),
        sa.Column('selected_candidate_id', sa.UUID(), nullable=True),
        sa.Column('resumed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'changes_requested', 'cancelled')", name='chk_approvals_status'),
        sa.CheckConstraint("status NOT IN ('approved', 'rejected', 'changes_requested') OR (decided_by IS NOT NULL AND decided_at IS NOT NULL)", name='chk_approvals_decision'),
        sa.ForeignKeyConstraint(['decided_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['requested_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['selected_candidate_id'], ['recommendation_candidates.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
        sa.UniqueConstraint('workflow_execution_id')
    )
    op.create_index(op.f('ix_approvals_shipment_id'), 'approvals', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_approvals_status'), 'approvals', ['status'], unique=False)
    op.create_index(op.f('ix_approvals_workflow_execution_id'), 'approvals', ['workflow_execution_id'], unique=True)

    # -------------------------------------------------------------------------
    # LEVEL 5: Booking Proposals & Audit Events
    # -------------------------------------------------------------------------
    op.create_table(
        'booking_proposals',
        sa.Column('id', sa.UUID(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('shipment_id', sa.UUID(), nullable=False),
        sa.Column('approval_id', sa.UUID(), nullable=False),
        sa.Column('carrier_id', sa.UUID(), nullable=False),
        sa.Column('proposal_number', sa.String(), nullable=False),
        sa.Column('status', sa.String(), nullable=False),
        sa.Column('snapshot', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status_reason', sa.String(), nullable=True),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('created_by', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("status IN ('proposed', 'accepted', 'declined', 'cancelled')", name='chk_booking_proposals_status'),
        sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['carrier_id'], ['carriers.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('approval_id'),
        sa.UniqueConstraint('idempotency_key'),
        sa.UniqueConstraint('proposal_number')
    )
    op.create_index(op.f('ix_booking_proposals_approval_id'), 'booking_proposals', ['approval_id'], unique=True)
    op.create_index(op.f('ix_booking_proposals_carrier_id'), 'booking_proposals', ['carrier_id'], unique=False)
    op.create_index(op.f('ix_booking_proposals_shipment_id'), 'booking_proposals', ['shipment_id'], unique=False)
    op.create_index(
        'uq_booking_proposals_active_shipment',
        'booking_proposals',
        ['shipment_id'],
        unique=True,
        postgresql_where=sa.text("status IN ('proposed', 'accepted')")
    )

    op.create_table(
        'audit_events',
        sa.Column('id', sa.BigInteger(), sa.Identity(always=False, start=1, increment=1), nullable=False),
        sa.Column('event_type', sa.String(), nullable=False),
        sa.Column('actor_type', sa.String(), nullable=False),
        sa.Column('actor_id', sa.UUID(), nullable=True),
        sa.Column('shipment_id', sa.UUID(), nullable=True),
        sa.Column('workflow_execution_id', sa.UUID(), nullable=True),
        sa.Column('recommendation_id', sa.UUID(), nullable=True),
        sa.Column('approval_id', sa.UUID(), nullable=True),
        sa.Column('booking_proposal_id', sa.UUID(), nullable=True),
        sa.Column('trace_id', sa.String(), nullable=False),
        sa.Column('idempotency_key', sa.String(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint("actor_type IN ('user', 'system', 'llm')", name='chk_audit_events_actor_type'),
        sa.CheckConstraint(
            "event_type IN ("
            "'shipment.created', 'shipment.updated', 'intake.received', 'intake.parsed', "
            "'validation.completed', 'validation.failed', 'recommendation.generated', "
            "'recommendation.superseded', 'approval.requested', 'approval.granted', "
            "'approval.rejected', 'approval.changes_requested', 'approval.cancelled', "
            "'booking_proposal.created', 'booking_proposal.status_changed', 'workflow.started', "
            "'workflow.paused_for_human', 'workflow.completed', 'workflow.failed', "
            "'llm.invoked', 'config.updated')",
            name='chk_audit_events_type'
        ),
        sa.ForeignKeyConstraint(['approval_id'], ['approvals.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['booking_proposal_id'], ['booking_proposals.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['recommendation_id'], ['recommendations.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['shipment_id'], ['shipments.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['workflow_execution_id'], ['workflow_executions.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_events_created_at'), 'audit_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_events_event_type'), 'audit_events', ['event_type'], unique=False)
    op.create_index(op.f('ix_audit_events_shipment_id'), 'audit_events', ['shipment_id'], unique=False)
    op.create_index(op.f('ix_audit_events_trace_id'), 'audit_events', ['trace_id'], unique=False)
    op.create_index(op.f('ix_audit_events_workflow_execution_id'), 'audit_events', ['workflow_execution_id'], unique=False)
    op.create_index(
        'uq_audit_events_idempotency_key',
        'audit_events',
        ['idempotency_key'],
        unique=True,
        postgresql_where=sa.text('idempotency_key IS NOT NULL')
    )

    # -------------------------------------------------------------------------
    # TRIGGER: Audit Events Immutability (F-SEC-03)
    # -------------------------------------------------------------------------
    op.execute("""
    CREATE OR REPLACE FUNCTION audit_events_immutable()
    RETURNS TRIGGER AS $$
    BEGIN
        RAISE EXCEPTION 'audit_events is append-only: UPDATE and DELETE are prohibited';
    END;
    $$ LANGUAGE plpgsql;
    """)

    op.execute("""
    CREATE TRIGGER trg_audit_events_immutable
    BEFORE UPDATE OR DELETE ON audit_events
    FOR EACH ROW EXECUTE FUNCTION audit_events_immutable();
    """)


def downgrade() -> None:
    # 1. Drop trigger and function
    op.execute("DROP TRIGGER IF EXISTS trg_audit_events_immutable ON audit_events;")
    op.execute("DROP FUNCTION IF EXISTS audit_events_immutable();")

    # 2. Drop partial unique indexes
    op.drop_index('uq_audit_events_idempotency_key', table_name='audit_events', postgresql_where=sa.text('idempotency_key IS NOT NULL'))
    op.drop_index('uq_booking_proposals_active_shipment', table_name='booking_proposals', postgresql_where=sa.text("status IN ('proposed', 'accepted')"))
    op.drop_index('uq_scoring_configs_active', table_name='scoring_configs', postgresql_where=sa.text('is_active = true'))
    op.drop_index('uq_carrier_lane_rates_active', table_name='carrier_lane_rates', postgresql_where=sa.text('is_active = true'))

    # 3. Drop circular foreign key constraint
    op.drop_constraint('fk_shipments_intake_submission_id', 'shipments', type_='foreignkey')

    # 4. Drop tables in reverse topological order
    op.drop_table('audit_events')
    op.drop_table('booking_proposals')
    op.drop_table('approvals')
    op.drop_table('recommendation_candidates')
    op.drop_table('recommendations')
    op.drop_table('llm_invocations')
    op.drop_table('validation_runs')
    op.drop_table('workflow_executions')
    op.drop_table('shipment_stops')
    op.drop_table('intake_submissions')
    op.drop_table('shipments')
    op.drop_table('carrier_lane_rates')
    op.drop_table('carrier_availability')
    op.drop_table('carrier_service_regions')
    op.drop_table('carrier_equipment_types')
    op.drop_table('facilities')
    op.drop_table('idempotency_keys')
    op.drop_table('scoring_configs')
    op.drop_table('carriers')
    op.drop_table('customers')
    op.drop_table('users')

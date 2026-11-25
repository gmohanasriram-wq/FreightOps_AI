"""Comprehensive PostgreSQL catalog verification script for Contract 2.2 schema."""
import json
import psycopg

from backend.app.core.config import settings

CONN_STR = settings.SQLALCHEMY_DATABASE_URI.replace("postgresql+psycopg://", "postgresql://", 1)

CANONICAL_21_TABLES = [
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
]


def run_catalog_audit():
    with psycopg.connect(CONN_STR) as conn:
        with conn.cursor() as cur:
            # 1. Check all tables exist in public schema
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
                ORDER BY table_name;
            """)
            existing_tables = [r[0] for r in cur.fetchall()]
            print(f"Total BASE TABLES in public: {len(existing_tables)}")
            missing = set(CANONICAL_21_TABLES) - set(existing_tables)
            if missing:
                print(f"FAILED: Missing tables: {missing}")
                return
            else:
                print("PASS: All 21 canonical tables present.")

            # 2. Check each table columns, types, nullability, defaults
            cur.execute("""
                SELECT table_name, column_name, data_type, udt_name, is_nullable, column_default
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = ANY(%s)
                ORDER BY table_name, ordinal_position;
            """, (CANONICAL_21_TABLES,))
            cols_by_table = {}
            for t, col, dt, udt, nullable, default in cur.fetchall():
                cols_by_table.setdefault(t, []).append({
                    "column": col,
                    "data_type": dt,
                    "udt_name": udt,
                    "nullable": nullable,
                    "default": default,
                })

            # 3. Check PKs
            cur.execute("""
                SELECT tc.table_name, c.column_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage c ON tc.constraint_name = c.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public' AND tc.table_name = ANY(%s);
            """, (CANONICAL_21_TABLES,))
            pks = {r[0]: r[1] for r in cur.fetchall()}

            # 4. Check FKs with on delete rules
            cur.execute("""
                SELECT
                    cl.relname AS source_table,
                    con.conname AS constraint_name,
                    att.attname AS source_column,
                    clf.relname AS target_table,
                    attf.attname AS target_column,
                    con.confdeltype AS on_delete_action
                FROM pg_constraint con
                JOIN pg_class cl ON con.conrelid = cl.oid
                JOIN pg_class clf ON con.confrelid = clf.oid
                JOIN pg_attribute att ON att.attrelid = con.conrelid AND att.attnum = con.conkey[1]
                JOIN pg_attribute attf ON attf.attrelid = con.confrelid AND attf.attnum = con.confkey[1]
                WHERE con.contype = 'f' AND cl.relname = ANY(%s)
                ORDER BY cl.relname, con.conname;
            """, (CANONICAL_21_TABLES,))
            fk_del_map = {'c': 'CASCADE', 'r': 'RESTRICT', 'a': 'NO ACTION', 'n': 'SET NULL', 'd': 'SET DEFAULT'}
            fks_by_table = {}
            for src_tbl, conname, src_col, tgt_tbl, tgt_col, deltype in cur.fetchall():
                fks_by_table.setdefault(src_tbl, []).append({
                    "name": conname,
                    "column": src_col,
                    "foreign_table": tgt_tbl,
                    "foreign_column": tgt_col,
                    "on_delete": fk_del_map.get(deltype, deltype)
                })

            # 5. Check constraints
            cur.execute("""
                SELECT tc.table_name, tc.constraint_name, cc.check_clause
                FROM information_schema.table_constraints tc
                JOIN information_schema.check_constraints cc ON tc.constraint_name = cc.constraint_name
                WHERE tc.constraint_type = 'CHECK' AND tc.table_schema = 'public' AND tc.table_name = ANY(%s)
                ORDER BY tc.table_name, tc.constraint_name;
            """, (CANONICAL_21_TABLES,))
            checks_by_table = {}
            for t, name, clause in cur.fetchall():
                checks_by_table.setdefault(t, []).append({"name": name, "clause": clause})

            # 6. Indexes & partial unique indexes
            cur.execute("""
                SELECT tablename, indexname, indexdef
                FROM pg_indexes
                WHERE schemaname = 'public' AND tablename = ANY(%s)
                ORDER BY tablename, indexname;
            """, (CANONICAL_21_TABLES,))
            indexes_by_table = {}
            for t, idx_name, idx_def in cur.fetchall():
                indexes_by_table.setdefault(t, []).append({"name": idx_name, "def": idx_def})

            # 7. Triggers on audit_events
            cur.execute("""
                SELECT trigger_name, event_manipulation, event_object_table, action_statement
                FROM information_schema.triggers
                WHERE event_object_table = 'audit_events';
            """)
            triggers = cur.fetchall()

            # Print Summary Matrix
            print("\n=== 21-TABLE POSTGRESQL CATALOG VERIFICATION MATRIX ===")
            for t in CANONICAL_21_TABLES:
                cols = cols_by_table.get(t, [])
                pk = pks.get(t, "NONE")
                fks = fks_by_table.get(t, [])
                checks = checks_by_table.get(t, [])
                idxs = indexes_by_table.get(t, [])
                print(f"\nTABLE: {t} (Columns: {len(cols)}, PK: {pk}, FKs: {len(fks)}, Checks: {len(checks)}, Indexes: {len(idxs)})")
                for c in cols:
                    def_str = f" DEFAULT {c['default']}" if c['default'] else ""
                    null_str = "NULL" if c['nullable'] == 'YES' else "NOT NULL"
                    print(f"  - {c['column']}: {c['udt_name']} {null_str}{def_str}")
                if fks:
                    print("  Foreign Keys:")
                    for fk in fks:
                        print(f"    * {fk['column']} -> {fk['foreign_table']}({fk['foreign_column']}) ON DELETE {fk['on_delete']}")
                if checks:
                    print("  Check Constraints:")
                    for chk in checks:
                        print(f"    * {chk['name']}: {chk['clause']}")
                if idxs:
                    print("  Indexes:")
                    for idx in idxs:
                        is_uniq = "UNIQUE " if "UNIQUE" in idx['def'] else ""
                        where_clause = ""
                        if "WHERE" in idx['def']:
                            where_clause = f" WHERE {idx['def'].split('WHERE')[1]}"
                        print(f"    * {idx['name']} ({is_uniq}INDEX){where_clause}")

            print("\n=== TRIGGERS ON audit_events ===")
            for trig in triggers:
                print(f"  * {trig[0]} on {trig[2]}: {trig[1]} -> {trig[3]}")

if __name__ == "__main__":
    run_catalog_audit()

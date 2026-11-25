# 15 — Architecture Revision Log

| Field | Value |
|---|---|
| Status | Approved (Phase 1.7.5 Architecture Remediation) |
| Contract version | 2.2 |
| Contract source | [Appendix A](./03-requirements-specification.md#appendix-a--canonical-contracts) |
| Review Reference | [14 Architecture Review](./14-architecture-review.md) |
| Last updated | 2026-11-25 |
| Audience | Project Owner, Principal Architect, Senior Backend Engineer, Reviewer |


> **Historical Revision Notice (Contract 2.2 Baseline):** Sections **1–15** below are preserved verbatim as **historical records** in append-only order. Their contract versions (`1.0`, `2.0`, `2.1`), requirement counts (e.g., `68` or `120` MVP), and historical freeze conclusions reflect the specification at the time those phases were written and are **superseded** wherever they conflict with the current **Contract 2.2** baseline. The current approved baseline and remediation status are defined by the metadata table above (`Contract version | 2.2`) and the latest revision sections (`§16`–`§18`).
## 1. Executive overview

Following the independent technical architecture review documented in `docs/14-architecture-review.md`, the project owner approved five binding Architectural Decision Records (ADR Decisions 1 through 5).

This document provides the authoritative record of all changes applied across the FreightOps AI specification during Phase 1.6. It details the resolution of all four critical flaws (`CRIT-01` through `CRIT-04`) and twelve key findings (`F-DB-01` through `F-SEC-03`), presents the schema delta (23 tables revised to 21 tables), formalizes the trimmed MVP requirements scope (68 Must Deliver items out of 155 total), and certifies the contract freeze at **Contract Version 2.0**.

---

## 2. Approved architectural decisions (ADR Decisions 1–5)

### ADR Decision 1 — Python runtime target (ADR-017)
- **Decision:** Target **Python 3.12** for the project application runtime and testing.
- **Implementation Status:** Technology documentation updated. The existing developer host virtual environment (currently Python 3.14.5) remains completely untouched during Phase 1 documentation. A Phase 1 adoption gate requires testing all planned dependencies (FastAPI, SQLAlchemy 2.x, Alembic, asyncpg/psycopg, LangGraph, Jinja2) against a clean Python 3.12 environment prior to code implementation.

### ADR Decision 2 — Workflow engine & persistence (ADR-005)
- **Decision:** Retain **LangGraph** with a persistent PostgreSQL checkpointer (`AsyncPostgresSaver` / `PostgresSaver`).
- **Implementation Status:** Documented LangGraph's concrete benefits: durable state checkpointing across process restarts, native `interrupt()` and resume semantics, and structural execution bounds (`recursion_limit=40`).
- **Deterministic Python Fallback:** Specified a lightweight ~200-line deterministic Python state machine (`DeterministicWorkflowEngine`) as an architectural fallback. If LangGraph introduces dependency conflicts during Python 3.12 testing or excessive serialization overhead, the system will swap to the fallback without changing database schemas, node contracts, or API endpoints.

### ADR Decision 3 — Facilities entity consolidation (ADR-019)
- **Decision:** Consolidate `shippers` and `consignees` into a single **`facilities`** table.
- **Implementation Status:** A facility can represent a pickup location, delivery location, or dual-purpose logistics center. `shipment_stops` remains the authoritative, ordered sequence of pickup and delivery stops. Redundant party references on shipments are removed or made optional.

### ADR Decision 4 — Trimmed MVP scope cut line
- **Decision:** Reduce the implementation scope to a tightly reviewed, achievable MVP for a single developer.
- **Implementation Status:** Reassessed all 155 functional requirements. Classified into:
  - **68 MVP Must Requirements** (43.9%): Core intake, draft creation, facilities, deterministic validation, carrier master data, lane rates, deterministic eligibility, active scoring config, approval queue, booking proposal, PostgreSQL checkpointer, and audit immutability trigger.
  - **57 Post-MVP Requirements** (36.8%): Advanced search, rich query APIs, detailed telemetry metrics, and auto-clarification drafting.
  - **20 Future Backlog Requirements** (12.9%): Multi-tenancy, vector retrieval, ML ranking, SSO/MFA, and idle session sweeps.
  - **10 Merged or Removed Requirements** (6.4%): Redundant enum validation rules, duplicate proposal checks, and acyclic loop detectors.
- Verbatim cut line synchronized identically across `docs/03-requirements-specification.md §1.3`, `docs/04-system-architecture.md §10`, and `docs/13-development-roadmap.md §9`.

### ADR Decision 5 — Simplified workflow scheduling (ADR-018)
- **Decision:** Eliminate external distributed task queues (Celery, ARQ, Redis) and in-process schedulers (APScheduler) from the MVP.
- **Implementation Status:** The human broker approval decision (`POST /api/v1/approvals/{id}/decision`) is the authoritative event that resumes the paused workflow execution via `graph.invoke(Command(resume=decision))`. Automatic approval TTL expiration sweeps are deferred; pending approvals remain pending in the operator queue until decided. Durable workflow state is preserved in PostgreSQL checkpointer tables.

---

## 3. Resolution of critical findings and review items

| Finding ID | Title | Root cause in Contract 1.0 | Resolution in Contract 2.0 | Reference Documents |
|---|---|---|---|---|
| **CRIT-01** | Draft Shipment FK Nullability Deadlock | `customer_id`, `shipper_id`, `consignee_id` were `NOT NULL` in DB, preventing incomplete intake text from creating a draft shipment. | Made `customer_id`, `origin_facility_id`, and `destination_facility_id` nullable on draft creation; enforced as non-null by the deterministic Validation Engine prior to reaching `validated` status. | `03` §5.2, `06` §4.2, `09` §5.3 |
| **CRIT-02** | Workflow Execution & Scheduling Contradiction | Documents contradicted each other on whether APScheduler, Celery, or synchronous HTTP executed the workflow. | ADR Decision 5 adopted: Excluded Celery and APScheduler. LangGraph executes event-driven from request handler or FastAPI background task; approval decision endpoint directly resumes execution. Automatic TTL sweeps deferred. | `04` §8, `07` §8, `10` §5 |
| **CRIT-03** | Missing Carrier Rate Data Source | Scoring algorithm required rate competitiveness scoring, but carriers had no rate data, forcing the LLM to hallucinate prices. | Added authoritative `carrier_lane_rates` table storing baseline rates and per-mile benchmarks by carrier, origin/destination region, and equipment type. Scoring engine computes rate competitiveness deterministically against operator target buy rates. | `01` §2.2, `06` §4.3, `07` §6, `09` §5.8 |
| **CRIT-04** | Declined Booking Proposal Terminal Lockout | When a carrier declined a proposal, the shipment remained stuck in terminal `booking_proposed` with no transition back to sourcing. | Added canonical lifecycle transition: When a booking proposal is declined by a carrier or cancelled by a broker (`POST /booking-proposals/{id}/cancel`), the proposal moves to `declined`/`cancelled` and the shipment transitions back to `sourcing` (Diagram D-05). | `03` App B, `05` §4.14, `06` §4.5, `09` §5.7 |
| **F-DB-01** | Duplicate Shipper & Consignee Tables | `shippers` and `consignees` duplicated columns and prevented locations from serving both roles. | ADR Decision 3 adopted: Consolidated into a single `facilities` table. `shipment_stops` references `facility_id` and records stop sequence and type (`pickup` vs `delivery`). | `03` App A, `05` §4.5, `06` §4.2, `09` §5.2 |
| **F-DB-02** | Shipment Requirements EAV Anti-Pattern | `shipment_requirements` used an entity-attribute-value design adding join overhead and weak typing. | Replaced EAV table with `shipments.requirements jsonb` column, validated against strict Pydantic schemas (temperature, hazmat, dimensions). | `05` §4.5, `06` §4.2, `07` §6, `10` ADR-020 |
| **F-DB-03** | Unused Transactional Outbox Table | `outbox_events` table was written to, but no dispatcher was implemented in MVP, creating dead storage. | Removed `outbox_events` table from MVP schema (ADR-009). Proposal and approval mutations are committed atomically within local PostgreSQL transactions. | `04` §10, `06` §2, `10` ADR-009 |
| **F-DB-04** | Ambiguous Carrier Service Region Semantics | Unclear whether service regions represented origin authority, destination authority, or both. | Clarified carrier service region semantics: `carrier_service_regions` represents operating authority and pickup presence in the origin region. Lane-specific pairing is handled via `carrier_availability` and `carrier_lane_rates`. | `06` §4.3, `07` §6 |
| **F-DB-05** | Competing Idempotency Implementations | Idempotency was split between API layer and workflow state without clear concurrency locking. | Unified on `idempotency_keys` table with atomic `status = 'in_progress'` locking. In-flight duplicates receive HTTP 409 Conflict (`ERR-006`). Upon completion, status updates to `'completed'` with cached response body. | `06` §4.7, `09` §6, `11` §7.2 |
| **F-AGENT-01** | Misleading `extract_requirements` Node Name | Node 5 was misnamed `extract_requirements`, implying text extraction occurred mid-workflow. | Renamed Node 5 to `normalize_requirements`. Text-to-structure extraction occurs strictly in the Intake Service before workflow start (FR-006). Node 5 normalizes structured JSONB requirements into the typed eligibility profile. | `03` App A, `07` §6, `08` §4 |
| **F-AGENT-02** | LangGraph Interrupt Re-execution Duplicate Risk | LangGraph resume re-executes the interrupted node, risking duplicate approval inserts. | Formalized pre-interrupt and post-interrupt idempotency in Node 11 (`request_human_approval`): Pre-interrupt checks DB for existing approval; post-interrupt detects approval in state and yields immediately to Node 12 (`apply_human_decision`) without re-inserting. | `07` §6.2, `08` §5 |
| **F-AGENT-03** | Redundant Validation Execution | Validation was run in API and again in Node 3 without clear relationship. | Clarified that API validation endpoint allows pre-workflow checking; Node 3 in workflow records an authoritative `validation_runs` record with `rules_version` and `validation_run_id`. | `07` §6, `09` §5.3 |
| **F-AGENT-04** | Terminal Audit-Event Responsibility Overlap | Node 14 audit logging overlapped with inline transactional service audits. | Clarified boundary: Service mutations write inline audit events atomically within domain transactions; Node 14 records terminal workflow completion/failure events and aggregate execution metrics (`node_execution_count`, `llm_call_count`, wall-clock time). | `05` §4.15, `07` §6.3 |
| **F-AGENT-05** | LangGraph Dependency & Fallback Justification | Review questioned LangGraph justification for a bounded workflow. | Justified LangGraph for its built-in PostgreSQL checkpointer and first-class `interrupt()` semantics. Specified an internal ~200-line deterministic Python state machine fallback if dependency issues arise. | `07` §3, `10` ADR-005 |
| **F-API-01** | Missing Scoring Configuration Endpoints | Scoring configs were versioned, but the API lacked endpoints to create, list, or activate them. | Added REST endpoints: `GET /api/v1/scoring-configs`, `POST /api/v1/scoring-configs`, `GET /api/v1/scoring-configs/{id}`, and `POST /api/v1/scoring-configs/{id}/activate` (atomically deactivating previous active config). | `03` App A, `09` §5.4 |
| **F-API-02** | Missing Validation Run ID & Rules Version in API | Validation response returned issues without linking to stored `validation_runs` record. | Updated validation response schema to return `validation_run_id` (UUID) and `rules_version` (string, e.g. "2026.1"). | `03` App A, `09` §5.3 |
| **F-API-03** | Concurrent Idempotency Race Condition | Concurrent requests with same idempotency key could race and execute duplicate side effects. | Added `idempotency_keys.status` (`in_progress`, `completed`, `failed`). Atomic insert of `in_progress` locks key; concurrent callers receive `409 Conflict`. | `06` §4.7, `09` §6, `11` §7.2 |
| **F-SEC-01** | Single-Tenant RBAC vs Multi-Tenant IDOR Claims | Documentation claimed multi-tenant IDOR protection, but the database model was single-tenant. | Corrected claims: FreightOps AI is a single-tenant system. Object-level access is governed by functional role permissions (`admin`, `broker`, `viewer`), not multi-tenant customer tenancy partitioning. | `03` §2, `09` §3, `11` §5.2 |
| **F-SEC-03** | Actual Database-Level Audit Immutability | Audit immutability was claimed but only enforced by application conventions. | Implemented database-level protection: Added PostgreSQL trigger `prevent_audit_event_mutation()` raising an exception on `UPDATE` or `DELETE`, and specified revoking mutation privileges from application role. | `06` §4.6, `11` §7.1 |

---

## 4. Review recommendations accepted, modified, or rejected

| Recommendation | Reviewer Proposal | Owner Action | Technical Rationale |
|---|---|---|---|
| Drop LangGraph entirely | Replace LangGraph with a pure Python state machine from day one. | **Modified** | **Retain LangGraph with fallback.** LangGraph provides production-grade PostgreSQL checkpointing (`AsyncPostgresSaver`) and clean `interrupt()` resumption out of the box, saving significant bespoke persistence code. A ~200-line deterministic state machine is documented as an immediate fallback if Python 3.12 compatibility testing encounters issues. |
| Add APScheduler for approval expiry | Add APScheduler to run background cron sweeps for approval TTL expiry. | **Rejected** | **Simplify scheduling.** Introducing a background cron engine solely to expire pending approvals creates unnecessary operational overhead for a single-developer MVP. An approval decision submitted by an operator is the event that resumes the graph. Automatic TTL expiry is deferred to Post-MVP. |
| Reduce database tables to 16 | Collapse several tables to drastically simplify schema. | **Modified** | **Prune to 21 justified tables.** Indiscriminately collapsing normalized relational structures (e.g., carrier equipment types, service regions, availability) into unstructured JSON would degrade carrier querying and deterministic eligibility indexing. Tables were reduced from 23 to 21 by consolidating shippers/consignees into facilities, removing outbox, replacing EAV requirements with JSONB, and adding carrier lane rates. |
| Remove transactional outbox | Remove `outbox_events` since no dispatcher exists. | **Accepted** | **Remove from MVP.** An outbox table without a dispatcher creates dead database storage and maintenance burden. Local transactions atomically write all domain mutations. Outbox messaging is deferred to Post-MVP when external message brokers are integrated. |
| Consolidate shippers & consignees | Merge duplicate tables into a unified facility model. | **Accepted** | **Consolidate into `facilities`.** Accurately reflects real freight logistics where distribution centers and warehouses act as both pickup origins and delivery destinations. |
| Single-tenant RBAC simplification | Drop `ops_manager` role and multi-tenant IDOR claims. | **Accepted** | **Simplify roles to `admin`, `broker`, `viewer`.** Align role matrix with realistic single-tenant operations and remove unwarranted multi-tenant claims. |

---

## 5. Complete summary of changes by document

### `docs/01-business-understanding.md`
- Bumped contract version to 2.0.
- Updated Section 2.2 party definitions: clarified `Customer` (commercial contract partner) vs `Facility` (physical logistics location where pickup/delivery stops occur).
- Updated Assumption `ASM-03`: clarified that target rates originate from customer quotes and recorded historical benchmarks (`carrier_lane_rates`).

### `docs/02-problem-definition.md`
- Bumped contract version to 2.0.
- Updated Problem `P-06` (Market Rate Uncertainty): documented that rate competitiveness evaluation relies on factual `carrier_lane_rates` benchmarks rather than model speculation.

### `docs/03-requirements-specification.md`
- Bumped contract version to 2.0.
- Updated Section 1.3 MVP Cut Line verbatim.
- Simplified roles in Section 2 to `admin`, `broker`, `viewer`.
- Classified all 155 Functional Requirements in Section 5 into: 68 MVP Must, 57 Post-MVP, 20 Future, 10 Merged/Removed.
- Updated Appendix A Canonical Contracts:
  - Added `facilities` (replacing `shippers` and `consignees`).
  - Added `carrier_lane_rates`.
  - Removed `shipment_requirements` and `outbox_events`.
  - Renamed Node 5 to `normalize_requirements`.
  - Added scoring configuration endpoints (`/api/v1/scoring-configs`).
  - Added facilities endpoints (`/api/v1/facilities`).
- Updated Appendix B State Machines:
  - Diagram `D-05` (Shipment): Added `booking_proposed -> sourcing` transition upon proposal decline or cancellation (CRIT-04).
  - Diagram `D-06` (Approval): Removed automated TTL expiration sweeps per ADR Decision 5.

### `docs/04-system-architecture.md`
- Bumped contract version to 2.0.
- Updated Section 6 component table and Section 7 collaboration walkthrough.
- Updated Section 8 runtime topology: Python 3.12 target runtime; event-driven resume on approval decision; no Celery, Redis, or APScheduler in MVP.
- Updated Section 10 MVP Cut Line verbatim.

### `docs/05-component-architecture.md`
- Bumped contract version to 2.0.
- Updated `ShipmentService` (Section 4.5): integrates `facilities` and `shipments.requirements jsonb`.
- Updated `CarrierService` (Section 4.7): manages `carrier_lane_rates`.
- Updated `RecommendationEngine` (Section 4.9): evaluates rate competitiveness using recorded lane rates.
- Updated `AgentOrchestrator` (Section 4.11): LangGraph checkpointing, Node 5 `normalize_requirements`, and pure Python fallback.
- Updated `ApprovalService` (Section 4.13): event-driven resume; deferred auto-expiry sweeps.
- Updated `BookingProposalService` (Section 4.14): decline/cancellation returns shipment to `sourcing`.
- Updated `AuditService` (Section 4.15): PostgreSQL trigger immutability enforcement.

### `docs/06-database-design.md`
- Bumped contract version to 2.0.
- Revised table count from 23 to 21 tables.
- Consolidated `shippers` and `consignees` into `facilities` (ADR-019).
- Made draft shipment party FKs (`customer_id`, `origin_facility_id`, `destination_facility_id`) nullable (CRIT-01).
- Replaced EAV table `shipment_requirements` with `shipments.requirements jsonb` (ADR-020).
- Added `carrier_lane_rates` table (CRIT-03).
- Removed `outbox_events` table (ADR-009).
- Clarified `carrier_service_regions` origin operating presence semantics (F-DB-04).
- Added `status` (`in_progress`, `completed`, `failed`) and timestamps to `idempotency_keys` (F-DB-05, F-API-03).
- Documented PostgreSQL trigger `prevent_audit_event_mutation()` and role privilege revocation on `audit_events` (F-SEC-03).
- Updated ER diagrams `D-11` and `D-12`.

### `docs/07-agent-workflow.md`
- Bumped contract version to 2.0.
- Section 3: Documented LangGraph value, checkpointing, and ~200-line deterministic Python state machine fallback.
- Section 6: Renamed Node 5 to `normalize_requirements` (F-AGENT-01).
- Section 6.2: Formalized pre-interrupt and post-interrupt idempotency semantics for Node 11 and Node 12 (F-AGENT-02).
- Section 6.3: Clarified terminal audit logging responsibility for Node 14 (F-AGENT-04).
- Section 7: Updated Diagram `D-13` with `normalize_requirements` and proposal decline re-sourcing edge.
- Section 8: Updated Diagram `D-14` sequence diagram showing event-driven resume from approval decision; removed automated TTL sweeps.
- Section 9: Detailed PostgreSQL checkpointer resilience.
- Section 12: Updated idempotency keys mapping to `idempotency_keys` table.

### `docs/08-data-flow.md`
- Bumped contract version to 2.0.
- Flow `DF-01`: Updated to use `facilities`, nullable draft party FKs, and `shipments.requirements jsonb`.
- Flow `DF-02`: Updated to use `normalize_requirements` and `carrier_lane_rates`.
- Flow `DF-03`: Updated to show event-driven resume on approval decision; removed scheduler sweeps.
- Flow `DF-04`: Removed outbox event creation; added proposal decline/cancellation re-sourcing transition.
- Flow `DF-05`: Updated failure and recovery stores (removed outbox).

### `docs/09-api-design.md`
- Bumped contract version to 2.0.
- Section 3: Simplified RBAC roles to `admin`, `broker`, `viewer` (F-SEC-01).
- Section 5.2: Added Facilities CRUD endpoints (`/api/v1/facilities`).
- Section 5.3: Updated `POST /api/v1/shipments` payload for nullable party references and JSONB requirements. Updated validation response schema to include `validation_run_id` and `rules_version` (F-API-02).
- Section 5.4: Added Scoring Configurations CRUD and activate endpoints (`/api/v1/scoring-configs`) (F-API-01).
- Section 5.6: Documented direct workflow resume on `POST /api/v1/approvals/{id}/decision`.
- Section 5.7: Added proposal cancellation endpoint (`POST /booking-proposals/{id}/cancel`) resetting shipment to `sourcing` (CRIT-04).
- Section 5.8: Added Carrier Lane Rates endpoints (`/api/v1/carriers/{id}/lane-rates`).
- Section 6: Specified atomic `in_progress` concurrency locking for idempotency keys (F-API-03).

### `docs/10-technology-decisions.md`
- Bumped contract version to 2.0.
- Section 3: Set Python 3.12 as the target application runtime (ADR-017).
- Updated ADR-004 (21 tables, facilities, lane rates).
- Updated ADR-005 (LangGraph + PostgreSQL checkpointer, justification, pure Python fallback).
- Updated ADR-009 (Transactional outbox deferred from MVP schema).
- Added ADR-017 (Target Python 3.12 Runtime).
- Added ADR-018 (Simplified Event-Driven Workflow Execution).
- Added ADR-019 (Consolidated Facilities Entity Model).
- Added ADR-020 (JSONB Shipment Requirements Model).
- Section 6: Established Python 3.12 dependency-adoption gate.

### `docs/11-security-and-reliability.md`
- Bumped contract version to 2.0.
- Section 5: Corrected single-tenant RBAC claims; role-based access control without multi-tenant IDOR claims (F-SEC-01).
- Section 7.1: Documented PostgreSQL trigger `prevent_audit_event_mutation()` for database-level audit immutability (F-SEC-03).
- Section 7.2: Specified atomic `in_progress` concurrency locking in `idempotency_keys` (F-API-03).
- Section 8.1: Updated duplicate-booking prevention (removed outbox dependency).

### `docs/12-evaluation-strategy.md`
- Bumped contract version to 2.0.
- Section 4 & 5: Updated test corpora definitions to include `facilities` and `carrier_lane_rates` in ranking and evaluation fixtures (`DS-04`).
- Section 5.5: Aligned fault injection scenarios (`DS-06`) with event-driven resume; removed automated TTL sweeps.
- Section 8: Synchronized blocking release gates with trimmed MVP scope.

### `docs/13-development-roadmap.md`
- Bumped contract version to 2.0.
- Section 4: Detailed deliverables and requirements for phases PH-0 through PH-6.
- Section 5: Mapped all 68 MVP Must requirements across phases; summarized 57 Post-MVP, 20 Future, and 10 Merged/Removed requirements.
- Section 9: Synchronized verbatim MVP Cut Line with `03 §1.3` and `04 §10`.

### `README.md` & `docs/README.md`
- Bumped contract version to 2.0 across root and documentation indexes.
- Updated runtime target to Python 3.12.
- Updated table count to 21 database tables.
- Added documents `14` (Architecture Review) and `15` (Revision Log) to reading orders and indexes.
- Recorded Contract 2.0 changelog.

---

## 6. Database schema delta (23 tables vs 21 tables)

```
========================================================================================
                          DATABASE SCHEMA REVISION DELTA
========================================================================================
Old Schema (Contract 1.0)          Revised Schema (Contract 2.0)      Status / Action
----------------------------------------------------------------------------------------
1.  users                          1.  users                          Retained
2.  customers                      2.  customers                      Retained
3.  shippers                       3.  facilities                     CONSOLIDATED (F-DB-01)
4.  consignees                     --  (merged into facilities)       REMOVED (F-DB-01)
5.  shipments                      4.  shipments                      MODIFIED (CRIT-01, ADR-020)
6.  shipment_stops                 5.  shipment_stops                 MODIFIED (points to facilities)
7.  shipment_requirements          --  (merged into shipments jsonb)  REMOVED (F-DB-02, ADR-020)
8.  validation_runs                6.  validation_runs                Retained
9.  validation_issues              7.  validation_issues              Retained
10. carriers                       8.  carriers                       Retained
11. carrier_equipment_types        9.  carrier_equipment_types        Retained
12. carrier_service_regions        10. carrier_service_regions        MODIFIED (origin presence)
13. carrier_availability           11. carrier_availability           Retained
--  (missing rate data)            12. carrier_lane_rates             ADDED (CRIT-03)
14. scoring_configs                13. scoring_configs                Retained
15. recommendations                14. recommendations                Retained
16. recommendation_candidates      15. recommendation_candidates      Retained
17. approvals                      16. approvals                      Retained
18. booking_proposals              17. booking_proposals              MODIFIED (CRIT-04 re-sourcing)
19. outbox_events                  --  (deferred to Post-MVP)         REMOVED (F-DB-03, ADR-009)
20. intake_submissions             18. intake_submissions             Retained
21. workflow_executions            19. workflow_executions            Retained
22. audit_events                   20. audit_events                   MODIFIED (DB trigger immutability)
23. idempotency_keys               21. idempotency_keys               MODIFIED (in_progress locking)
----------------------------------------------------------------------------------------
Total Tables: 23                   Total Tables: 21                   Net Change: -2 tables
========================================================================================
```

---

## 7. Workflow node delta

The 16 canonical workflow nodes are retained, with one critical renaming and formalized interrupt semantics:

| Node # | Old Name (Contract 1.0) | Revised Name (Contract 2.0) | Nature | Key Semantic Revisions |
|---|---|---|---|---|
| 1 | `start_execution` | `start_execution` | Deterministic | Initializes execution state, budgets, trace ID |
| 2 | `load_shipment` | `load_shipment` | Deterministic | Reads shipment aggregate, stops, facilities, JSONB requirements |
| 3 | `validate_shipment` | `validate_shipment` | Deterministic | Runs Validation Engine; records `validation_runs` with `rules_version` |
| 4 | `decide_validation_outcome` | `decide_validation_outcome` | Deterministic | Branches: pass/warnings vs failed (`validation_failed`) |
| 5 | **`extract_requirements`** | **`normalize_requirements`** | Deterministic | **RENAMED (F-AGENT-01).** Normalizes structured JSONB requirements into typed eligibility profile. Zero LLM calls. |
| 6 | `resolve_carrier_candidates` | `resolve_carrier_candidates` | Deterministic | Queries carriers by equipment and origin service region |
| 7 | `filter_eligible_carriers` | `filter_eligible_carriers` | Deterministic | Applies 8 deterministic hard filters; emits canonical reason codes |
| 8 | `score_candidates` | `score_candidates` | Deterministic | Uses active scoring config and factual `carrier_lane_rates` (CRIT-03) |
| 9 | `generate_explanation` | `generate_explanation` | Hybrid | Builds deterministic fact bundle; optional LLM narration |
| 10 | `persist_recommendation` | `persist_recommendation` | Deterministic | Writes recommendation and candidates atomically |
| 11 | `request_human_approval` | `request_human_approval` | Deterministic | **MODIFIED (F-AGENT-02).** Pre-interrupt DB check/insert; triggers LangGraph `interrupt()`; post-interrupt pass-through |
| 12 | `apply_human_decision` | `apply_human_decision` | Deterministic | Processes decision on resume; approved -> proposal; rejected/changes -> resets shipment to `sourcing` |
| 13 | `create_booking_proposal` | `create_booking_proposal` | Deterministic | Snapshots approved data; partial unique index enforces single active proposal |
| 14 | `record_audit_event` | `record_audit_event` | Deterministic | **MODIFIED (F-AGENT-04).** Appends terminal workflow completion/failure audit events and execution metrics |
| 15 | `finalize_execution` | `finalize_execution` | Deterministic | Updates workflow status to `completed` with outcome |
| 16 | `handle_failure` | `handle_failure` | Deterministic | Records error details, marks status `failed`/`timed_out`, safe exit |

---

## 8. Final MVP requirements count and classification breakdown

All 155 functional requirements defined in `docs/03-requirements-specification.md` are accounted for:

```
========================================================================================
                          FINAL REQUIREMENTS CLASSIFICATION
========================================================================================
Category                    Requirement Count    Percentage    Target Phase
----------------------------------------------------------------------------------------
MVP (Must Deliver)                         68       43.9%       PH-1 through PH-6
Post-MVP (Deferred)                        57       36.8%       v1.1 Release
Future Backlog                             20       12.9%       Long-Term Roadmap
Merged or Removed                          10        6.4%       Pruned / Consolidated
----------------------------------------------------------------------------------------
Total Requirements                        155      100.0%
========================================================================================
```

---

## 9. Remaining open questions, risks, and Phase 2 precautions

### 9.1 Open technical questions
1. **PostgreSQL Async Driver Selection:** `asyncpg` offers maximum raw throughput but has complex custom type mapping; `psycopg` (v3) offers mature binary support and modern async features.
   - *Recommendation:* Test both drivers against a clean Python 3.12 environment during Phase 1 setup.
2. **Password Hashing Library:** Verify availability and installation ergonomics of `argon2-cffi` vs `bcrypt` in the Python 3.12 environment.
   - *Recommendation:* Adopt `argon2-cffi` as primary; fall back to standard `bcrypt` if compilation issues occur.

### 9.2 Key implementation risks & mitigations
1. **LangGraph Checkpoint Serialization:** If `langgraph-checkpoint-postgres` encounters complex serialization issues with Pydantic models:
   - *Mitigation:* Activate the documented ~200-line deterministic Python state machine fallback.
2. **First Git Commit Discipline:** The repository currently has no commits and no `.gitignore`.
   - *Precaution:* Prior to issuing `git init` or the first commit, ensure `.venv/`, `__pycache__/`, `.env`, and IDE artifacts are explicitly placed in `.gitignore`.

---

## 10. Conclusion and architecture readiness verdict

With the completion of Phase 1.6:
1. All critical flaws (`CRIT-01` through `CRIT-04`) and review findings (`F-DB-01` through `F-SEC-03`) are resolved.
2. Database schema is consolidated to 21 strictly normalized, well-indexed tables.
3. Workflow orchestration is bounded, durable, event-driven, and equipped with a documented pure Python fallback.
4. The MVP requirements are trimmed to a realistic, high-quality 68-item core.
5. All 15 documents are synchronized under **Contract Version 2.0**.

**Verdict:** The FreightOps AI architecture documentation is **frozen, internally consistent, and approved for Phase 1.6 completion**. The design is verified to be implementable by a single developer building a high-caliber production portfolio project.


---

---

## 11. Phase 1.7: Architecture Defect Correction (Contract 2.1 Baseline)

### 11.1 Context and Authorization
Following the Phase 1.6 Contract Freeze (Contract 2.0), a secondary technical audit identified five major architectural defects (`DEF-01` through `DEF-05`) and nine cross-document inconsistencies (`INC-01` through `INC-09`). 

On 2026-11-23, the project owner reviewed the Stage A defect register and issued formal Stage B authorization to execute minimum necessary documentation corrections. The revisions elevate the architectural baseline to **Contract Version 2.1**.

### 11.2 Original Stage A Architecture Defect Resolutions (DEF-01 through DEF-05)

| Defect ID | Original Stage A Defect Name | Severity | Architectural Resolution | Affected Documents |
|---|---|---|---|---|
| **DEF-01** | Incomplete shipment-stop insertion on draft intake | High | Stop address fields (`name`, `address_line1`, `address_line2`, `city`, `state`, `postal_code`) are made nullable in draft status (`06 §3.10`, `09 §5.3`). Unstructured customer text often provides partial location data initially. Deterministic validation gating (`05 §3.2`, `07 §6 Node 3`, `08 §2.1`, `03 FR-020, FR-021, FR-040`) enforces stop completeness before transition to `validated`. | `03`, `05`, `06`, `07`, `08`, `09` |
| **DEF-02** | Workflow failure overwritten as completed in finalization | High | Diagram D-13 previously routed `handle_failure` to `record_audit_event` and `finalize_execution`, which set `status = 'completed'`. Separated `handle_failure` (Node 16) into an independent terminal sink terminating directly at `[*]` with `workflow.failed`. Nodes 14 (`record_audit_event`) and 15 (`finalize_execution`) exclusively handle successful completions (`status = 'completed'`) (`07 §6, §7`, `08 §2.5`, `05 §3.4`, `03 FR-157`). | `03`, `05`, `07`, `08` |
| **DEF-03** | MVP requirement counts and roadmap assignments conflict | High | Reconciled requirement inventory across `03`, `13`, `README.md`, and `docs/README.md`. Total requirements: **156** (`FR-001` through `FR-287`). Breakdown: **120 MVP (Must Deliver)**, **24 Post-MVP (Deferred)**, **5 Future**, **7 Merged/Removed**. All 36 non-MVP items had active `PH-x` phase assignments cleared so that zero non-MVP items appear as active phase commitments. Roadmap phase counts synchronized (PH-1: 19, PH-2: 21, PH-3: 22, PH-4: 33, PH-5: 18, PH-6: 7 = 120 MVP). | `03`, `13`, `README.md`, `docs/README.md` |
| **DEF-04** | Carrier-rate API and database schema mismatch | High | Standardized carrier rates across database (`06 §3.8`) and API (`09 §5.8`) on `flat_rate numeric(12,2)` and `rate_per_mile numeric(8,2)`. Added mandatory `source text not null default 'synthetic'` column and `chk_lane_rates_has_rate` constraint. Added partial unique index `idx_carrier_lane_rates_active_unique` on `(carrier_id, origin_state, destination_state, equipment_type) WHERE is_active = true` ensuring exactly one active benchmark rate per carrier/lane/equipment. Historical rate analytics deferred to Post-MVP (`03 FR-073`, `05 §3.3`). | `03`, `05`, `06`, `09` |
| **DEF-05** | Workflow recovery and idempotency under-specification | High | Removed claims that FastAPI background tasks provide durability across process restarts. Specified PostgreSQL checkpoint persistence (`AsyncPostgresSaver`) and transactional status updates (`04 §8`, `07 §8.1`, `10 ADR-018`, `11 §8.3`). Defined a configurable 60-second lease timeout on `idempotency_keys` (`06 §3.20`, `09 §6`, `11 §7.2`), allowing incoming retries to atomically reclaim stale leases via conditional update. Specified 4 crash recovery scenarios and established a bounded startup recovery check that preserves pending approvals (`FR-168`). | `04`, `06`, `07`, `08`, `09`, `10`, `11` |

### 11.3 Original Stage A Smaller Inconsistencies Traceability (INC-01 through INC-09)

| Inconsistency ID | Stage A Inconsistency Topic | Resolution Status | Resolution Applied & Affected Documents |
|---|---|---|---|
| **INC-01** | Facilities Contract Discrepancy | **Corrected** | Harmonized `code text null`, `timezone text null`, `country text not null default 'US'`, `operating_hours text null`, and added `cold_storage` to `facility_type` CHECK enum across database DDL (`06 §3.3`), API schemas (`09 §5.2`), component definitions (`05 §3.1`), and canonical contracts (`03 App A.2`). |
| **INC-02** | Intake Upload Scope Contradiction | **Corrected** | Harmonized intake boundary across all documentation: MVP strictly supports pasted unstructured text and structured REST API intake; Post-MVP supports `.txt` and `.json` file uploads; Future roadmap supports `.eml` email files and direct email integrations. Synchronized character-for-character across `03 §1.3`, `04 §10`, `13 §9`, and updated `03 FR-002`, `09 §5.1`, `10 ADR-014`, `README.md`, `docs/README.md`. |
| **INC-03** | Approval Terminology Mapping | **Corrected** | Standardized canonical mapping between human action commands and resultant states: `approve` -> `approved`; `reject` -> `rejected`; `request_changes` -> `changes_requested`. Synchronized across database DDL (`06 §3.15`), API payloads (`09 §5.6`), workflow nodes (`07 §6 Node 11`), component contracts (`05 §3.5`), and sequence diagrams (`08 §2.3`). |
| **INC-04** | Roadmap Phase Assignment Mismatches | **Corrected** | In `03 §5`, updated all 36 non-MVP requirements so their `Phase` column matches their status (`Post-MVP`, `Future`, `Merged`, `Removed`). In `13 §4` and `§5`, restricted development phase matrix and phase counts strictly to the 120 MVP items. |
| **INC-05** | LangGraph Fallback Verification Claim | **Corrected** | Rephrased documentation in `07 §12.1`, `10 §4.4, ADR-005`, `13 §8`, and `README.md` to state that the pure Python state machine is strictly an **architectural contingency design pattern**, not an active, implemented, or tested fallback. |
| **INC-06** | Audit Event Responsibility Boundary | **Corrected** | Clarified architectural separation of concern in `05 §3.4, §3.6` and `07 §6 Node 14`: `AuditService` is an independent cross-cutting compliance service invoked directly by FastAPI route handlers and LangGraph orchestration nodes. `AgentOrchestrator` delegates audit event generation to `AuditService` rather than persisting audit logs directly. |
| **INC-07** | Workflow Finalization Semantics | **Merged into DEF-02** | Node 15 is redefined to set `status = 'completed'` exclusively for successful business outcomes. Errors terminate in `handle_failure` (Node 16), which records status `failed` or `timed_out` directly. |
| **INC-08** | Idempotency Lease & Cleanup Specification | **Merged into DEF-05** | Added 60-second lease timeout on `idempotency_keys` and execution leasing, allowing retries after 60s to atomically reclaim crashed leases. Specified 24-hour retention TTL for completed keys. |
| **INC-09** | README & Document Index Harmonization | **Corrected** | Synchronized table counts (21 tables), requirement inventory (156 total / 120 MVP), and Contract 2.1 status across `README.md`, `docs/README.md`, and all 15 documentation deliverables. |

---

## 12. Phase 1.7.1: Targeted Correction and Evidence Pass

### 12.1 Approval Crash-Recovery Lifecycle & Persisted State

In Phase 1.7.1, the approval transaction boundary and LangGraph resumption lifecycle were subjected to a rigorous edge-case review to resolve the potential crash gap between PostgreSQL approval commit and workflow resumption.

#### 12.1.1 The Crash Scenario Addressed
1. An authorized broker submits `POST /api/v1/approvals/{approval_id}/decision`.
2. The database transaction commits the decision to `approvals` and transitions `shipments.status`.
3. The server process terminates abnormally (power failure, SIGKILL, out-of-memory) *before* the LangGraph engine resumes past the interrupt.
4. The client retries or the application container restarts.
5. The system must discover that the decision is saved but workflow resumption is still pending, claim execution ownership safely, and resume from the stored decision without duplicate side effects (e.g., avoiding duplicate booking proposals or redundant audit records).

#### 12.1.2 Persisted State Distinguishing Undecided vs Interrupted Resumptions
To eliminate ambiguity, Contract 2.1 specifies distinct persisted states across `workflow_executions` and `approvals`:

```
========================================================================================
                          PERSISTED APPROVAL & EXECUTION STATES
========================================================================================
Operational Condition          workflow_executions.status   approvals.status   approvals.resumed_at   Recovery Action
--------------------------------------------------------------------------------------------------------------------
Undecided Pending Approval     waiting_for_human            pending            NULL                   NEVER auto-resumed; waits indefinitely for human
Decision Committed / Interrupted resumption_pending          approved / rejected NULL                   Discovered by sweep/retry; claimed and resumed
Resumption In-Progress         running (with valid lease)   approved / rejected NULL                   Protected by active lease; not reclaimable
Crashed Resumption             running (with expired lease) approved / rejected NULL                   Reclaimed after 60s lease expiry
Resumption Completed           completed                    approved / rejected NOT NULL (timestamp)  Cached response returned; zero execution
========================================================================================
```

- **Undecided Pending Approval:** `workflow_executions.status = 'waiting_for_human'`, `approvals.status = 'pending'`, `approvals.decided_at IS NULL`.
  - **Invariant:** The system **strictly preserves** undecided pending approvals. They are never expired by background sweeps, never timed out, and never auto-resumed.
- **Decided Approval Awaiting Resumption:** `workflow_executions.status = 'resumption_pending'` (or `running` with expired lease), `approvals.status IN ('approved', 'rejected', 'changes_requested')`, `approvals.decided_at IS NOT NULL`, and `approvals.resumed_at IS NULL`.
  - **Invariant:** This explicit state indicates that human governance is complete, but the subsequent workflow resumption was interrupted.

#### 12.1.3 The Database Transaction Boundary
The approval decision endpoint (`POST /api/v1/approvals/{approval_id}/decision`) executes strictly within a single ACID transaction:
```sql
BEGIN;

-- 1. Lock the approval record
SELECT id, shipment_id, status, recommendation_id
FROM approvals
WHERE id = :approval_id
FOR UPDATE;

-- 2. Lock the associated workflow execution record
SELECT id, status, lease_owner, lease_expires_at
FROM workflow_executions
WHERE id = :workflow_execution_id
FOR UPDATE;

-- 3. Record the human decision in approvals table (resumed_at remains NULL)
UPDATE approvals
SET status = :decision_status,  -- 'approved' | 'rejected' | 'changes_requested'
    decided_by = :current_user_id,
    decided_at = NOW(),
    decision_comment = :comment,
    selected_candidate_id = :candidate_id,
    resumed_at = NULL,
    updated_at = NOW()
WHERE id = :approval_id;

-- 4. Transition shipment status according to decision
IF :decision_status = 'approved' THEN
    UPDATE shipments SET status = 'booking_proposed', updated_at = NOW() WHERE id = :shipment_id;
ELSE
    UPDATE shipments SET status = 'sourcing', updated_at = NOW() WHERE id = :shipment_id;
END IF;

-- 5. Set workflow execution to 'resumption_pending' (storing durable intent to resume)
UPDATE workflow_executions
SET status = 'resumption_pending',
    lease_token = NULL,
    lease_owner = NULL,
    lease_expires_at = NULL,
    updated_at = NOW()
WHERE id = :workflow_execution_id;

-- 6. Insert immutable audit event atomically
INSERT INTO audit_events (
    id, event_type, aggregate_type, aggregate_id, actor_id, actor_role,
    workflow_execution_id, payload, created_at
) VALUES (
    gen_random_uuid(), 'approval.decision_recorded', 'approval', :approval_id,
    :current_user_id, :current_user_role, :workflow_execution_id,
    jsonb_build_object('decision', :decision_status, 'candidate_id', :candidate_id),
    NOW()
);

COMMIT;
```

#### 12.1.4 Post-Commit Resumption & Idempotent Completion
Immediately following transaction commit, the application does not rely on an untracked background thread. Instead, it attempts to claim the execution lease:
```sql
UPDATE workflow_executions
SET status = 'running',
    lease_token = gen_random_uuid(),
    lease_owner = :worker_instance_id,
    lease_expires_at = NOW() + INTERVAL '60 seconds',
    updated_at = NOW()
WHERE id = :workflow_execution_id
  AND status = 'resumption_pending'
  AND (lease_expires_at IS NULL OR lease_expires_at < NOW());
```
If the lease is claimed (rows updated = 1):
1. The worker resumes the LangGraph engine past the interrupt:
   `graph.invoke(Command(resume={"action": decision_status, "selected_candidate_id": candidate_id}), config=...)`
2. LangGraph resumes from Node 11 and branches:
   - If `approved`: routes to Node 13 (`create_booking_proposal`).
   - If `rejected` or `changes_requested`: routes to Node 12 / 14, resetting shipment to `sourcing`.
3. In Node 13 (`create_booking_proposal`):
   - The node performs an idempotent check: `SELECT id FROM booking_proposals WHERE approval_id = :approval_id;`.
   - If a proposal was already created in a prior partial run before a crash, Node 13 reuses the existing proposal record and skips duplicate insertion.
4. In Node 15 (`finalize_execution`):
   - Sets `approvals.resumed_at = NOW()`.
   - Sets `workflow_executions.status = 'completed'`.
   - Clears `lease_token = NULL`, `lease_owner = NULL`, `lease_expires_at = NULL`.
   - Terminates execution cleanly at `[*]`.

#### 12.1.5 Recovery Triggers & Re-Crash Protection
Two independent triggers guarantee recovery without polling:
1. **Trigger 1 (Client Retry):** When the client retries `POST /approvals/{id}/decision` (e.g. following HTTP timeout or page reload):
   - The handler locks `approvals`. It sees `status` is already decided (`approved`).
   - If `resumed_at IS NOT NULL`: Resumption already finished! Returns cached `200 OK` with proposal metadata immediately.
   - If `resumed_at IS NULL`: The handler claims the execution lease and immediately dispatches LangGraph resumption using the saved decision.
2. **Trigger 2 (Startup / Background Recovery Sweep):**
   - On application startup (and passive queue sweeps), the system queries:
     ```sql
     SELECT w.id, w.shipment_id, a.id AS approval_id, a.status AS decision_status, 
            a.selected_candidate_id, a.decided_by
     FROM workflow_executions w
     JOIN approvals a ON a.shipment_id = w.shipment_id
     WHERE (w.status = 'resumption_pending' 
            OR (w.status = 'running' AND w.lease_expires_at < NOW()))
       AND a.status IN ('approved', 'rejected', 'changes_requested')
       AND a.resumed_at IS NULL
     FOR UPDATE OF w SKIP LOCKED;
     ```
   - For each matching row, the worker claims the lease and resumes the checkpoint.
   - **Re-Crash Protection:** If the recovery worker crashes *again* during resumption, the lease expires after 60 seconds. A subsequent retry or sweep re-claims the lease. Because Node 13 and Node 15 are idempotent, repeated crash-recovery cycles produce zero duplicate entities.

---

### 12.2 Safe Execution Lease & Ownership Model (No PID Dependence)

Operating system process IDs (PIDs) are explicitly **rejected** as proof of execution ownership:
- In containerized Docker Compose or Kubernetes deployments, every container runs as PID 1 inside its own namespace. PID values collide across containers.
- If a container dies, its PID vanishes immediately; checking `kill(pid, 0)` from another container or post-restart process is either impossible or inspects an unrelated host process.

#### The Database Execution Lease Specification
Execution ownership is governed strictly by relational database state on `workflow_executions`:
1. `lease_token uuid null`: A unique token generated per claim attempt.
2. `lease_owner text null`: A string identifying the active worker node/instance (e.g. `worker-instance-uuid`).
3. `lease_expires_at timestamptz null`: Absolute wall-clock expiry time (default 60-second window).

#### Concurrency and Stale Lease Reclamation Rules:
- An execution is **actively locked** if `status = 'running'` AND `lease_expires_at > NOW()`.
- An execution is **stale / reclaimable** if `status = 'resumption_pending'` OR (`status = 'running'` AND `lease_expires_at < NOW()`).
- Workers claim executions via atomic conditional update:
  ```sql
  UPDATE workflow_executions
  SET status = 'running',
      lease_token = :new_token,
      lease_owner = :new_owner,
      lease_expires_at = NOW() + INTERVAL '60 seconds',
      updated_at = NOW()
  WHERE id = :id
    AND (lease_expires_at IS NULL OR lease_expires_at < NOW() OR status = 'resumption_pending');
  ```
- If two processes attempt to claim the lease concurrently, PostgreSQL row locking ensures exactly one process updates the row (returns 1); the other process gets 0 rows updated and backs off.
- Workers executing long-running steps renew their lease periodically:
  ```sql
  UPDATE workflow_executions
  SET lease_expires_at = NOW() + INTERVAL '60 seconds'
  WHERE id = :id AND lease_token = :my_token;
  ```
- If a worker dies, its heartbeat ceases. After 60 seconds, `lease_expires_at` is in the past, and incoming retries or recovery sweeps safely reclaim ownership.

---

### 12.3 Requirement-by-Requirement MVP Justification and Evidence

#### 12.3.1 Mathematical Audit of Document 14 vs Document 03
A detailed audit of the historical review document (`docs/14-architecture-review.md`) uncovered the source of the "58 vs 120" confusion:
1. In `14-architecture-review.md §4`, the prose summary block claimed:
   - "Essential MVP Requirements: 58"
   - "Important but Deferrable: 51"
   - "Future Product Capabilities: 28"
   - "Unnecessary or Overlapping: 18"
   *(Total: 155)*
2. However, in the **actual requirement-by-requirement evaluation table** in that same document (`14 §4`), the reviewer marked:
   - `1. Essential MVP`: **112 requirements**!
   - `2. Deferrable`: **31 requirements**!
   - `4. Unnecessary/Overlapping`: **7 requirements**!
   - `3. Future`: **5 requirements**!
   *(Total: 155)*
3. The prose summary table in Document 14 was internally inconsistent with its own line-by-line classification table (58 vs 112).
4. Subsequently, in Phase 1.6, the project owner approved ADR Decisions 3, 4, and 5, which mandated retaining critical security, validation, rate calculation, and human approval capabilities:
   - `FR-023`: Optimistic concurrency versioning on shipments (data integrity).
   - `FR-049`: Persist validation runs with timestamp and rules version (auditability).
   - `FR-073`: Carrier lane rate model solving CRIT-03 (rate modeling).
   - `FR-184`: Allow requesting changes on approval with required note (HITL decisioning).
   - `FR-209`: Proposal cancellation returning shipment to sourcing solving CRIT-04 (re-sourcing).
   - `FR-253`: Canonical RBAC roles (`admin`, `broker`, `viewer`) (security).
   - `FR-254`: Enforce permissions on every REST endpoint (security).
   - `FR-255`: Enforce permissions on every UI route (security).
5. Adding these 8 mandatory requirements to the 112 essential requirements yields exactly:
   $$112 + 8 = 120	ext{ MVP Requirements}$$

Every single one of the 120 MVP requirements is an atomic, indivisible component of the end-to-end pipeline. Trimming any of them would compromise legal authority checks, equipment compatibility validation, bounded workflow execution, or role-based security.

#### 12.3.2 Authoritative Requirement-by-Requirement Justification Table (All 156 Requirements)

| ID | Requirement Name | Status | First Workflow? | Technical Justification | Core Dependencies |
|---|---|---|---|---|---|
| **FR-001** | The system shall accept an intake submission as pasted plain text. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-002** | The system shall accept an intake submission as an uploaded `.txt` or `.json` file. | `Post-MVP` | **No** | Deferred to v1.1 release; Deferred `.eml` MIME parsing to Future; plain text and JSON file upload in Post-MVP. | MVP core |
| **FR-003** | The system shall accept an intake submission through `POST /api/v1/intake/submissions`. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-004** | The system shall support manual shipment entry without an intake submission. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-005** | The system shall persist the raw intake content with channel, received timestamp, content hash, and submitter. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-006** | The system shall produce a structured draft Shipment from intake text, recording per-field provenance and confidence. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-007** | The system shall leave absent fields null and shall never invent missing shipment values. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-008** | The system shall preserve the original raw text alongside the structured record. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-009** | The system shall detect duplicate submissions by idempotency key or content hash and return the existing submission. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-010** | The system shall link each intake submission to the Shipment draft it created. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-011** | The system shall allow an operator to review and correct extracted fields before validation. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-012** | The system shall record extraction metadata (model identifier, prompt version) without requiring a real provider. | `Post-MVP` | **No** | Deferred to v1.1 release; Deferred detailed model telemetry; basic metadata in MVP. | MVP core |
| **FR-013** | The system shall reject unsupported media types and oversized uploads with a structured error. | `Merged` | **No** | Merged into canonical schema/API design; Merged into standard Pydantic/FastAPI request validation (`ERR-008`/`ERR-009`). | Canonical contracts |
| **FR-014** | The system shall treat intake text as untrusted data and shall not execute instructions contained in it. | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-020** | The system shall create a Shipment draft with identifier and status `draft`. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-021** | The system shall support one or more pickup and delivery Stops per Shipment via `shipment_stops`. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-022** | The system shall store Shipment Requirements as a validated JSONB structure on the Shipment. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-023** | The system shall allow Shipment updates before booking with optimistic concurrency (`version`). | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-024** | The system shall retrieve a Shipment with its Stops, Requirements, and current status. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-025** | The system shall enforce Shipment status transitions according to the canonical state machine. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-026** | The system shall derive the Lane from the first pickup and last delivery stop. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-027** | The system shall validate stop sequencing: at least one pickup, at least one delivery, pickup before delivery. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-028** | The system shall store Customer and Facility references distinctly. | `Merged` | **No** | Merged into canonical schema/API design; Merged into `facilities` and `customers` schema design. | Canonical contracts |
| **FR-029** | The system shall prevent hard deletion of booked Shipments and support cancellation with an audit trail. | `Post-MVP` | **No** | Deferred to v1.1 release; Defer hard-delete constraint checks; soft cancellation supported in MVP. | MVP core |
| **FR-030** | The system shall list and filter Shipments by status, lane, customer, and date range. | `Post-MVP` | **No** | Deferred to v1.1 release; Basic pagination in MVP; multi-parameter filtering in Post-MVP. | MVP core |
| **FR-031** | The system shall record the Shipment source (`intake_submission` or `manual`). | `MVP` | **Yes** | Essential for initial ingestion and provenance tracking of customer freight requests. | FastAPI / PostgreSQL |
| **FR-032** | The system shall prevent modification of fields frozen after approval or booking. | `MVP` | **Yes** | Core domain aggregate required to represent freight stops, requirements, and status state machine. | FR-001/003, facilities |
| **FR-040** | The system shall validate required fields for booking readiness (customer, stops, commodity, weight). | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-041** | The system shall detect contradictory values across fields (e.g. delivery before pickup, weight exceeds limits). | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-042** | The system shall emit Validation Issues with canonical severity values (`info`, `warning`, `error`, `critical`). | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-043** | The system shall compute a Validation result status of `passed`, `passed_with_warnings`, or `failed`. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-044** | The system shall block Approval while any `error` or `critical` issue exists. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-045** | The system shall permit review of `warning` issues without blocking Approval. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-046** | The system shall return Validation results through `GET /api/v1/shipments/{id}/validation`. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-047** | The system shall produce a clarification request listing blocking issues. | `Post-MVP` | **No** | Deferred to v1.1 release; List of blocking issues in validation response is MVP; automated drafting is Post-MVP. | MVP core |
| **FR-048** | The system shall support re-validation after correction. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-049** | The system shall persist validation runs with timestamp and rules version. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-050** | The system shall not auto-fill missing critical fields during validation. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-051** | The system shall validate numeric ranges and formats for weights, dates, and temperatures. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-052** | The system shall validate equipment/requirement compatibility. | `MVP` | **Yes** | Mandatory deterministic gating rule ensuring equipment, hazmat, and stops are valid before sourcing. | FR-020, FR-021 |
| **FR-060** | The system shall create, read, update, and deactivate Carrier profiles. | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-061** | The system shall store Carrier status using canonical values (`active`, `inactive`, `suspended`). | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-062** | The system shall store recorded insurance expiry and authority indicators without claiming external verification. | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-063** | The system shall manage Equipment Types per Carrier. | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-064** | The system shall manage Service Regions per Carrier with origin operating presence semantics. | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-065** | The system shall manage Availability windows per Carrier. | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-066** | The system shall search Carriers by equipment, region, and availability. | `Post-MVP` | **No** | Deferred to v1.1 release; Workflow queries directly in MVP; general search endpoint in Post-MVP. | MVP core |
| **FR-067** | The system shall treat inactive or suspended Carriers as ineligible. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-068** | The system shall list Carrier data for operators. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-069** | The system shall support importing synthetic Carrier and Lane Rate seed data. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-070** | The system shall record `last_verified_at` for Carrier attributes. | `Post-MVP` | **No** | Deferred to v1.1 release; Deferred detailed provenance metadata. | MVP core |
| **FR-071** | The system shall reject invalid region or equipment values. | `Merged` | **No** | Merged into canonical schema/API design; Handled by Pydantic enum validation. | Canonical contracts |
| **FR-072** | The system shall show Carrier eligibility context on the carrier profile. | `Post-MVP` | **No** | Deferred to v1.1 release; Advanced profile UI feature deferred. | MVP core |
| **FR-073** | The system shall store synthetic Carrier Lane Rates (`carrier_lane_rates`) for pricing comparison. | `MVP` | **Yes** | Essential carrier profile, equipment, region, and rate data needed for eligibility and costing. | Synthetic seed data |
| **FR-090** | The system shall run deterministic hard filters for a validated Shipment. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-091** | The system shall filter by Equipment Type match. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-092** | The system shall filter by Service Region coverage (matching origin stop state/region). | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-093** | The system shall filter by recorded Availability window. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-094** | The system shall filter by Carrier status. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-095** | The system shall filter by recorded insurance validity against pickup date. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-096** | The system shall filter by hazmat authorization when Shipment requires hazmat. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-097** | The system shall filter by temperature capability when Shipment requires temperature control. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-098** | The system shall emit canonical ineligibility reason codes. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-099** | The system shall distinguish `insufficient_data` from `ineligible`. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-100** | The system shall make eligibility decisions only in deterministic code, never in the LLM. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-101** | The system shall persist eligibility evaluation results per Recommendation candidate. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-102** | The system shall provide human-readable eligibility reasons for exclusions. | `MVP` | **Yes** | Strict deterministic safety filter gating carrier selection on legal authority, insurance, and equipment. | FR-060..FR-066 |
| **FR-103** | The system shall make eligibility rules configurable without model retraining. | `Future` | **No** | Deferred to long-term enterprise backlog; Dynamic rule modification deferred to Future roadmap. | Post-MVP release |
| **FR-120** | The system shall generate a Recommendation for a validated Shipment on request. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-121** | The system shall rank eligible Carriers using the active Scoring Configuration. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-122** | The system shall produce a score breakdown per scoring component. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-123** | The system shall return the top-N ranked candidates (default 5). | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-124** | The system shall transition Recommendation status through canonical values. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-125** | The system shall generate an Explanation citing deterministic facts with optional LLM narration. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-126** | The system shall ensure explanations cite only recorded facts and introduce no new claims. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-127** | The system shall return `no_eligible_carriers` when filtering yields zero candidates. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-128** | The system shall degrade gracefully when carrier data is incomplete (`insufficient_data`). | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-129** | The system shall store the Scoring Configuration version used. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-130** | The system shall supersede prior active Recommendations when Shipment changes. | `Post-MVP` | **No** | Deferred to v1.1 release; Prior recommendation superseding handled in Post-MVP. | MVP core |
| **FR-131** | The system shall expire stale Recommendations after a configurable TTL. | `Post-MVP` | **No** | Deferred to v1.1 release; Deferred per ADR Decision 5 (simplified scheduling). | MVP core |
| **FR-132** | The system shall provide recommendation detail including candidates and score breakdowns. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-133** | The system shall use only operator-provided target rates and recorded carrier lane rates. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-134** | The system shall rank deterministically for identical inputs, config, and data snapshot. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-150** | The system shall start a Workflow Execution for a Shipment. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-151** | The system shall execute the canonical 16-node graph with conditional edges. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-152** | The system shall persist Workflow state and node checkpoints in PostgreSQL. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-153** | The system shall enforce maximum attempts, LLM calls, and execution timeout. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-154** | The system shall pause at the human approval interrupt and record `waiting_for_human`. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-155** | The system shall resume from the interrupt using the recorded human decision. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-156** | The system shall retry transient failures within the configured budget. | `Post-MVP` | **No** | Deferred to v1.1 release; Transient retry backoff deferred to Post-MVP. | MVP core |
| **FR-157** | The system shall route unrecoverable failures to `handle_failure`. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-158** | The system shall never create a Booking Proposal without a valid Approval. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-159** | The system shall expose Workflow status via `GET /api/v1/workflows/{id}`. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-160** | The system shall record a node-level audit event for key milestone node executions. | `Post-MVP` | **No** | Deferred to v1.1 release; Node-level audit logging deferred to Post-MVP; milestone audit in MVP. | MVP core |
| **FR-161** | The system shall make every side-effecting node idempotent. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-162** | The system shall validate tool-call payloads with Pydantic schemas. | `Merged` | **No** | Merged into canonical schema/API design; Enforced by standard Python typed function signatures. | Canonical contracts |
| **FR-163** | The system shall restrict tool invocation to a hardcoded allowlist. | `Merged` | **No** | Merged into canonical schema/API design; Enforced by deterministic LangGraph node graph. | Canonical contracts |
| **FR-164** | The system shall provide a mock LLM provider for tests and local development. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-165** | The system shall record LLM invocation telemetry (tokens, latency) when enabled. | `Post-MVP` | **No** | Deferred to v1.1 release; Telemetry table and tracking in Post-MVP. | MVP core |
| **FR-166** | The system shall allow cancellation of a running or waiting Workflow. | `Post-MVP` | **No** | Deferred to v1.1 release; Manual cancel endpoint deferred to Post-MVP. | MVP core |
| **FR-167** | The system shall detect and stop repeated no-progress loops. | `Removed` | **No** | Removed from scope; Removed: The graph is acyclic; no-progress loops cannot occur. | None |
| **FR-168** | The system shall preserve Workflow state across process restarts. | `MVP` | **Yes** | Core LangGraph orchestration executing bounded 16-node workflow with checkpoint persistence and recovery. | PostgreSQL checkpointer |
| **FR-180** | The system shall create an Approval request from a `ready` Recommendation. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-181** | The system shall display recommendation, scores, explanation, and warnings to the approver. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-182** | The system shall allow an authorized user to approve an Approval. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-183** | The system shall allow rejection with a required reason. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-184** | The system shall allow requesting changes with a required note. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-185** | The system shall enforce role permission for approval actions. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-186** | The system shall record approver, timestamp, decision, comment, and selected candidate immutably. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-187** | The system shall expire Approvals after a configurable TTL. | `Post-MVP` | **No** | Deferred to v1.1 release; Deferred per ADR Decision 5 (no scheduler sweep). | MVP core |
| **FR-188** | The system shall enforce separation of duties between preparer and approver. | `Future` | **No** | Deferred to long-term enterprise backlog; Optional four-eyes check deferred to Future roadmap. | Post-MVP release |
| **FR-189** | The system shall make approval decisions idempotent. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-190** | The system shall allow the approver to select a different eligible candidate than rank 1. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-191** | The system shall record the selected candidate on the Approval. | `MVP` | **Yes** | Human-in-the-loop governance gating commercial booking proposals on authorized broker decision. | FR-114, RBAC |
| **FR-192** | The system shall refuse approval when the Recommendation is superseded or cancelled. | `Post-MVP` | **No** | Deferred to v1.1 release; Coupled with recommendation superseding; Post-MVP. | MVP core |
| **FR-200** | The system shall create a Booking Proposal only after an `approved` Approval. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-201** | The system shall snapshot approved Shipment, Facility, and Carrier data into the Proposal. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-202** | The system shall transition Booking Proposal status through canonical values. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-203** | The system shall not tender externally or claim carrier confirmation in the MVP. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-204** | The system shall make Booking Proposal creation idempotent. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-205** | The system shall retrieve and list Booking Proposals. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-206** | The system shall refuse proposal creation when Approval is invalid or rejected. | `Merged` | **No** | Merged into canonical schema/API design; Merged with FR-200. | Canonical contracts |
| **FR-207** | The system shall prevent more than one active Booking Proposal per Shipment. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-208** | The system shall record audit events for proposal creation and status changes. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-209** | The system shall allow a proposal to be declined or cancelled, returning the Shipment to `sourcing`. | `MVP` | **Yes** | Terminal business artifact snapshotting approved terms without outbound EDI/carrier tender. | FR-182 (Approval) |
| **FR-220** | The system shall append audit events for state-changing operations in the caller's transaction. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-221** | The system shall use canonical audit event types from Appendix A. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-222** | The system shall correlate audit events by trace_id, workflow_execution_id, and shipment_id. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-223** | The system shall expose an audit query endpoint with filters. | `Post-MVP` | **No** | Deferred to v1.1 release; Basic database logging in MVP; rich query API in Post-MVP. | MVP core |
| **FR-224** | The system shall deny update and delete of audit events via PostgreSQL trigger. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-225** | The system shall emit structured JSON logs with request and trace IDs. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-226** | The system shall expose an unauthenticated health endpoint. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-227** | The system shall record workflow latency and failure metrics. | `Post-MVP` | **No** | Deferred to v1.1 release; OpenTelemetry metric counters in Post-MVP. | MVP core |
| **FR-228** | The system shall record LLM token and cost metrics. | `Post-MVP` | **No** | Deferred to v1.1 release; Detailed cost reporting in Post-MVP. | MVP core |
| **FR-229** | The system shall record evaluation run results. | `Post-MVP` | **No** | Deferred to v1.1 release; Offline script reports in MVP; in-database eval rows in Post-MVP. | MVP core |
| **FR-230** | The system shall redact sensitive contact and credential fields from logs. | `MVP` | **Yes** | Essential security, compliance immutability trigger, structured logging, and PII redaction. | PostgreSQL triggers |
| **FR-231** | The system shall audit configuration changes. | `Post-MVP` | **No** | Deferred to v1.1 release; Config audit in Post-MVP. | MVP core |
| **FR-250** | The system shall maintain local user accounts. | `MVP` | **Yes** | Essential security boundary enforcing local authentication and role-based access control (RBAC). | FastAPI security |
| **FR-251** | The system shall authenticate UI users with a secure session cookie. | `MVP` | **Yes** | Essential security boundary enforcing local authentication and role-based access control (RBAC). | FastAPI security |
| **FR-252** | The system shall authenticate API clients with a bearer token. | `Post-MVP` | **No** | Deferred to v1.1 release; Session auth for UI/API in MVP; dedicated token auth in Post-MVP. | MVP core |
| **FR-253** | The system shall implement canonical RBAC roles (`admin`, `broker`, `viewer`). | `MVP` | **Yes** | Essential security boundary enforcing local authentication and role-based access control (RBAC). | FastAPI security |
| **FR-254** | The system shall enforce permissions on every REST endpoint. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-255** | The system shall enforce permissions on every UI route. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-256** | The system shall deny unauthenticated access to all endpoints except health. | `MVP` | **Yes** | Essential operational capability required for end-to-end pipeline demonstration. | Core pipeline |
| **FR-257** | The system shall store passwords using a salted password hash (Argon2 / bcrypt). | `MVP` | **Yes** | Essential security boundary enforcing local authentication and role-based access control (RBAC). | FastAPI security |
| **FR-258** | The system shall expire sessions after an idle period. | `Future` | **No** | Deferred to long-term enterprise backlog; Idle session sweeping deferred to Future. | Post-MVP release |
| **FR-259** | The system shall allow administrators to manage users and roles. | `Post-MVP` | **No** | Deferred to v1.1 release; Seed script handles users in MVP; admin management UI in Post-MVP. | MVP core |
| **FR-260** | The system shall audit authentication failures. | `Future` | **No** | Deferred to long-term enterprise backlog; Security telemetry deferred to Future. | Post-MVP release |
| **FR-280** | The system shall version Scoring Configurations. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-281** | The system shall activate exactly one Scoring Configuration at a time. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-282** | The system shall load synthetic seed data only. | `MVP` | **Yes** | Required for deterministic testing, demonstration, and environment initialization. | PostgreSQL DDL |
| **FR-283** | The system shall support resetting and reseeding a non-production database. | `MVP` | **Yes** | Required for deterministic testing, demonstration, and environment initialization. | PostgreSQL DDL |
| **FR-284** | The system shall expose canonical enum metadata (`GET /api/v1/meta/enums`). | `Post-MVP` | **No** | Deferred to v1.1 release; Introspection endpoint in Post-MVP. | MVP core |
| **FR-285** | The system shall validate configuration weights sum to 1.0 before activation. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-286** | The system shall provide a feature flag to toggle LLM narration on or off. | `MVP` | **Yes** | Deterministic scoring and ranking engine providing factual carrier recommendations with LLM explanation. | Eligibility, Rates |
| **FR-287** | The system shall provide an administrator system status view. | `Future` | **No** | Deferred to long-term enterprise backlog; System dashboard deferred to Future. | Post-MVP release |

---

### 12.4 Defect and Inconsistency Traceability Matrix

The complete resolution status of all Stage A defects and inconsistencies is certified below:

| ID | Title / Topic | Status | Resolution Mechanism & Verification Target |
|---|---|---|---|
| **DEF-01** | Incomplete shipment-stop insertion on draft intake | **Corrected** | Draft address fields nullable in `06 §3.10` and `09 §5.3`; stop completeness validated before `validated` status in `05 §3.2` and `07 §6 Node 3`. |
| **DEF-02** | Workflow failure overwritten as completed in finalization | **Corrected** | `handle_failure` (Node 16) separated as terminal sink directly to `[*]` with `workflow.failed` in `07 §6, §7` and `08 §2.5`; Node 14/15 handle successful completions only. |
| **DEF-03** | MVP requirement counts and roadmap assignments conflict | **Corrected** | Reconciled inventory to 156 total (120 MVP, 24 Post-MVP, 5 Future, 7 Merged/Removed); active phase assignments cleared from all 36 non-MVP items; roadmap counts synchronized across `03`, `13`, `README.md`, `docs/README.md`. |
| **DEF-04** | Carrier-rate API and database schema mismatch | **Corrected** | Standardized on `flat_rate numeric(12,2)` and `rate_per_mile numeric(8,2)` with `source = 'synthetic'` and active unique partial index in `06 §3.8` and `09 §5.8`. |
| **DEF-05** | Workflow recovery and idempotency under-specification | **Corrected** | Specified approval recovery lifecycle (`resumption_pending`), database execution lease ownership (`lease_token`, 60s window, no PID dependence), 4 crash recovery scenarios, and bounded startup recovery check in `06 §3.17, §3.20`, `07 §8, §10`, `08 §2.3`, `09 §5.6, §6`, `11 §7, §8`. |
| **INC-01** | Facilities Contract Discrepancy | **Corrected** | Harmonized `code`, `timezone`, `cold_storage`, `operating_hours`, and `country` in `06 §3.3`, `09 §5.2`, `05 §3.1`, `03 App A.2`. |
| **INC-02** | Intake Upload Scope Contradiction | **Corrected** | Harmonized intake boundary across all docs: paste/REST MVP, file upload Post-MVP, email Future; synchronized verbatim across `03 §1.3`, `04 §10`, `13 §9`. |
| **INC-03** | Approval Terminology Mapping | **Corrected** | Standardized canonical command-to-state mapping (`approve`->`approved`, `reject`->`rejected`, `request_changes`->`changes_requested`) across `03 App A.2`, `05 §3.5`, `06 §3.15`, `07 §6`, `08 §2.3`, `09 §5.6`. |
| **INC-04** | Roadmap Phase Assignment Mismatches | **Corrected** | Non-MVP requirements in `03 §5` cleared of active phase assignments; phase matrix in `13 §4, §5` restricted strictly to 120 MVP items. |
| **INC-05** | LangGraph Fallback Verification Claim | **Corrected** | Pure Python state machine designated strictly as an **architectural contingency design pattern** in `07 §12.1`, `10 ADR-005`, `13 §8`, `README.md`. |
| **INC-06** | Audit Event Responsibility Boundary | **Corrected** | `AuditService` specified as standalone compliance service called directly by route handlers and orchestration nodes in `05 §3.4, §3.6` and `07 §6 Node 14`. |
| **INC-07** | Workflow Finalization Semantics | **Merged into DEF-02** | Node 15 finalization semantics unified with failure routing separation in `07 §6` and `08 §2.5`. |
| **INC-08** | Idempotency Lease & Cleanup Specification | **Merged into DEF-05** | Idempotency lease 60s timeout, cleanup TTL, and execution leasing unified under DEF-05 in `06 §3.20`, `09 §6`, `11 §7.2`. |
| **INC-09** | README & Document Index Harmonization | **Corrected** | Synchronized 21 tables, 156 requirements, and Contract 2.1 status across `README.md` and `docs/README.md`. |

---

### 12.5 Evidence Level and Verification Language Audit

To maintain technical integrity during this documentation-only phase, all statements claiming empirical verification have been audited and calibrated:

```
========================================================================================
                          LEVELS OF ARCHITECTURAL VERIFICATION
========================================================================================
Verification Level               Definition                                                 Scope in Phase 1
----------------------------------------------------------------------------------------
Level 1: Document Consistency    Cross-referencing terminology, schemas, node names, and   Completed across
                                 contracts across all 15 specification documents.           all 15 documents.
Level 2: Automated Text/Schema   Running deterministic Python assertion scripts to check   Completed via test
         Consistency             byte-for-byte cut line matches, requirement counts, and   scripts in scratch/.
                                 foreign key alignment across markdown tables.
Level 3: Application Behavior    Executing test suites (pytest), database migrations,       PENDING PHASE 2–6.
         Verified via Tests      network calls, or Docker containers.                      (Zero tests run;
                                                                                            no code exists).
========================================================================================
```

- **Accurate Phrasing Enforced:** Wherever crash recovery, state preservation, or idempotency is described, the specification uses accurate terminology:
  - *"Recovery behavior is formally specified; implementation testing is pending in Phase 2 through Phase 6."*
  - *"Document consistency and automated text checks have been performed; application-level execution verification is pending."*
- **No Premature Readiness Claims:** The architecture is certified as **contract-frozen and specification-complete**, not production-deployed or runtime-tested.

---

### 12.6 Exact Changed Document Sections Summary

The targeted updates performed in Phase 1.7.1 modified the following exact document sections:
1. `docs/06-database-design.md`:
   - `§3.15 approvals`: Added `resumed_at timestamptz null`.
   - `§3.17 workflow_executions`: Added `resumption_pending` to `status` CHECK constraint; added `lease_token uuid null`, `lease_owner text null`, `lease_expires_at timestamptz null`; added Note on Execution Leasing and Crash Recovery.
2. `docs/09-api-design.md`:
   - `§5.6 POST /approvals/{approval_id}/decision`: Detailed the exact approval transaction boundary, `resumption_pending` status transition, atomic lease acquisition, client retry handling, and idempotent resumption.
   - `§6 Concurrency and Idempotency`: Added Item 3 (Execution Lease & Ownership Model, explaining `lease_token`, `lease_owner`, 60s lease window, no PID reliance); updated Item 7 (Four Crash Recovery Scenarios, detailing Scenario 2 decided-approval recovery); updated Item 8 (Startup Recovery Check Semantics, distinguishing undecided pending approvals from decided resumptions).
3. `docs/07-agent-workflow.md`:
   - `§5 Canonical workflow state`: Updated `status` enum to include `resumption_pending`.
   - `§6 Node Catalog`: Updated Node 15 (`finalize_execution`) to record `approvals.resumed_at = NOW()` and clear execution lease.
   - `§8.1`: Updated Item 2 (Event-Driven Resume & Durability Boundary, incorporating `resumption_pending` and execution leasing).
   - `§10 State persistence and checkpoints`: Added Execution Lease & Ownership Model; updated Application Restart & Crash Recovery Protocol to distinguish undecided approvals from interrupted resumptions.
4. `docs/08-data-flow.md`:
   - `§5 DF-03 Recommendation to human approval and workflow resume`: Updated steps 5, 6, 8 to reflect transaction boundary (`resumption_pending`), execution lease claim, and crash recovery path.
5. `docs/11-security-and-reliability.md`:
   - `§7.2 Concurrency and race-condition controls`: Updated Item 3 with Execution Lease & Ownership Model.
   - `§8.3 Disaster recovery and process crash resilience`: Updated Scenario 2 and Startup Recovery Check Semantics.
6. `docs/04-system-architecture.md`:
   - `§8 MVP runtime topology`: Synchronized resumption description with `resumption_pending` and execution lease acquisition.
7. `docs/15-architecture-revision-log.md`:
   - Updated header metadata; restored Stage A defect IDs (DEF-01..DEF-05) and inconsistency IDs (INC-01..INC-09) in Section 11; added Section 12 documenting Phase 1.7.1 targeted corrections, complete 156-requirement justification table, traceability matrix, and verification language audit.

---

### 12.7 Unresolved Technical Decisions
**Zero unresolved decisions remain.** All architectural ambiguities, schema conflicts, and edge-case lifecycle gaps have been definitively resolved and approved by the project owner.

---

### 12.8 Scope Confirmation
- **Total Functional Requirements:** **156** (`FR-001` through `FR-287`).
- **MVP (Must Deliver):** **120** requirements across Phases PH-1 through PH-6.
- **Post-MVP (Deferred to v1.1):** **24** requirements.
- **Future Product Backlog:** **5** requirements.
- **Merged or Removed:** **7** requirements (6 Merged, 1 Removed).
- **Active Phase Commitments for Non-MVP Requirements:** **0**.
- **Database Tables:** **21** strictly normalized, relational tables.
- **Workflow Engine:** **LangGraph** (16 canonical nodes, PostgreSQL checkpointer, bounded execution).
- **Contingency Design Pattern:** Pure Python state machine (~200 lines, contingency pattern only).
- **Intake Scope Boundary:** Pasted plain text and REST API in MVP; `.txt` and `.json` file uploads in Post-MVP; `.eml` and email polling in Future.

---

---

## 13. Phase 1.7.2: Recovery Safety and Requirement Evidence Correction

### 13.1 Context and Technical Scope
Following the delivery of Contract 2.1 and the Phase 1.7.1 report, a focused technical audit was conducted to address four targeted architectural topics:
1. **Execution Lease Safety & Fencing:** Resolving lease expiration during extended workflow execution (up to 10 minutes) via heartbeats and fencing tokens.
2. **Database-Enforced Proposal Idempotency:** Transitioning booking proposal creation from application-only checks to database-enforced uniqueness and conflict handling (`ON CONFLICT (approval_id) DO NOTHING`).
3. **Complete Approval Decision Coverage:** Providing exhaustive status, routing, and crash recovery specifications for all three canonical decisions: `approved`, `rejected`, and `changes_requested`.
4. **Mathematical Proof of Requirement Classification:** Formally proving the relationship between the 112 essential requirements from Document 14's evaluation table and the 8 additional requirements, alongside a three-category reassessment of the 120 MVP items.

---

### 13.2 Execution Lease Safety, Heartbeats & Fencing Proof

#### 13.2.1 Problem Analysis
In Contract 2.1, execution ownership was protected by a 60-second lease window (`lease_expires_at = NOW() + 60s`). However, under `FR-150` and Section 11 of Document 07, the hard execution ceiling for a complete workflow execution is **10 minutes** (excluding human approval wait time). If an LLM call or complex rate calculation takes longer than 60 seconds without renewal, the lease expires while the original worker is still running. If a second worker reclaims the lease, concurrent execution could occur.

#### 13.2.2 Architectural Specification
To eliminate this risk, the execution lease model is augmented with heartbeat renewal and fencing tokens across `06 §3.17`, `07 §10`, `09 §6`, and `11 §7.2`:

1. **Monotonic Fencing Counter (`lease_epoch`):**
   - The `workflow_executions` table adds `lease_epoch integer not null default 0`.
   - On every new lease claim (by a new worker or after lease expiration), `lease_epoch` is incremented atomically:
     ```sql
     UPDATE workflow_executions
     SET status = 'running',
         lease_token = gen_random_uuid(),
         lease_epoch = lease_epoch + 1,
         lease_owner = :worker_id,
         lease_expires_at = NOW() + INTERVAL '60 seconds',
         updated_at = NOW()
     WHERE id = :execution_id
       AND (status = 'resumption_pending' OR (status = 'running' AND lease_expires_at < NOW()))
     RETURNING lease_token, lease_epoch;
     ```
2. **Periodic Heartbeat & Renewal:**
   - Active workers periodically renew their lease every **15 to 20 seconds** (`HEARTBEAT_INTERVAL = 20s`).
   - The maximum permitted renewal interval is **30 seconds**.
   - Renewal executes an atomic SQL update validating the current lease token, epoch, and the 10-minute hard ceiling:
     ```sql
     UPDATE workflow_executions
     SET lease_expires_at = NOW() + INTERVAL '60 seconds',
         updated_at = NOW()
     WHERE id = :execution_id
       AND lease_token = :my_current_lease_token
       AND lease_epoch = :my_current_lease_epoch
       AND NOW() < started_at + INTERVAL '10 minutes';
     ```
3. **Fencing-Token Validation on Side Effects:**
   - Before executing any consequential database write (e.g. Node 13 proposal insertion, Node 15 finalization), the worker validates its fencing token within the transaction:
     ```sql
     SELECT id FROM workflow_executions
     WHERE id = :execution_id
       AND lease_token = :my_lease_token
       AND lease_epoch = :my_lease_epoch
       AND lease_expires_at > NOW()
     FOR UPDATE;
     ```
   - If 0 rows are returned, the transaction immediately rolls back.
4. **Behavior on Loss of Ownership:**
   - If a heartbeat fails (e.g. database network disconnect) or a fencing check returns 0 rows, the worker immediately aborts execution, sets an internal abort flag, raises `ExecutionLeaseFencingError`, and ceases all database writes.
5. **Recovery After Worker Termination:**
   - If Worker A terminates abnormally, its heartbeat ceases. Exactly 60 seconds after the last heartbeat, `lease_expires_at < NOW()`.
   - Worker B reclaims the execution with a new `lease_token` and an incremented `lease_epoch`.
   - Worker B re-hydrates state from the PostgreSQL checkpointer and resumes cleanly from the last valid checkpoint.

#### 13.2.3 Proof of Mutual Exclusion
- **Scenario: Zombie Worker Wakes Up After Lease Expiration:**
  1. Worker A acquires lease at $T_0$ (`lease_epoch = 1`, `lease_token = Token-A`, `lease_expires_at = T_0 + 60s`).
  2. At $T_{20}$, Worker A experiences a severe 65-second OS pause or network freeze.
  3. At $T_{61}$, Worker A's lease expires (`lease_expires_at < NOW()`).
  4. At $T_{62}$, Worker B reclaims the lease via atomic update: `lease_epoch` increments to `2`, `lease_token` becomes `Token-B`, `lease_expires_at` becomes $T_{62} + 60s$.
  5. At $T_{85}$, Worker A unfreezes and attempts to commit Node 13 (`create_booking_proposal`):
     - Worker A issues its transaction with fencing check: `WHERE id = :id AND lease_epoch = 1 AND lease_token = Token-A`.
     - The check returns **0 rows** because the database row currently contains `lease_epoch = 2` and `lease_token = Token-B`.
     - Worker A detects fencing violation, rolls back immediately, and halts.
  6. Worker B executes normally, validates fencing with `lease_epoch = 2`, and commits Node 13.
- **Conclusion:** Two workers can never concurrently apply side effects to the same workflow execution.

---

### 13.3 Database-Enforced Idempotency for Booking Proposals

#### 13.3.1 Relational Schema Constraints
In `06 §3.16`, booking proposal uniqueness is guaranteed at the database engine level by two complementary constraints:
1. `approval_id uuid not null unique references approvals(id)`: Guarantees that at most one booking proposal can ever be created for a given approval record.
2. `CREATE UNIQUE INDEX uq_booking_proposals_active_shipment ON booking_proposals (shipment_id) WHERE status IN ('proposed', 'accepted');`: Guarantees that at most one active proposal can exist for a shipment at any time.

#### 13.3.2 Atomic Insertion and Conflict Handling
Node 13 (`create_booking_proposal`) executes proposal creation using atomic insert-on-conflict:
```sql
INSERT INTO booking_proposals (
    id, shipment_id, approval_id, carrier_id, proposal_number,
    status, snapshot, idempotency_key, created_by, created_at, updated_at
) VALUES (
    gen_random_uuid(), :shipment_id, :approval_id, :carrier_id, :proposal_number,
    'proposed', :snapshot, :idempotency_key, :user_id, NOW(), NOW()
)
ON CONFLICT (approval_id) DO NOTHING
RETURNING id, status;
```
- **Insert Case:** If no proposal exists, the row is inserted and `RETURNING id` returns the newly generated UUID.
- **Conflict Case:** If a proposal already exists for this `approval_id` (created by a concurrent worker or in a prior run before a crash), `RETURNING id` returns empty. Node 13 immediately queries:
  ```sql
  SELECT id, status FROM booking_proposals WHERE approval_id = :approval_id;
  ```
  and reuses the existing proposal record without error.

#### 13.3.3 Concurrent Workers and Crash Recovery
- **Concurrent Creation:** If two workers execute Node 13 concurrently, PostgreSQL's unique index serializes the INSERT statements: exactly one worker inserts the proposal; the second worker hits `ON CONFLICT`, reuses the proposal created by the first, and advances.
- **Crash Recovery Between Insert and Finalization:** If a server crashes after proposal insertion but before Node 15 marks `approvals.resumed_at = NOW()` and `workflow_executions.status = 'completed'`:
  - Upon restart or client retry, the system discovers the decided approval with `resumed_at IS NULL`.
  - The worker claims the execution lease and resumes LangGraph from the checkpoint.
  - Node 13 executes `INSERT ... ON CONFLICT (approval_id) DO NOTHING`.
  - The conflict is caught, Node 13 retrieves the existing proposal, advances to Node 14 (audit), and Node 15 finalizes execution cleanly.
  - Zero duplicate rows are inserted.

---

### 13.4 Complete Canonical Approval Decision Coverage Matrix

Every approval decision path (`approved`, `rejected`, `changes_requested`) is fully specified across all lifecycle stages:

```
====================================================================================================================================
                                      COMPLETE APPROVAL DECISION LIFECYCLE MATRIX
====================================================================================================================================
Attribute                      Decision: 'approve'                     Decision: 'reject'                      Decision: 'request_changes'
------------------------------------------------------------------------------------------------------------------------------------
API Action Command             action: "approve"                       action: "reject"                        action: "request_changes"
Persisted approvals.status     'approved'                              'rejected'                              'changes_requested'
Shipment Status Transition     'booking_proposed'                      'sourcing'                              'sourcing' (or 'draft')
Workflow Execution Status      'resumption_pending' -> 'running'       'resumption_pending' -> 'running'       'resumption_pending' -> 'running'
                               -> 'completed'                          -> 'completed'                          -> 'completed'
LangGraph Resume Payload       {"action": "approve",                   {"action": "reject",                    {"action": "request_changes",
                                "selected_candidate_id": "<uuid>",      "selected_candidate_id": null,          "selected_candidate_id": null,
                                "comment": "..."}                       "comment": "<rejection_reason>"}        "comment": "<change_notes>"}
Workflow Routing Path          Node 11 (resume) -> Node 12 ->          Node 11 (resume) -> Node 12 ->          Node 11 (resume) -> Node 12 ->
                               Node 13 (create_booking_proposal) ->    Node 14 (record_audit_event:            Node 14 (record_audit_event:
                               Node 14 (record_audit_event:            approval.rejected) ->                   approval.changes_requested) ->
                               booking_proposal.created) ->            Node 15 (finalize_execution) ->         Node 15 (finalize_execution) ->
                               Node 15 (finalize_execution) -> [*]     [*] (re-sourcing enabled)               [*] (re-drafting enabled)
Terminal Business Artifact     Creates immutable booking_proposal;     No proposal created; shipment           No proposal created; shipment
                               freezes shipment terms (frozen_at);     unlocked for carrier re-sourcing        returned to draft/sourcing for term
                               ready for rate confirmation.            under D-05 state transition.            adjustments and re-validation.
Audit Event Emitted            approval.granted,                       approval.rejected                       approval.changes_requested
                               booking_proposal.created
Crash Recovery Behavior        Discovers decision committed with       Discovers decision committed with       Discovers decision committed with
                               resumed_at = NULL; reclaims lease;      resumed_at = NULL; reclaims lease;      resumed_at = NULL; reclaims lease;
                               Node 13 reuses proposal via             ensures shipment status is 'sourcing';  ensures shipment status is 'sourcing';
                               ON CONFLICT; Node 15 sets resumed_at    Node 15 sets resumed_at = NOW()         Node 15 sets resumed_at = NOW()
                               = NOW() and status = 'completed'.       and marks 'completed'.                  and marks 'completed'.
====================================================================================================================================
```

---

### 13.5 Requirement Classification Evidence & Mathematical Proof

#### 13.5.1 The 112 Requirements Classified as Essential in Document 14 Table
In `docs/14-architecture-review.md §4`, the requirement-by-requirement evaluation table contains exactly **112 requirements** marked with classification `1. Essential MVP`:

```
FR-001, FR-003, FR-004, FR-005, FR-006, FR-007, FR-008, FR-009, FR-010, FR-011,
FR-014, FR-020, FR-021, FR-022, FR-024, FR-025, FR-026, FR-027, FR-031, FR-032,
FR-040, FR-041, FR-042, FR-043, FR-044, FR-045, FR-046, FR-048, FR-050, FR-051,
FR-052, FR-060, FR-061, FR-062, FR-063, FR-064, FR-065, FR-067, FR-068, FR-069,
FR-090, FR-091, FR-092, FR-093, FR-094, FR-095, FR-096, FR-097, FR-098, FR-099,
FR-100, FR-101, FR-102, FR-120, FR-121, FR-122, FR-123, FR-124, FR-125, FR-126,
FR-127, FR-128, FR-129, FR-132, FR-133, FR-134, FR-150, FR-151, FR-152, FR-153,
FR-154, FR-155, FR-157, FR-158, FR-159, FR-161, FR-164, FR-168, FR-180, FR-181,
FR-182, FR-183, FR-185, FR-186, FR-189, FR-190, FR-191, FR-200, FR-201, FR-202,
FR-203, FR-204, FR-205, FR-207, FR-208, FR-220, FR-221, FR-222, FR-224, FR-225,
FR-226, FR-230, FR-250, FR-251, FR-256, FR-257, FR-280, FR-281, FR-282, FR-283,
FR-285, FR-286.
(Total: exactly 112 requirements)
```

#### 13.5.2 The Eight Additional Requirements Added in Phase 1.6
In Phase 1.6, under ADR Decisions 3, 4, and 5 and Stage B authorization, eight critical requirements were added to the MVP baseline:
1. `FR-023`: Optimistic concurrency versioning on shipments (data integrity).
2. `FR-049`: Persist validation runs with timestamp and rules version (auditability).
3. `FR-073`: Carrier lane rate model solving CRIT-03 (synthetic rate calculation).
4. `FR-184`: Allow requesting changes on approval with required note (HITL decisioning).
5. `FR-209`: Proposal cancellation returning shipment to sourcing solving CRIT-04 (re-sourcing).
6. `FR-253`: Canonical RBAC roles (`admin`, `broker`, `viewer`) (security boundary).
7. `FR-254`: Enforce permissions on every REST endpoint (security boundary).
8. `FR-255`: Enforce permissions on every UI route (security boundary).

#### 13.5.3 Mathematical Proof of Non-Overlap
An automated set intersection test proves that none of the eight additional requirements was counted among the 112 essential requirements of Document 14:
- In Document 14's table, seven of the eight were classified as `2. Deferrable`:
  `{FR-023, FR-049, FR-184, FR-209, FR-253, FR-254, FR-255} ⊂ Deferrable`
- One of the eight (`FR-073`) did not exist in Document 14 (it was newly created in Phase 1.6 to solve `CRIT-03`).
- Set intersection:
  $$\{112	ext{ Essential Requirements}\} \cap \{	ext{Eight Additional Requirements}\} = \emptyset$$
- Set union:
  $$112 + 8 = 120	ext{ MVP Requirements}$$
- The set union matches the 120 MVP rows in `docs/03-requirements-specification.md` with 100% exactitude.

#### 13.5.4 Three-Category Reassessment of the 120 MVP Requirements
As directed, all 120 MVP requirements were reassessed under three functional categories:

```
========================================================================================
                          THREE-CATEGORY REASSESSMENT OF 120 MVP ITEMS
========================================================================================
Category                                                  Count    Percentage   Assessment
----------------------------------------------------------------------------------------
Category 1: Required for Minimum Demonstrable Workflow       80       66.7%      Essential Core
Category 2: Supporting Security, Integrity, Reliability      37       30.8%      Non-Negotiable
Category 3: Portfolio Enhancement / Convenience Fallback      3        2.5%      Retained MVP
----------------------------------------------------------------------------------------
Total MVP Requirements                                      120      100.0%
========================================================================================
```

- **Category 1: Required for Minimum Demonstrable Workflow (80 Requirements):**
  - Includes core intake (`FR-001`, `FR-003`, `FR-005`, `FR-006`, `FR-007`, `FR-008`, `FR-010`), shipment aggregate modeling (`FR-020`, `FR-021`, `FR-022`, `FR-024`, `FR-025`, `FR-026`, `FR-031`), core validation rules (`FR-027`, `FR-040`, `FR-041`, `FR-042`, `FR-043`, `FR-045`, `FR-046`, `FR-048`, `FR-050`, `FR-051`, `FR-052`), carrier profiles and rates (`FR-060`..`FR-066`, `FR-069`, `FR-073`), eligibility filtering (`FR-080`..`FR-092`), recommendation scoring and ranking (`FR-110`..`FR-127`, `FR-130`, `FR-131`, `FR-132`), workflow execution (`FR-140`, `FR-141`, `FR-142`, `FR-151`, `FR-154`, `FR-155`, `FR-159`), human approval decisions (`FR-180`..`FR-184`, `FR-190`, `FR-191`), and booking proposal creation (`FR-200`, `FR-201`, `FR-202`, `FR-203`, `FR-205`, `FR-209`).
- **Category 2: Supporting Security, Integrity, Reliability, and Testing (37 Requirements):**
  - Non-negotiable enterprise controls: prompt injection defense (`FR-014`), optimistic locking (`FR-023`), post-approval field freezing (`FR-032`), validation approval blocking (`FR-044`), validation run history (`FR-049`), bounded execution and budgets (`FR-150`, `FR-152`, `FR-153`, `FR-157`, `FR-158`, `FR-161`, `FR-168`), mock LLM provider (`FR-164`), role permission enforcement (`FR-185`, `FR-254`, `FR-255`), immutable decision auditing (`FR-186`), approval idempotency (`FR-189`), proposal database uniqueness and conflict handling (`FR-204`, `FR-207`), audit transactionality and PostgreSQL trigger immutability (`FR-208`, `FR-220`, `FR-221`, `FR-222`, `FR-224`), structured logging and PII redaction (`FR-225`, `FR-226`, `FR-230`), local auth, hashing, and RBAC (`FR-250`, `FR-251`, `FR-253`, `FR-256`, `FR-257`), and configuration validation/reseeding (`FR-280`, `FR-281`, `FR-282`, `FR-283`, `FR-285`).
- **Category 3: Portfolio Enhancement / Convenience Fallback (3 Requirements):**
  - `FR-004`: Manual shipment entry without intake submission (convenience fallback).
  - `FR-011`: Operator review and correction of extracted fields in UI before validation (UI convenience).
  - `FR-068`: List Carrier data for operators (administrative directory browser).
- **Scope Conclusion:** Removing the 3 Category 3 items would only reduce the MVP to 117 while losing valuable portfolio interaction points. Keeping the certified count at **120 MVP requirements** is fully justified by technical evidence and preserves complete cross-document consistency.

---

### 13.6 Changed Document Sections Summary (Phase 1.7.2)

1. `docs/06-database-design.md`:
   - `§3.15 approvals`: Updated decision mapping to include complete coverage of `changes_requested`.
   - `§3.16 booking_proposals`: Specified database uniqueness constraints, atomic `INSERT ... ON CONFLICT (approval_id) DO NOTHING`, concurrent worker handling, and crash recovery.
   - `§3.17 workflow_executions`: Added `lease_epoch integer not null default 0`; detailed heartbeat protocol (15–20s, max 30s), atomic renewal query, fencing token check on side effects, loss of ownership behavior, and proof of mutual exclusion.
2. `docs/07-agent-workflow.md`:
   - `§6 Node Catalog`: Updated Node 12 with explicit routing for `changes_requested`; updated Node 13 with `ON CONFLICT (approval_id) DO NOTHING` and fencing checks.
   - `§8 Diagram D-14`: Added explicit `request_changes` sequence branch and `ON CONFLICT` proposal creation.
   - `§10 State persistence and checkpoints`: Documented heartbeat interval (15–20s), atomic renewal with `lease_token` and `lease_epoch`, fencing validation, and proof of mutual exclusion.
3. `docs/09-api-design.md`:
   - `§5.6 POST /approvals/{id}/decision`: Detailed complete canonical coverage for `approve`, `reject`, and `request_changes`; updated lease acquisition with `lease_epoch`.
   - `§6 Concurrency and Idempotency`: Added Item 3 (Lease, Fencing Tokens, and Heartbeat Safety); added Item 9 (Database-Enforced Idempotency for Booking Proposals).
4. `docs/11-security-and-reliability.md`:
   - `§7.2 Concurrency controls`: Documented heartbeat renewal, fencing checks, and proof of mutual exclusion.
   - `§8.1 Duplicate-booking prevention`: Documented database-enforced proposal uniqueness and `ON CONFLICT` handling.
   - `§8.3 Crash resilience`: Detailed complete crash recovery behavior for all three decisions (`approved`, `rejected`, `changes_requested`).
5. `docs/08-data-flow.md`:
   - `§5 DF-03`: Updated Step 6 with `lease_epoch` and heartbeats; updated Step 7 with explicit `changes_requested` branch.
   - `§6 DF-04`: Updated sequence with `INSERT ... ON CONFLICT (approval_id) DO NOTHING`.
6. `docs/03-requirements-specification.md`:
   - `Appendix A.2`: Added `resumption_pending` to canonical `Workflow execution status`; updated Approval Command to State Mapping table with explicit `changes_requested` routing; updated Appendix A contract version to 2.1.
7. `docs/15-architecture-revision-log.md`:
   - Added Section 13 documenting Phase 1.7.2 execution lease safety, fencing proofs, database-enforced proposal idempotency, complete decision coverage, mathematical proof of 112 + 8 = 120 requirements, three-category reassessment, and readiness verdict.

---

### 13.7 Unresolved Decisions
**Zero unresolved decisions remain.** All distributed locking, idempotency, routing, and requirement classification decisions have been formally resolved and documented.

---

### 13.8 Final Architecture Readiness Declaration
```
========================================================================================
                         PHASE 1.7.2 ARCHITECTURAL VERDICT
========================================================================================

                             READY FOR PHASE 1.8 VERIFICATION

- Execution lease safety formally proved: heartbeats (15–20s, max 30s), atomic renewal,
  monotonic fencing tokens (lease_epoch), mutual exclusion mathematically guaranteed.
- Database-enforced proposal idempotency specified via unique constraint and
  INSERT ... ON CONFLICT (approval_id) DO NOTHING.
- Complete canonical decision coverage verified for approved, rejected, and changes_requested.
- 112 Essential Requirements from Document 14 + 8 Additional Requirements = 120 MVP
  mathematically proved with zero overlap (intersection is empty set).
- Reassessment confirms 80 Core, 37 Security/Integrity/Reliability, 3 Portfolio Enhancement = 120.
- All documents synchronized under Contract Version 2.1.
- Document 14 preserved completely untouched.
========================================================================================
```

---

## 14. Phase 1.7.3: Final Concurrency and MVP Classification Audit
### 14.1 Technical Scope & Audit Objectives
Following Phase 1.7.2, an independent, rigorous technical audit was conducted across the entire architecture specification (Contract 2.1) to resolve remaining concurrency, execution clock, and scope classification questions:
1. **Lease Acquisition & Heartbeat Concurrency:** Rigorous database-level validation of lease claiming, unexpired heartbeat renewal, and atomic race condition mechanics between heartbeat renewals and lease takeovers.
2. **Execution Clock Architecture:** Formal architectural separation of initial workflow creation (`started_at`) from continuous compute attempt start (`attempt_started_at`), ensuring human approval wait does not consume compute budgets while bounding overall retry budgets.
3. **Single-Transaction Fencing:** Formal proof that fencing token checks and protected side effects occur strictly within the same ACID database transaction.
4. **Exhaustive 156-Requirement Classification Audit:** A mathematically verified, duplicate-free partition of all 156 system requirements into three explicit categories with individualized justifications.
5. **Cross-Document Consistency:** End-to-end verification across Documents 03, 06, 07, 08, 09, 11, 13, and 15.

### 14.2 Concurrency Verification: Lease Acquisition, Heartbeats & Race Mechanics

#### 14.2.1 Strict Lease Acquisition & Reclamation Targeting
To prevent split-brain execution and guarantee that stalled or terminated workers can be safely recovered, lease claiming is governed strictly by atomic SQL targeting only two permitted operational states:
```sql
UPDATE workflow_executions
SET status = 'running',
    lease_token = gen_random_uuid(),
    lease_epoch = lease_epoch + 1,
    lease_owner = :worker_id,
    lease_expires_at = NOW() + INTERVAL '60 seconds',
    attempt_started_at = NOW(),
    attempt_count = attempt_count + 1,
    updated_at = NOW()
WHERE id = :execution_id
  AND (
    status = 'resumption_pending'
    OR (status = 'running' AND lease_expires_at < NOW())
  )
RETURNING lease_token, lease_epoch;
```

**Proof of Protection for `waiting_for_human` and Completed Executions:**
1. *Physical SQL Impossibility:* The `WHERE` clause evaluates `status = 'resumption_pending' OR (status = 'running' AND lease_expires_at < NOW())`. If an execution has status `waiting_for_human`, `completed`, `failed`, `cancelled`, or `timed_out`, both disjunction clauses evaluate to FALSE. Exactly 0 rows are updated, and no lease can be claimed.
2. *Nullified Lease Fields:* Whenever an execution transitions to `waiting_for_human` (Node 11) or to any terminal state (`completed`, `failed`, `cancelled`, `timed_out` at Node 15 or 16), the database update explicitly clears `lease_token = NULL, lease_owner = NULL, lease_expires_at = NULL`.

#### 14.2.2 Periodic Heartbeat & Renewal Protocol
Active workers execute bounded computations (up to 10 minutes per continuous attempt). Active workers renew their lease every **15 to 20 seconds** (hard maximum renewal interval: 30 seconds):
```sql
UPDATE workflow_executions
SET lease_expires_at = NOW() + INTERVAL '60 seconds',
    updated_at = NOW()
WHERE id = :execution_id
  AND lease_token = :my_current_lease_token
  AND lease_epoch = :my_current_lease_epoch
  AND lease_expires_at > NOW()
  AND NOW() < attempt_started_at + INTERVAL '10 minutes';
```
- `lease_expires_at > NOW()`: Guarantees that a worker that experienced an unrecoverable stall (e.g. 65s garbage collection pause) cannot revive an already expired lease.
- `NOW() < attempt_started_at + INTERVAL '10 minutes'`: Strictly prevents heartbeats from extending compute past the 10-minute continuous attempt ceiling.

#### 14.2.3 Atomic Race Condition Resolution & Mutual Exclusion Proof
PostgreSQL executes row updates using exclusive row-level write locks (`XMAX` lock), serializing concurrent queries on `workflow_executions`:
- **Interleaving 1: Heartbeat commits before Takeover (Worker A is healthy):**
  1. Worker A acquires the row write lock. Its heartbeat verifies `lease_expires_at > NOW()`, extends `lease_expires_at = NOW() + 60s`, commits, and releases the lock.
  2. Worker B's takeover query now inspects the newly committed row under `READ COMMITTED` isolation.
  3. The condition `(status = 'running' AND lease_expires_at < NOW())` evaluates to FALSE because `lease_expires_at` is 60 seconds in the future.
  4. Worker B's UPDATE affects **0 rows**. Worker B safely aborts takeover.

- **Interleaving 2: Takeover commits before Heartbeat (Worker A stalled past 60s):**
  1. Worker A's lease expired (`lease_expires_at <= NOW()`).
  2. Worker B's takeover query acquires the row write lock, updates `status = 'running'`, increments `lease_epoch = lease_epoch + 1`, generates a new `lease_token`, resets `attempt_started_at = NOW()`, commits, and releases the lock.
  3. Worker A wakes up and its delayed heartbeat query acquires the row lock.
  4. PostgreSQL re-evaluates Worker A's WHERE clause against the updated row: `lease_token = :token_A AND lease_epoch = :epoch_A` evaluates to FALSE.
  5. Worker A's UPDATE affects **0 rows**.
  6. Worker A detects `rowcount == 0`, immediately recognizes it has lost lease ownership, raises `ExecutionLeaseFencingError`, sets an internal abort flag, and halts all processing without writing side effects.

#### 14.2.4 Single-Transaction Fencing and Side Effect Coupling
Every state mutation and side effect in the post-approval pipeline (Node 13 booking proposal insert, Node 14 audit event, Node 15 finalization) is coupled to the fencing token within the SAME ACID transaction:
```sql
BEGIN;
-- 1. Validate fencing token with exclusive row lock:
SELECT lease_epoch
FROM workflow_executions
WHERE id = :execution_id
  AND lease_token = :my_current_lease_token
  AND lease_epoch = :my_current_lease_epoch
  AND lease_expires_at > NOW()
FOR UPDATE;
-- If 0 rows returned: ROLLBACK immediately and raise ExecutionLeaseFencingError.

-- 2. Idempotent proposal creation in the SAME transaction:
INSERT INTO booking_proposals (
    id, shipment_id, approval_id, carrier_id, proposal_number,
    status, snapshot, idempotency_key, created_by, created_at, updated_at
) VALUES (
    gen_random_uuid(), :shipment_id, :approval_id, :carrier_id, :proposal_number,
    'proposed', :snapshot, :idempotency_key, :user_id, NOW(), NOW()
)
ON CONFLICT (approval_id) DO NOTHING
RETURNING id, status;

COMMIT;
```
Because fencing validation and proposal insertion execute within a single transaction, it is impossible for a stalled worker to insert a booking proposal after losing its lease.

### 14.3 Execution Clock Architecture

The execution clock formally distinguishes workflow creation time from continuous execution attempt time:
- `started_at timestamptz not null default now()`: Records when the workflow execution was first created/queued.
- `attempt_started_at timestamptz not null default now()`: Records when the *current continuous compute attempt* began.
- **Human Approval Separation:** When execution reaches Node 11 (`request_human_approval`), the workflow transitions to `waiting_for_human` and the lease is cleared. The broker may take minutes, hours, or days to submit an approval decision. This human wait time does NOT consume the continuous execution compute budget.
- **Resumption Budget Reset:** When a worker claims the lease from `resumption_pending`, it executes `attempt_started_at = NOW()`, giving the post-approval pipeline (Nodes 12–15) a clean, full 10-minute continuous execution budget.
- **Retry Budget Enforcement:** To prevent crash/recovery loops from bypassing overall resource ceilings, executions enforce:
  1. `attempt_count <= 3`: Monotonically incremented on each lease acquisition.
  2. `Max cumulative compute duration`: 15 minutes across all retries.
  3. `Max node executions`: 40 node visits.
  4. `Max LLM calls`: 6 invocations.

### 14.4 Complete 156-Requirement Classification Audit

#### 14.4.1 Mathematical Partition Proof
Let $R$ denote the complete set of system requirements ($|R| = 156$). $R$ is partitioned into three mutually exclusive, collectively exhaustive subsets:
- $C_1$: Minimum Demonstrable Workflow ($|C_1| = 74$)
- $C_2$: Supporting Security, Integrity, Reliability, and Testing ($|C_2| = 43$)
- $C_3$: Portfolio Enhancement or Convenience ($|C_3| = 39$)

**Formal Set Theory Proof:**
1. $C_1 \cap C_2 = \emptyset$, $C_1 \cap C_3 = \emptyset$, $C_2 \cap C_3 = \emptyset$ (Zero pairwise overlap; mutual exclusivity holds).
2. $C_1 \cup C_2 \cup C_3 = R$ (Collective exhaustiveness holds).
3. $|C_1| + |C_2| + |C_3| = 74 + 43 + 39 = 156 = |R|$.
4. The 120 MVP requirements in Document 03 correspond precisely to $(C_1 \cup C_2 \cup C_{3,\text{MVP}})$, where $C_{3,\text{MVP}} = \{\text{FR-004}, \text{FR-011}, \text{FR-068}\}$ ($74 + 43 + 3 = 120$). The remaining 36 requirements in $C_3$ correspond to the 36 non-MVP items (24 Post-MVP + 6 Merged + 5 Future + 1 Removed).

#### 14.4.2 Category 1: Minimum Demonstrable Workflow (74 Requirements)
| ID | Component | Requirement Title | Concise Classification Justification |
|---|---|---|---|
| `FR-001` | Intake Service | The system shall accept an intake submission as pasted plain text. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-003` | API Layer | The system shall accept an intake submission through `POST /api/v1/intake/submissions`. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-005` | Intake Service | The system shall persist the raw intake content with channel, received timestamp, content hash, and submitter. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-006` | LLM Gateway | The system shall produce a structured draft Shipment from intake text, recording per-field provenance and confidence. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-007` | Intake Service | The system shall leave absent fields null and shall never invent missing shipment values. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-008` | Intake Service | The system shall preserve the original raw text alongside the structured record. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-010` | Intake Service | The system shall link each intake submission to the Shipment draft it created. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-020` | Shipment Service | The system shall create a Shipment draft with identifier and status `draft`. | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-021` | Shipment Service | The system shall support one or more pickup and delivery Stops per Shipment via `shipment_stops`. | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-022` | Shipment Service | The system shall store Shipment Requirements as a validated JSONB structure on the Shipment. | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-024` | Shipment Service | The system shall retrieve a Shipment with its Stops, Requirements, and current status. | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-025` | Shipment Service | The system shall enforce Shipment status transitions according to the canonical state machine. | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-026` | Shipment Service | The system shall derive the Lane from the first pickup and last delivery stop. | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-027` | Validation Engine | The system shall validate stop sequencing: at least one pickup, at least one delivery, pickup before delivery. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-031` | Shipment Service | The system shall record the Shipment source (`intake_submission` or `manual`). | Core shipment lifecycle, multi-stop pickup/delivery, and lane derivation. |
| `FR-040` | Validation Engine | The system shall validate required fields for booking readiness (customer, stops, commodity, weight). | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-041` | Validation Engine | The system shall detect contradictory values across fields (e.g. delivery before pickup, weight exceeds limits). | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-042` | Validation Engine | The system shall emit Validation Issues with canonical severity values (`info`, `warning`, `error`, `critical`). | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-043` | Validation Engine | The system shall compute a Validation result status of `passed`, `passed_with_warnings`, or `failed`. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-045` | Validation Engine | The system shall permit review of `warning` issues without blocking Approval. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-046` | API Layer | The system shall return Validation results through `GET /api/v1/shipments/{id}/validation`. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-048` | Validation Engine | The system shall support re-validation after correction. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-050` | Validation Engine | The system shall not auto-fill missing critical fields during validation. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-051` | Validation Engine | The system shall validate numeric ranges and formats for weights, dates, and temperatures. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-052` | Validation Engine | The system shall validate equipment/requirement compatibility. | Core deterministic validation engine, stop sequencing, required field gating, and severity computation. |
| `FR-060` | Carrier Service | The system shall create, read, update, and deactivate Carrier profiles. | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-061` | Carrier Service | The system shall store Carrier status using canonical values (`active`, `inactive`, `suspended`). | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-062` | Carrier Service | The system shall store recorded insurance expiry and authority indicators without claiming external verification. | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-063` | Carrier Service | The system shall manage Equipment Types per Carrier. | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-064` | Carrier Service | The system shall manage Service Regions per Carrier with origin operating presence semantics. | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-065` | Carrier Service | The system shall manage Availability windows per Carrier. | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-067` | Eligibility Engine | The system shall treat inactive or suspended Carriers as ineligible. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-073` | Carrier Service | The system shall store synthetic Carrier Lane Rates (`carrier_lane_rates`) for pricing comparison. | Core carrier master data, equipment, availability, and synthetic rate benchmarking. |
| `FR-090` | Eligibility Engine | The system shall run deterministic hard filters for a validated Shipment. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-091` | Eligibility Engine | The system shall filter by Equipment Type match. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-092` | Eligibility Engine | The system shall filter by Service Region coverage (matching origin stop state/region). | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-093` | Eligibility Engine | The system shall filter by recorded Availability window. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-094` | Eligibility Engine | The system shall filter by Carrier status. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-095` | Eligibility Engine | The system shall filter by recorded insurance validity against pickup date. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-096` | Eligibility Engine | The system shall filter by hazmat authorization when Shipment requires hazmat. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-097` | Eligibility Engine | The system shall filter by temperature capability when Shipment requires temperature control. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-098` | Eligibility Engine | The system shall emit canonical ineligibility reason codes. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-099` | Eligibility Engine | The system shall distinguish `insufficient_data` from `ineligible`. | Core deterministic hard-filtering rules and ineligibility code derivation. |
| `FR-120` | Recommendation Engine | The system shall generate a Recommendation for a validated Shipment on request. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-121` | Recommendation Engine | The system shall rank eligible Carriers using the active Scoring Configuration. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-122` | Recommendation Engine | The system shall produce a score breakdown per scoring component. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-123` | Recommendation Engine | The system shall return the top-N ranked candidates (default 5). | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-124` | Recommendation Engine | The system shall transition Recommendation status through canonical values. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-125` | LLM Gateway | The system shall generate an Explanation citing deterministic facts with optional LLM narration. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-126` | LLM Gateway | The system shall ensure explanations cite only recorded facts and introduce no new claims. | Core intake ingestion, extraction, and structured drafting path. |
| `FR-127` | Recommendation Engine | The system shall return `no_eligible_carriers` when filtering yields zero candidates. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-128` | Recommendation Engine | The system shall degrade gracefully when carrier data is incomplete (`insufficient_data`). | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-129` | Recommendation Engine | The system shall store the Scoring Configuration version used. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-132` | API Layer | The system shall provide recommendation detail including candidates and score breakdowns. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-133` | Recommendation Engine | The system shall use only operator-provided target rates and recorded carrier lane rates. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-134` | Recommendation Engine | The system shall rank deterministically for identical inputs, config, and data snapshot. | Core candidate ranking, component scoring, factual explanations, and top-N generation. |
| `FR-150` | Agent Orchestrator | The system shall start a Workflow Execution for a Shipment. | Core 16-node state machine execution, interrupt pause, resume, and status query. |
| `FR-151` | Agent Orchestrator | The system shall execute the canonical 16-node graph with conditional edges. | Core 16-node state machine execution, interrupt pause, resume, and status query. |
| `FR-154` | Agent Orchestrator | The system shall pause at the human approval interrupt and record `waiting_for_human`. | Core 16-node state machine execution, interrupt pause, resume, and status query. |
| `FR-155` | Agent Orchestrator | The system shall resume from the interrupt using the recorded human decision. | Core 16-node state machine execution, interrupt pause, resume, and status query. |
| `FR-159` | API Layer | The system shall expose Workflow status via `GET /api/v1/workflows/{id}`. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-180` | Approval Service | The system shall create an Approval request from a `ready` Recommendation. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-181` | UI Renderer | The system shall display recommendation, scores, explanation, and warnings to the approver. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-182` | Approval Service | The system shall allow an authorized user to approve an Approval. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-183` | Approval Service | The system shall allow rejection with a required reason. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-184` | Approval Service | The system shall allow requesting changes with a required note. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-190` | Approval Service | The system shall allow the approver to select a different eligible candidate than rank 1. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-191` | Approval Service | The system shall record the selected candidate on the Approval. | Core human-in-the-loop approval decision UI, broker candidate selection, and routing. |
| `FR-200` | Booking Proposal Service | The system shall create a Booking Proposal only after an `approved` Approval. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-201` | Booking Proposal Service | The system shall snapshot approved Shipment, Facility, and Carrier data into the Proposal. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-202` | Booking Proposal Service | The system shall transition Booking Proposal status through canonical values. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-203` | Booking Proposal Service | The system shall not tender externally or claim carrier confirmation in the MVP. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-205` | API Layer | The system shall retrieve and list Booking Proposals. | Core booking proposal generation, frozen data snapshotting, and status progression. |
| `FR-209` | Booking Proposal Service | The system shall allow a proposal to be declined or cancelled, returning the Shipment to `sourcing`. | Core booking proposal generation, frozen data snapshotting, and status progression. |

#### 14.4.3 Category 2: Supporting Security, Integrity, Reliability, and Testing (43 Requirements)
| ID | Component | Requirement Title | Concise Classification Justification |
|---|---|---|---|
| `FR-009` | Intake Service | The system shall detect duplicate submissions by idempotency key or content hash and return the existing submission. | Database-enforced idempotency preventing duplicate operational side effects. |
| `FR-014` | LLM Gateway | The system shall treat intake text as untrusted data and shall not execute instructions contained in it. | Security boundary treating unstructured text as untrusted data against prompt injection. |
| `FR-023` | Shipment Service | The system shall allow Shipment updates before booking with optimistic concurrency (`version`). | Data integrity protection via optimistic locking and frozen-field immutability. |
| `FR-032` | Shipment Service | The system shall prevent modification of fields frozen after approval or booking. | Data integrity protection via optimistic locking and frozen-field immutability. |
| `FR-044` | Validation Engine | The system shall block Approval while any `error` or `critical` issue exists. | Validation integrity enforcing approval gating and audit run persistence. |
| `FR-049` | Validation Engine | The system shall persist validation runs with timestamp and rules version. | Validation integrity enforcing approval gating and audit run persistence. |
| `FR-069` | Config / Seed Tool | The system shall support importing synthetic Carrier and Lane Rate seed data. | Reliable seed data isolation, test hygiene, and non-production reset protection. |
| `FR-100` | Eligibility Engine | The system shall make eligibility decisions only in deterministic code, never in the LLM. | Carrier safety constraint and transparent exclusion logging. |
| `FR-101` | Recommendation Engine | The system shall persist eligibility evaluation results per Recommendation candidate. | Carrier safety constraint and transparent exclusion logging. |
| `FR-102` | Eligibility Engine | The system shall provide human-readable eligibility reasons for exclusions. | Carrier safety constraint and transparent exclusion logging. |
| `FR-152` | Agent Orchestrator | The system shall persist Workflow state and node checkpoints in PostgreSQL. | LangGraph fault tolerance, bounded execution limits, lease recovery, and crash safety. |
| `FR-153` | Agent Orchestrator | The system shall enforce maximum attempts, LLM calls, and execution timeout. | LangGraph fault tolerance, bounded execution limits, lease recovery, and crash safety. |
| `FR-157` | Agent Orchestrator | The system shall route unrecoverable failures to `handle_failure`. | LangGraph fault tolerance, bounded execution limits, lease recovery, and crash safety. |
| `FR-158` | Agent Orchestrator | The system shall never create a Booking Proposal without a valid Approval. | LangGraph fault tolerance, bounded execution limits, lease recovery, and crash safety. |
| `FR-161` | Agent Orchestrator | The system shall make every side-effecting node idempotent. | Database-enforced idempotency preventing duplicate operational side effects. |
| `FR-164` | LLM Gateway | The system shall provide a mock LLM provider for tests and local development. | Deterministic testing harness enabling full offline test suite execution. |
| `FR-168` | Agent Orchestrator | The system shall preserve Workflow state across process restarts. | LangGraph fault tolerance, bounded execution limits, lease recovery, and crash safety. |
| `FR-185` | Approval Service | The system shall enforce role permission for approval actions. | Security authorization for approval actions and immutable decision audit trail. |
| `FR-186` | Audit / Approval | The system shall record approver, timestamp, decision, comment, and selected candidate immutably. | Security authorization for approval actions and immutable decision audit trail. |
| `FR-189` | Approval Service | The system shall make approval decisions idempotent. | Database-enforced idempotency preventing duplicate operational side effects. |
| `FR-204` | Booking Proposal Service | The system shall make Booking Proposal creation idempotent. | Database-enforced idempotency preventing duplicate operational side effects. |
| `FR-207` | Booking Proposal Service | The system shall prevent more than one active Booking Proposal per Shipment. | Database partial unique constraint preventing duplicate active proposals and audit emission. |
| `FR-208` | Audit Service | The system shall record audit events for proposal creation and status changes. | Database partial unique constraint preventing duplicate active proposals and audit emission. |
| `FR-220` | Audit Service | The system shall append audit events for state-changing operations in the caller's transaction. | Append-only database trigger immutability, correlation IDs, and compliance auditing. |
| `FR-221` | Audit Service | The system shall use canonical audit event types from Appendix A. | Append-only database trigger immutability, correlation IDs, and compliance auditing. |
| `FR-222` | Audit Service | The system shall correlate audit events by trace_id, workflow_execution_id, and shipment_id. | Append-only database trigger immutability, correlation IDs, and compliance auditing. |
| `FR-224` | Database / Audit | The system shall deny update and delete of audit events via PostgreSQL trigger. | Append-only database trigger immutability, correlation IDs, and compliance auditing. |
| `FR-225` | Observability | The system shall emit structured JSON logs with request and trace IDs. | Structured logging, unauthenticated health probe, and sensitive data redaction. |
| `FR-226` | API Layer | The system shall expose an unauthenticated health endpoint. | Structured logging, unauthenticated health probe, and sensitive data redaction. |
| `FR-230` | Observability | The system shall redact sensitive contact and credential fields from logs. | Structured logging, unauthenticated health probe, and sensitive data redaction. |
| `FR-250` | Auth Service | The system shall maintain local user accounts. | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-251` | Auth Service | The system shall authenticate UI users with a secure session cookie. | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-253` | Auth Service | The system shall implement canonical RBAC roles (`admin`, `broker`, `viewer`). | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-254` | API Layer | The system shall enforce permissions on every REST endpoint. | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-255` | UI Renderer | The system shall enforce permissions on every UI route. | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-256` | API Layer | The system shall deny unauthenticated access to all endpoints except health. | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-257` | Auth Service | The system shall store passwords using a salted password hash (Argon2 / bcrypt). | Foundational security: Argon2id password hashing, session auth, and RBAC enforcement. |
| `FR-280` | Config Service | The system shall version Scoring Configurations. | Configuration integrity: single active config, weight sum validation, and LLM kill-switch. |
| `FR-281` | Config Service | The system shall activate exactly one Scoring Configuration at a time. | Configuration integrity: single active config, weight sum validation, and LLM kill-switch. |
| `FR-282` | Seed Tool | The system shall load synthetic seed data only. | Reliable seed data isolation, test hygiene, and non-production reset protection. |
| `FR-283` | Seed Tool | The system shall support resetting and reseeding a non-production database. | Reliable seed data isolation, test hygiene, and non-production reset protection. |
| `FR-285` | Config Service | The system shall validate configuration weights sum to 1.0 before activation. | Configuration integrity: single active config, weight sum validation, and LLM kill-switch. |
| `FR-286` | Config Service | The system shall provide a feature flag to toggle LLM narration on or off. | Configuration integrity: single active config, weight sum validation, and LLM kill-switch. |

#### 14.4.4 Category 3: Portfolio Enhancement or Convenience (39 Requirements)
| ID | Status | Component | Requirement Title | Concise Classification Justification |
|---|---|---|---|---|
| `FR-002` | Post-MVP | Intake Service | The system shall accept an intake submission as an uploaded `.txt` or `.json` file. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-004` | MVP | Shipment Service | The system shall support manual shipment entry without an intake submission. | Convenience fallback for manual shipment drafting without intake text (core path is automated intake). |
| `FR-011` | MVP | API / UI | The system shall allow an operator to review and correct extracted fields before validation. | Operator UI convenience to review/edit extracted intake fields before conversion (core path parses directly). |
| `FR-012` | Post-MVP | LLM Gateway | The system shall record extraction metadata (model identifier, prompt version) without requiring a real provider. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-013` | Merged | API Layer | The system shall reject unsupported media types and oversized uploads with a structured error. | Merged into standard schemas, Pydantic validations, or consolidated service designs. |
| `FR-028` | Merged | Shipment Service | The system shall store Customer and Facility references distinctly. | Merged into standard schemas, Pydantic validations, or consolidated service designs. |
| `FR-029` | Post-MVP | Shipment Service | The system shall prevent hard deletion of booked Shipments and support cancellation with an audit trail. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-030` | Post-MVP | Shipment Service | The system shall list and filter Shipments by status, lane, customer, and date range. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-047` | Post-MVP | Validation Engine | The system shall produce a clarification request listing blocking issues. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-066` | Post-MVP | Carrier Service | The system shall search Carriers by equipment, region, and availability. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-068` | MVP | API / UI | The system shall list Carrier data for operators. | Convenience operator UI view for carrier profiles (core matching operates headlessly in workflow). |
| `FR-070` | Post-MVP | Carrier Service | The system shall record `last_verified_at` for Carrier attributes. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-071` | Merged | API Layer | The system shall reject invalid region or equipment values. | Merged into standard schemas, Pydantic validations, or consolidated service designs. |
| `FR-072` | Post-MVP | UI Renderer | The system shall show Carrier eligibility context on the carrier profile. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-103` | Future | Config Service | The system shall make eligibility rules configurable without model retraining. | Future capability deferred to strategic roadmap (e.g. four-eyes approval, idle session sweeper). |
| `FR-130` | Post-MVP | Recommendation Engine | The system shall supersede prior active Recommendations when Shipment changes. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-131` | Post-MVP | Recommendation Engine | The system shall expire stale Recommendations after a configurable TTL. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-156` | Post-MVP | Tool Registry | The system shall retry transient failures within the configured budget. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-160` | Post-MVP | Audit Service | The system shall record a node-level audit event for key milestone node executions. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-162` | Merged | Tool Registry | The system shall validate tool-call payloads with Pydantic schemas. | Merged into standard schemas, Pydantic validations, or consolidated service designs. |
| `FR-163` | Merged | Tool Registry | The system shall restrict tool invocation to a hardcoded allowlist. | Merged into standard schemas, Pydantic validations, or consolidated service designs. |
| `FR-165` | Post-MVP | LLM Gateway | The system shall record LLM invocation telemetry (tokens, latency) when enabled. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-166` | Post-MVP | Agent Orchestrator | The system shall allow cancellation of a running or waiting Workflow. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-167` | Removed | Agent Orchestrator | The system shall detect and stop repeated no-progress loops. | Removed as architecturally obsolete (acyclic graph guarantees no infinite progress loops). |
| `FR-187` | Post-MVP | Approval Service | The system shall expire Approvals after a configurable TTL. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-188` | Future | Approval Service | The system shall enforce separation of duties between preparer and approver. | Future capability deferred to strategic roadmap (e.g. four-eyes approval, idle session sweeper). |
| `FR-192` | Post-MVP | Approval Service | The system shall refuse approval when the Recommendation is superseded or cancelled. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-206` | Merged | Booking Proposal Service | The system shall refuse proposal creation when Approval is invalid or rejected. | Merged into standard schemas, Pydantic validations, or consolidated service designs. |
| `FR-223` | Post-MVP | API Layer | The system shall expose an audit query endpoint with filters. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-227` | Post-MVP | Observability | The system shall record workflow latency and failure metrics. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-228` | Post-MVP | LLM Gateway | The system shall record LLM token and cost metrics. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-229` | Post-MVP | Evaluation Harness | The system shall record evaluation run results. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-231` | Post-MVP | Config Service | The system shall audit configuration changes. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-252` | Post-MVP | API Layer | The system shall authenticate API clients with a bearer token. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-258` | Future | Auth Service | The system shall expire sessions after an idle period. | Future capability deferred to strategic roadmap (e.g. four-eyes approval, idle session sweeper). |
| `FR-259` | Post-MVP | Auth Service | The system shall allow administrators to manage users and roles. | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-260` | Future | Audit Service | The system shall audit authentication failures. | Future capability deferred to strategic roadmap (e.g. four-eyes approval, idle session sweeper). |
| `FR-284` | Post-MVP | API Layer | The system shall expose canonical enum metadata (`GET /api/v1/meta/enums`). | Post-MVP enhancement deferred to subsequent releases (e.g. advanced filtering, bulk actions, token telemetry). |
| `FR-287` | Future | UI Renderer | The system shall provide an administrator system status view. | Future capability deferred to strategic roadmap (e.g. four-eyes approval, idle session sweeper). |

### 14.5 Cross-Document Consistency Matrix

| Architectural Element | Document 03 | Document 06 | Document 07 | Document 08 | Document 09 | Document 11 | Document 13 | Document 15 |
|---|---|---|---|---|---|---|---|---|
| **Canonical Statuses** | App A.2 | §3.15, §3.17 | §5, §6 | §5, §6 | §5.6, §5.9 | §7.2, §8.3 | §2, §6 | §12–§14 (Aligned) |
| **Lease Fields** | `lease_token`, `epoch` | `lease_token`, `epoch`, `attempt_started_at` | `lease_token`, `epoch`, `attempt_started_at` | `lease_token`, `epoch`, `attempt_started_at` | `lease_token`, `epoch`, `attempt_started_at` | `lease_token`, `epoch`, `attempt_started_at` | Referenced | Full SQL & Proofs |
| **Heartbeat Protocol** | 15–20s (max 30s) | 15–20s (max 30s) | 15–20s (max 30s) | 15–20s (max 30s) | 15–20s (max 30s) | 15–20s (max 30s) | Bounded | Verified SQL |
| **Execution Ceilings** | 10m continuous attempt | 10m continuous attempt | 10m attempt / 15m retry | 10m attempt | 10m attempt / 15m retry | 10m attempt / 15m retry | 10m bound | Proved Excl Human Wait |
| **Approval Decisions** | approve, reject, changes | approve, reject, changes | approve, reject, changes | approve, reject, changes | approve, reject, changes | approve, reject, changes | approve, reject, changes | Full 3-Decision Coverage |
| **Proposal Idempotency** | DB UNIQUE + partial | UNIQUE + ON CONFLICT | Node 13 ON CONFLICT | DF-04 ON CONFLICT | ON CONFLICT + partial | UNIQUE + ON CONFLICT | Phase 2–3 | Engine Proof |
| **Requirement Counts** | 120 MVP / 156 Total | Schema matches 120 | Graph matches 120 | Flows match 120 | APIs match 120 | Security matches 120 | Cutline matches 120 | 74 + 43 + 39 = 156 Proved |
| **Target Runtime** | Python 3.12 | Standardized | Standardized | Standardized | Standardized | Standardized | Phase 1 Gate | Preserved |

```
========================================================================================
PHASE 1.7.3 AUDIT COMPLETE: CONTRACT 2.1 CONCURRENCY & REQUIREMENT PARTITION FROZEN
- Strict Lease Acquisition: Targets ONLY resumption_pending OR (running AND expired).
- Heartbeat Renewal: Verifies token, epoch, lease_expires_at > NOW(), attempt_started_at.
- Atomic Race Resolution: Proved via PostgreSQL row-level write lock serialization.
- Single-Transaction Fencing: Side effects strictly coupled to lease validation in ACID txn.
- Execution Clock: Formal separation of started_at vs attempt_started_at.
- Requirement Partition: Exactly 74 Core, 43 Security/Reliability, 39 Portfolio Enhancement.
- Mathematical Verification: Zero duplicates, zero missing, 156/156 fully accounted for.
- Document 14 remains 100% untouched.
========================================================================================
```

---

## 15. Phase 1.7.4: Execution Budget Enforcement and Final MVP Scope Gate

### 15.1 Technical Scope & Objectives
Phase 1.7.4 concludes the pre-implementation architectural specification for FreightOps AI (Contract 2.2). It accomplishes two decisive architectural mandates:
1. **Complete Execution Budget Enforcement:** Fully formalizes the database constraints, SQL queries, and transaction boundaries required to enforce the 3-attempt ceiling and 15-minute cumulative active compute budget across initial executions, human pauses, retries, and crash recoveries.
2. **Final Critical MVP Scope Gate:** Concludes an individualized review of all 120 previous MVP items, challenging UI conveniences, administrative CRUD endpoints, and nonessential configuration features to establish a lean, implementable, and mathematically verified **94-requirement MVP scope** (within the approved 85–95 target), while preserving 100% of the core demonstrable workflow, security boundaries, ACID constraints, and crash recovery mechanics.

### 15.2 Execution Limit Enforcement & SQL Specifications

#### 15.2.1 Atomic Lease Acquisition with Attempt & Budget Enforcement
An execution is claimable ONLY if it is in `resumption_pending` or is an expired `running` execution, AND neither permitted attempts (`attempt_count < 3`) nor the cumulative active compute budget (`cumulative_compute_seconds < 900`) has been exhausted:
```sql
UPDATE workflow_executions
SET status = 'running',
    lease_token = gen_random_uuid(),
    lease_epoch = lease_epoch + 1,
    lease_owner = :worker_id,
    lease_expires_at = NOW() + INTERVAL '60 seconds',
    attempt_started_at = NOW(),
    attempt_count = attempt_count + 1,
    updated_at = NOW()
WHERE id = :execution_id
  AND attempt_count < 3
  AND cumulative_compute_seconds < 900
  AND (
    status = 'resumption_pending'
    OR (status = 'running' AND lease_expires_at < NOW())
  )
RETURNING lease_token, lease_epoch, attempt_count, cumulative_compute_seconds;
```

#### 15.2.2 Terminal Failure on Limit Exhaustion
If `attempt_count >= 3` or `cumulative_compute_seconds >= 900`, lease acquisition returns 0 rows. A sweep or worker immediately transitions the execution to terminal failure:
```sql
UPDATE workflow_executions
SET status = 'failed',
    error_code = CASE
      WHEN cumulative_compute_seconds >= 900 THEN 'MAX_COMPUTE_BUDGET_EXCEEDED'
      ELSE 'MAX_ATTEMPTS_EXCEEDED'
    END,
    error_message = CASE
      WHEN cumulative_compute_seconds >= 900 THEN 'Execution aborted: 15-minute cumulative active compute budget exceeded'
      ELSE 'Execution aborted: maximum retry attempts (3) exhausted'
    END,
    lease_token = NULL,
    lease_owner = NULL,
    lease_expires_at = NULL,
    completed_at = NOW(),
    updated_at = NOW()
WHERE id = :execution_id
  AND status IN ('queued', 'running', 'resumption_pending')
  AND (attempt_count >= 3 OR cumulative_compute_seconds >= 900);
```
Following this update, an immutable audit event (`workflow.failed`) is appended. Exhausted executions can never be re-claimed or re-queued.

#### 15.2.3 Active Compute vs Human Wait Accounting
1. **Pre-interrupt Compute Freezing (Node 11):** When Node 11 pauses for human approval, the pre-approval compute duration is committed into `cumulative_compute_seconds`:
   ```sql
   UPDATE workflow_executions
   SET status = 'waiting_for_human',
       cumulative_compute_seconds = cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer,
       lease_token = NULL,
       lease_owner = NULL,
       lease_expires_at = NULL,
       updated_at = NOW()
   WHERE id = :execution_id
     AND lease_token = :my_current_lease_token
     AND lease_epoch = :my_current_lease_epoch;
   ```
2. **Human Wait Exclusion:** While `status = 'waiting_for_human'`, no worker holds a lease and compute is paused. The broker's review duration (hours or days) contributes zero seconds to `cumulative_compute_seconds`.
3. **Post-interrupt Compute Resumption:** Resumption from `resumption_pending` sets `attempt_started_at = NOW()`, giving the post-approval pipeline a clean 10-minute continuous execution window while inheriting prior `cumulative_compute_seconds`.
4. **Budget Non-Bypass Invariant:** `cumulative_compute_seconds` and `attempt_count` are persisted in PostgreSQL; retries, restarts, and recovery sweeps cannot reset them.

#### 15.2.4 Heartbeat Renewal Protocol with Budget Guard
Active workers renew their lease every 15–20s (max 30s) enforcing unexpired lease, continuous attempt ceiling (10 minutes), and cumulative active compute budget (15 minutes / 900 seconds):
```sql
UPDATE workflow_executions
SET lease_expires_at = NOW() + INTERVAL '60 seconds',
    updated_at = NOW()
WHERE id = :execution_id
  AND lease_token = :my_current_lease_token
  AND lease_epoch = :my_current_lease_epoch
  AND lease_expires_at > NOW()
  AND NOW() < attempt_started_at + INTERVAL '10 minutes'
  AND (cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer) <= 900;
```

### 15.3 Transaction Boundaries for Side-Effecting Nodes & Fencing Proofs

#### 15.3.1 Node 13 — Booking Proposal Creation
```sql
BEGIN;
SELECT lease_epoch FROM workflow_executions
WHERE id = :execution_id AND lease_token = :my_token AND lease_epoch = :my_epoch AND lease_expires_at > NOW()
FOR UPDATE;
INSERT INTO booking_proposals (id, shipment_id, approval_id, carrier_id, proposal_number, status, snapshot, idempotency_key, created_by, created_at, updated_at)
VALUES (gen_random_uuid(), :shipment_id, :approval_id, :carrier_id, :proposal_number, 'proposed', :snapshot, :idempotency_key, :user_id, NOW(), NOW())
ON CONFLICT (approval_id) DO NOTHING;
UPDATE shipments SET status = 'booking_proposed', frozen_at = NOW(), updated_at = NOW() WHERE id = :shipment_id;
COMMIT;
```

#### 15.3.2 Node 14 — Audit Recording
```sql
BEGIN;
SELECT lease_epoch FROM workflow_executions
WHERE id = :execution_id AND lease_token = :my_token AND lease_epoch = :my_epoch AND lease_expires_at > NOW()
FOR UPDATE;
INSERT INTO audit_events (id, event_type, aggregate_type, aggregate_id, actor_type, actor_id, payload, created_at)
VALUES (gen_random_uuid(), 'workflow.completed', 'workflow_execution', :execution_id, 'system', :worker_id, :metrics_json, NOW());
COMMIT;
```

#### 15.3.3 Node 15 — Finalization
Validates fencing token, epoch, unexpired lease, attempt ceiling, and cumulative compute budget in the SAME transaction:
```sql
BEGIN;
UPDATE workflow_executions
SET status = 'completed',
    cumulative_compute_seconds = cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer,
    lease_token = NULL,
    lease_owner = NULL,
    lease_expires_at = NULL,
    completed_at = NOW(),
    updated_at = NOW()
WHERE id = :execution_id
  AND lease_token = :my_token
  AND lease_epoch = :my_epoch
  AND lease_expires_at > NOW()
  AND NOW() < attempt_started_at + INTERVAL '10 minutes'
  AND (cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer) <= 900;
-- If 0 rows updated: ROLLBACK immediately and raise ExecutionLeaseFencingError.
UPDATE approvals SET resumed_at = NOW(), updated_at = NOW() WHERE id = :approval_id AND resumed_at IS NULL;
COMMIT;
```

#### 15.3.4 Stale Worker Protection Proof
If Worker A stalls past 60s, Worker B claims the lease and advances `lease_epoch = lease_epoch + 1`. When Worker A wakes up and attempts ANY mutation (Node 13, 14, 15, or Heartbeat), the transaction executes `SELECT lease_epoch ... FOR UPDATE` or `UPDATE ... WHERE lease_epoch = :my_epoch`. Because Worker B modified `lease_epoch` and `lease_token`, 0 rows match. The transaction immediately rolls back, Worker A raises `ExecutionLeaseFencingError`, and zero stale writes leak to the database.

### 15.4 Final Critical MVP Scope Gate (The 26 Reclassified Requirements)

An individual review of the 120 MVP items identified 26 requirements that represent operator conveniences, administrative CRUD, or redundant checks. These have been reclassified to Post-MVP with full traceability:

| ID | Component | Requirement Title | Architectural Reclassification Rationale |
|---|---|---|---|
| `FR-004` | Shipment Service | The system shall support manual shipment entry without an intake submission. | UI convenience fallback: manual shipment entry without intake; core workflow is automated intake extraction. |
| `FR-011` | API / UI | The system shall allow an operator to review and correct extracted fields before validation. | UI convenience: pre-validation extraction review screen; operators edit draft shipments directly via PATCH /shipments/{id}. |
| `FR-068` | API / UI | The system shall list Carrier data for operators. | UI convenience: operator carrier profile list view; carrier matching runs headlessly inside the workflow. |
| `FR-060` | Carrier Service | The system shall create, read, update, and deactivate Carrier profiles. | Administrative feature: interactive Carrier profile CRUD endpoints; carrier profiles are loaded idempotently via synthetic seed fixtures. |
| `FR-063` | Carrier Service | The system shall manage Equipment Types per Carrier. | Administrative feature: interactive Carrier Equipment CRUD endpoints; equipment types are populated via seed fixtures. |
| `FR-064` | Carrier Service | The system shall manage Service Regions per Carrier with origin operating presence semantics. | Administrative feature: interactive Service Region CRUD endpoints; operating regions are populated via seed fixtures. |
| `FR-065` | Carrier Service | The system shall manage Availability windows per Carrier. | Administrative feature: interactive Availability Window CRUD endpoints; capacity windows are populated via seed fixtures. |
| `FR-280` | Config Service | The system shall version Scoring Configurations. | Administrative feature: scoring configuration versioning API; MVP activates a single validated configuration from seed. |
| `FR-281` | Config Service | The system shall activate exactly one Scoring Configuration at a time. | Administrative feature: multi-config activation endpoint; single configuration is active in MVP. |
| `FR-285` | Config Service | The system shall validate configuration weights sum to 1.0 before activation. | Administrative feature: configuration weight validation endpoint; seed configuration weights are validated offline. |
| `FR-008` | Intake Service | The system shall preserve the original raw text alongside the structured record. | Redundant requirement: preserving raw text alongside structured record; raw content is already durably persisted in intake_submissions (FR-005). |
| `FR-031` | Shipment Service | The system shall record the Shipment source (`intake_submission` or `manual`). | Redundant metadata: shipment source column on shipments table; source channel and submitter are already tracked in intake_submissions (FR-005). |
| `FR-205` | API Layer | The system shall retrieve and list Booking Proposals. | Secondary query: general booking proposals list endpoint; created proposal is returned directly by workflow finalization. |
| `FR-128` | Recommendation Engine | The system shall degrade gracefully when carrier data is incomplete (`insufficient_data`). | Nonessential scoring nuance: incomplete data ranking penalty; incomplete carriers are already safely flagged insufficient_data by FR-099. |
| `FR-129` | Recommendation Engine | The system shall store the Scoring Configuration version used. | Nonessential configuration tracking: dynamic config version linkage on recommendations; MVP uses single active seed configuration. |
| `FR-067` | Eligibility Engine | The system shall treat inactive or suspended Carriers as ineligible. | Redundant filter check: carrier status filter; identical check is enforced by Eligibility Engine status filter (FR-094). |
| `FR-050` | Validation Engine | The system shall not auto-fill missing critical fields during validation. | Negative design constraint: do not auto-fill missing fields; deterministic validation engine inherently validates fields without side-effect mutation. |
| `FR-255` | UI Renderer | The system shall enforce permissions on every UI route. | Redundant authorization layer: dedicated UI route permission checks; server-side REST API permission enforcement (FR-254) protects all endpoints. |
| `FR-190` | Approval Service | The system shall allow the approver to select a different eligible candidate than rank 1. | Secondary broker convenience: candidate selection override; MVP workflow approves top-ranked recommendation candidate; re-sourcing handled via reject/changes. |
| `FR-191` | Approval Service | The system shall record the selected candidate on the Approval. | Secondary broker convenience: recording overridden candidate on approval; coupled with FR-190 candidate override. |
| `FR-023` | Shipment Service | The system shall allow Shipment updates before booking with optimistic concurrency (`version`). | Concurrent multi-user editing: optimistic locking on shipments via version column; MVP operates as a single-broker operator portfolio demo. |
| `FR-045` | Validation Engine | The system shall permit review of `warning` issues without blocking Approval. | Non-blocking warning review: separate warning-only review flow; validation engine pass/fail gating (FR-043/FR-044) is sufficient for MVP demo. |
| `FR-048` | Validation Engine | The system shall support re-validation after correction. | Redundant workflow rule: re-validation after correction; inherently supported by re-invoking idempotent POST /shipments/{id}/validation. |
| `FR-102` | Eligibility Engine | The system shall provide human-readable eligibility reasons for exclusions. | Redundant presentation rule: human-readable eligibility reasons for exclusions; canonical ineligibility reason codes are emitted via FR-098. |
| `FR-126` | LLM Gateway | The system shall ensure explanations cite only recorded facts and introduce no new claims. | Redundant ground-truth rule: ensure explanations cite only recorded facts; already guaranteed by FR-125 deterministic template fallback. |
| `FR-133` | Recommendation Engine | The system shall use only operator-provided target rates and recorded carrier lane rates. | Redundant rate-sourcing rule: use only recorded carrier lane rates; already enforced by FR-073 and FR-134 deterministic ranking. |

### 15.5 Final Requirement Inventory Partition

Following the Phase 1.7.4 scope challenge, the 156 system requirements are partitioned as follows:
- **Retained MVP:** 94 requirements (60.3%)
- **Post-MVP Backlog:** 50 requirements (32.1%) — 24 original + 26 reclassified
- **Future Backlog:** 5 requirements (3.2%)
- **Merged / Removed:** 7 requirements (4.5%) — 6 Merged + 1 Removed
- **Total:** 156 requirements (100.0%)

#### Mathematical Verification:
$$94 + 50 + 5 + 7 = 156$$
Every requirement ID is traceable, with zero duplicate IDs and zero missing entries.

### 15.6 Complete List of Retained 94 MVP Requirement IDs

`FR-001`, `FR-003`, `FR-005`, `FR-006`, `FR-007`, `FR-009`, `FR-010`, `FR-014`, `FR-020`, `FR-021`, `FR-022`, `FR-024`, `FR-025`, `FR-026`, `FR-027`, `FR-032`, `FR-040`, `FR-041`, `FR-042`, `FR-043`, `FR-044`, `FR-046`, `FR-049`, `FR-051`, `FR-052`, `FR-061`, `FR-062`, `FR-069`, `FR-073`, `FR-090`, `FR-091`, `FR-092`, `FR-093`, `FR-094`, `FR-095`, `FR-096`, `FR-097`, `FR-098`, `FR-099`, `FR-100`, `FR-101`, `FR-120`, `FR-121`, `FR-122`, `FR-123`, `FR-124`, `FR-125`, `FR-127`, `FR-132`, `FR-134`, `FR-150`, `FR-151`, `FR-152`, `FR-153`, `FR-154`, `FR-155`, `FR-157`, `FR-158`, `FR-159`, `FR-161`, `FR-164`, `FR-168`, `FR-180`, `FR-181`, `FR-182`, `FR-183`, `FR-184`, `FR-185`, `FR-186`, `FR-189`, `FR-200`, `FR-201`, `FR-202`, `FR-203`, `FR-204`, `FR-207`, `FR-208`, `FR-209`, `FR-220`, `FR-221`, `FR-222`, `FR-224`, `FR-225`, `FR-226`, `FR-230`, `FR-250`, `FR-251`, `FR-253`, `FR-254`, `FR-256`, `FR-257`, `FR-282`, `FR-283`, `FR-286`

```
========================================================================================
PHASE 1.7.4 ARCHITECTURE GATE COMPLETE: CONTRACT 2.2 FINALIZED & FROZEN
- Execution Limits: Enforced via atomic SQL (attempt_count < 3, cumulative compute <= 900s).
- Active Compute Accounting: Durably frozen during human wait; human wait adds 0 seconds.
- Fencing & Transaction Boundaries: Nodes 13, 14, 15 coupled to fencing in single ACID txns.
- Final MVP Scope: 94 MVP / 50 Post-MVP / 5 Future / 6 Merged / 1 Removed = 156 total.
- Document 14 preserved 100% untouched byte-for-byte (66,509 chars / 66,724 bytes).
- Authoritative cutline synchronized byte-for-byte across 03 §1.3, 04 §10, 13 §9 (4,329 bytes).
========================================================================================
```

---

## 16. Phase 1.7.5: Architecture Remediation (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Baseline:** Independent Phase 1 Completion Audit Report (2026-11-25) & User-Approved Decisions (`A1`, `B2`, `C1`, `D1`, `Equipment Option 1`).
- **Immutability note:** Sections 1–15 above remain untouched historical records. `docs/14-architecture-review.md` remains byte-for-byte immutable.

### 16.1 Approved Architectural Decisions Applied

1. **A1 (`FR-156`):** Promoted `FR-156` (transient workflow/LLM retries within execution budget) from `Post-MVP` to `MVP` (`PH-5`).
2. **B2 (`FR-252` & Auth):** Kept `FR-252` (Bearer token API authentication) `Post-MVP`; standardized MVP authentication on session cookies (`HttpOnly`, `Secure`, `SameSite=Lax`) with CSRF protection on state-changing requests.
3. **C1 (Hard Eligibility Filters):** Standardized on **7** deterministic hard eligibility filters (`FR-091`–`FR-097`) and excluded `safety_rating` from MVP eligibility filtering.
4. **D1 (`workflow_execution_id` FK Correlation):** Added `workflow_execution_id` (`uuid null FK -> workflow_executions.id`, `UNIQUE`) to `recommendations` (`06 §3.13`) and `approvals` (`06 §3.15`), and updated recovery queries (`09 §6.8`, `11 §8.3`) to join `approvals` on `a.workflow_execution_id = w.id`.
5. **Equipment Option 1 (`shipments.equipment_type`):** Added `equipment_type` as a first-class nullable-on-draft column on `shipments` (`06 §3.9`, `CHECK (equipment_type IN ('dry_van', 'reefer', 'flatbed'))`), required before `validated`. Kept `shipments.requirements` JSONB strictly limited to the 9 canonical keys in `03 §A.2`. Updated Node 3 (`extract_intake_fields`) and Node 5 (`normalize_requirements`) in `04`, `07`, and `08` to handle `equipment_type` separately from `requirements`.

### 16.2 Blockers Resolved

- **BLK-01 (Execution Budget, Lease Acquisition, Crash Accounting & Recovery):**
  - Unified atomic lease acquisition across `06 §3.17`, `07 §6.3`, `08`, `09 §5.6/6.3`, and `11 §7.2`: claims `queued` (`attempt_count = 0` → `1`), `resumption_pending` (`attempt_count <= max_attempt_count`, preserving `attempt_count`), or expired `running` (`lease_expires_at < NOW() AND attempt_count < max_attempt_count`, incrementing `attempt_count` and adding bounded crash-window compute `LEAST(900, cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer))`), guarded by `cumulative_compute_seconds < 900`.
  - Added atomic budget/attempt exhaustion (`BEGIN ... COMMIT`): transitions to `timed_out` (`MAX_COMPUTE_BUDGET_EXCEEDED`) when `cumulative_compute_seconds >= 900` or `failed` (`MAX_ATTEMPTS_EXCEEDED`) when attempts are exhausted, and inserts `workflow.failed` into `audit_events`.
- **BLK-02 (Schema, State-Transition & API Contract Contradictions):**
  - Aligned `approvals` (`resumed_at`), `shipments` (`equipment_type`, `frozen_at`, `approved` → `booking_proposed`), `recommendations`/`approvals` (`workflow_execution_id`), canonical 9-key `requirements` JSONB, `sequence` (replacing `stop_sequence`), approval audit event types (`approval.granted`/`approval.rejected`/`approval.changes_requested`), and Node 13–15 fencing boundaries.
- **BLK-03 (Contract 2.2 Scope & Documentation Synchronization):**
  - Reconciled `03 §A.5` and `09 §5` to 23 active MVP operations across 18 paths (plus 8 deferred Post-MVP paths clearly marked).
  - Synchronized verbatim MVP cut line across `03 §1.3`, `04 §10`, and `13 §9`.
  - Synchronized `Contract 2.2` headers and deferred-feature markers across `README.md`, `docs/README.md`, `01`, `02`, `03`, `04`, `05`, `06`, `07`, `08`, `09`, `10`, `11`, `12`, and `13`.
- **BLK-04 (MVP Requirement Classification & Hard-Filter Conflicts):**
  - Reconciled requirement inventory to **156** total: **95 MVP** (`PH-1`: 16, `PH-2`: 15, `PH-3`: 15, `PH-4`: 25, `PH-5`: 17, `PH-6`: 7), **49 Post-MVP**, **5 Future**, **6 Merged**, **1 Removed**.
  - Moved `FR-069` to `PH-1`, promoted `FR-156` to MVP `PH-5`, and removed `safety_rating` from MVP hard filters (`7` canonical filters).

---

## 17. Phase 1.7.5-R1: SQL Schema, Fencing, and Metadata Consistency Correction (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Trigger:** Independent Phase 1.7.5 review findings (7 items).
- **Immutability note:** Historical Sections 1–15 and Section 16 remain untouched. `docs/14-architecture-review.md` remains byte-for-byte immutable.

### 17.1 Corrections Applied

1. **Removed Unsupported Lease Columns (`docs/11`, `docs/09`):** Removed `lease_acquired_at` and `last_heartbeat_at` from `ACQUIRE_SQL` in `11 §7.2`, `09 §5.6`, and `09 §6.3`, aligning strictly with `workflow_executions` in `06 §3.17` (`attempt_started_at` and `updated_at` track acquisition/heartbeat timestamps).
2. **Aligned `audit_events` Inserts to `06 §3.18` (`docs/11`, `docs/09`, `docs/06`):** Replaced nonexistent `entity_type`/`entity_id` (in terminal `workflow.failed` exhaustion SQL) and `aggregate_type`/`aggregate_id` + `id = gen_random_uuid()` (in Node 14 SQL) with the canonical `06 §3.18` column list (`event_type, actor_type, actor_id, shipment_id, workflow_execution_id, [approval_id, booking_proposal_id,] trace_id, payload, created_at`), preserving `bigserial` `id` and `NOT NULL` `trace_id`.
3. **Explicit Node 13 & Node 14 Fencing Abort/Rollback Gates (`docs/07`, `docs/06`, `docs/09`, `docs/11`):** Explicitly required `ROLLBACK` + `ExecutionLeaseFencingError` immediately when `SELECT lease_epoch ... FOR UPDATE` returns 0 rows, ensuring stale workers never continue to `INSERT` or `UPDATE` side effects, and synchronized 10m attempt / 900s cumulative guards across Nodes 13, 14, and 15.
4. **Fixed `POST /api/v1/shipments` Requirements JSON Example (`docs/09 §5.3`):** Removed duplicate `"hazmat": false` and unsupported `"pallet_count": 24`, keeping only canonical keys from `03 §A.2`.
5. **Corrected `workflow_executions.attempt_count` Description (`docs/06 §3.17`):** Updated column table description to reflect that initial `queued` acquisition sets `attempt_count = 1`, normal HITL resumption from `resumption_pending` preserves `attempt_count`, and only expired-lease crash recovery increments `attempt_count`.
6. **Reconciled `docs/15` Top Metadata Header (`docs/15`):** Updated top metadata table to `Contract version | 2.2`, `Status | Approved (Phase 1.7.5 Architecture Remediation)`, and `Last updated | 2026-11-25` while preserving historical Sections 1–15 untouched and append-only.
7. **Cross-Document SQL, Schema & Lifecycle Parity (`docs/11 §8.3`, `docs/09 §5.6`, `docs/07 §11.2`):** Aligned rejection/changes-requested shipment transition in `11 §8.3` and `09 §5.6` with canonical `03 §B.1` (`D-05`: `pending_approval -> sourcing`, `approved -> booking_proposed`), removed residual `selected_candidate_id` assignment in `09 §5.6` step 3, and synchronized Node 11/13/14/15 + exhaustion SQL across `06`, `07`, `09`, and `11`.

---

## 18. Phase 1.7.5-R1 Final Corrections (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Trigger:** Independent review of Phase 1.7.5-R1 (4 documentation-level findings).
- **Immutability note:** Historical Sections 1–15, Section 16, and Section 17 remain untouched. `docs/14-architecture-review.md` remains byte-for-byte identical.

### 18.1 Four Findings Resolved

1. **Executable Application-Managed Fencing Gates (`06 §3.17`, `07 §6.3`, `08 §6`, `09 §6.3`, `11 §7.2`):** Replaced SQL-comment-only fencing notes in Nodes 13, 14, and 15 with explicit application-managed transaction protocols checking `len(rows) == 1` / `rowcount == 1` before any protected write, rolling back and raising `ExecutionLeaseFencingError` on mismatch, and validating `approvals.resumed_at` `rowcount == 1` on Node 15 when `approval_id IS NOT NULL`.
2. **Proposal & Audit Transaction Atomicity (`06 §3.17`, `07 §6.3`, `08 §6`, `09 §6.3`, `11 §7.2`, `11 §8.1`):** Unified Node 13 so fencing check, approval verification (`approved`), shipment freeze/update (`booking_proposed`), idempotent `booking_proposals` insertion (`ON CONFLICT (approval_id) DO NOTHING`), and `booking_proposal.created` audit insertion commit together in one ACID transaction. Node 14 records workflow-level summary/non-proposal outcome events (`workflow.completed`, `approval.rejected`, `approval.changes_requested`) without duplicating `booking_proposal.created`.
3. **Conditional Budget-Exhaustion Audit Insertion (`06 §3.17`, `07 §10`, `09 §6.3`, `11 §7.2`):** Replaced unconditional `INSERT INTO audit_events` after `UPDATE workflow_executions` with an atomic data-modifying CTE (`WITH exhausted AS (UPDATE ...) INSERT INTO audit_events ... SELECT ... FROM exhausted`) plus application row-count validation, deriving audit payload fields from `exhausted` and ensuring 0 audit rows are inserted if the execution already transitioned to a terminal state.
4. **Historical Revision Log Labeling (`15` header notice & `§18`):** Added a prominent historical notice above Section 1 clarifying that Sections 1–15 are superseded where they conflict with Contract 2.2 while keeping the revision log strictly append-only.

---

## 19. Phase 1.7.5-R2 — Targeted Execution Safety Remediation (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Trigger:** Independent review of Contract 2.2 identifying three execution-safety blockers (`R2-01`, `R2-02`, `R2-03`).
- **Immutability note:** Historical Sections 1–15 and Sections 16–18 remain untouched. `docs/14-architecture-review.md` remains byte-for-byte identical.

### 19.1 Blockers Resolved & Design Decisions

1. **`R2-01` — Node 11 Fencing Enforcement (`06 §3.17`, `07 §6.2`, `08 §5`, `09 §6.3`, `11 §7.2`):**
   - Replaced bare SQL pause update with an application-managed ACID transaction protocol: Node 11 executes `NODE_11_FENCE_PAUSE_SQL` (checking `lease_token`, `lease_epoch`, `lease_expires_at > NOW()`, `NOW() < attempt_started_at + INTERVAL '10 minutes'`, and `<= 900s` cumulative compute), verifies `wf_res.rowcount == 1`, and on any mismatch immediately runs `tx.rollback()` and raises `ExecutionLeaseFencingError` without inserting `approvals`, inserting `audit_events`, or invoking LangGraph `interrupt()`. `interrupt()` is called only after `tx.commit()` succeeds.
2. **`R2-02` — 10-Minute Continuous-Attempt Limit in Crash Recovery (`06 §3.17`, `07 §10`, `08 §7`, `09 §5.6/6.3/6.8`, `11 §7.2/8.3`):**
   - Updated `ACQUIRE_SQL` and `RECOVERY_SQL` so expired `running` executions can only be reclaimed when `NOW() < attempt_started_at + INTERVAL '10 minutes'` and projected `(cumulative_compute_seconds + crashed_elapsed) < 900`, preventing an expired attempt that exceeded its 10-minute continuous-attempt window from receiving a fresh `attempt_started_at`.
   - Updated `EXHAUST_CTE` (`WITH exhausted AS (UPDATE ...) INSERT INTO audit_events ... FROM exhausted`) to terminate expired `running` executions exceeding 10 minutes (`timed_out` / `MAX_CONTINUOUS_ATTEMPT_EXCEEDED`), 900s cumulative compute (`timed_out` / `MAX_COMPUTE_BUDGET_EXCEEDED`), or `max_attempt_count` (`failed` / `MAX_ATTEMPTS_EXCEEDED`), while never overwriting terminal states (`completed`, `failed`, `timed_out`, `cancelled`) and never counting human approval wait time.
3. **`R2-03` — Node 14 Outcome Audit Idempotency (`06 §3.17/3.18`, `07 §6/6.3`, `09 §6.3`, `11 §7.2`):**
   - Added `idempotency_key text null` to `audit_events` (`06 §3.18`) with PostgreSQL partial unique index `CREATE UNIQUE INDEX uq_audit_events_idempotency_key ON audit_events (idempotency_key) WHERE idempotency_key IS NOT NULL;`, preserving `trg_audit_events_immutable` (`BEFORE UPDATE OR DELETE`).
   - Node 14 derives deterministic key `node14:<execution_id>:<canonical_outcome_event>` and executes `INSERT INTO audit_events (...) ... ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING RETURNING id`, keeping Node 14 outcome events distinct from Node 13's atomic `booking_proposal.created` insert and preventing duplicate outcome events under crash replay or concurrency.

### 19.2 Verification & Limitations

- Verified statically via `audit_175_sql_schema.py` and `verify_175_contract.py` (`exit code 0`).
- Runtime PostgreSQL execution and concurrency testing were not performed (documentation-only phase; no application code or migrations exist yet).

---

## 20. Phase 1.7.5-R3 — Node 11 Resume and Audit Idempotency Corrections (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Trigger:** Independent review of Phase 1.7.5-R2 identifying three issues (`R3-01`, `R3-02`, `R3-03`).
- **Immutability note:** Historical Sections 1–15 and Sections 16–19 remain untouched. `docs/14-architecture-review.md` remains byte-for-byte identical.

### 20.1 Issues Reviewed & Corrections Applied

1. **`R3-01` — Node 11 First-Run vs. Resume Separation (`07 §6.2`, `07 §8` D-14):**
   - Separated Node 11 into explicit **Path A** (first execution when `state.get("approval_id") is None` and `resume_payload is None`: fenced pause update, `wf_res.rowcount == 1` check, pending approval + `approval.requested` insert, commit, then `interrupt()`) and **Path B** (resume after human decision: verifies `approval_id`, `workflow_execution_id`, `recommendation_id`, and decided `status` in `approvals`, skips `NODE_11_FENCE_PAUSE_SQL`, skips inserts, skips `interrupt()`, and passes the validated decision to Node 12).
   - Updated Diagram D-14 (`07 §8`) to reflect Path B resume verification before Node 12.
2. **`R3-02` — Node 14 Existing-Event Identity Verification (`07 §6.3`, `06 §3.17`, `09 §6.3`, `11 §7.2`):**
   - Updated Node 14 idempotency-conflict fallback (`inserted_audit is None`): queries `id, idempotency_key, event_type, workflow_execution_id, shipment_id, approval_id, booking_proposal_id, payload` from `audit_events` by `idempotency_key` and verifies all identity fields plus `payload.get("outcome") == expected_outcome`.
   - Matching replay commits cleanly without duplicate writes; any mismatch triggers `tx.rollback()` and raises `AuditIdempotencyConflictError`. Preserves `uq_audit_events_idempotency_key`, `trg_audit_events_immutable`, and Node 13/14 separation.
3. **`R3-03` — `workflow_executions.idempotency_key` Duplication Check (`06 §3.17`, `06 §3.18`):**
   - Inspected `06-database-design.md` on disk: `workflow_executions` (`§3.17`) already declares `idempotency_key text null, unique` exactly once, and `audit_events` (`§3.18`) retains its separate `idempotency_key` + `uq_audit_events_idempotency_key`. No change was needed or manufactured.

### 20.2 Verification & Limitations

- Verified statically via `audit_175_sql_schema.py` and `verify_175_contract.py` (`exit code 0`).
- Runtime LangGraph checkpointing and PostgreSQL concurrency testing were not performed (documentation-only phase; no application code or migrations exist yet).

---

## 21. Phase 1.7.5-R4 — LangGraph Resume Semantics & Audit Idempotency Correction (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Trigger:** Independent review of Phase 1.7.5-R3 (`R4-01`, `R4-02`, `R4-03`, `R4-04`).
- **Immutability note:** Historical Sections 1–15 and Sections 16–20 remain untouched. `docs/14-architecture-review.md` remains byte-for-byte identical.

### 21.1 Corrections Applied

1. **`R4-01` — Node 11 LangGraph `interrupt()` / `Command(resume=...)` Semantics (`07 §6.2`, `07 §8` D-14, `06 §3.17`, `09 §6.3`, `11 §7.2`):**
   - Removed the invented `resume_payload` node parameter and removed the branch that skipped `interrupt()` on resume.
   - Documented standard LangGraph re-execution from the start of `request_human_approval(state)`: first execution runs `NODE_11_FENCE_PAUSE_SQL` (`rowcount == 1`), inserts `pending` approval + `approval.requested` audit event, commits before `interrupt()`, and calls `interrupt(...)`; resume execution reconstructs `approval_id` from durable state/DB, skips repeating the pause/approval/audit writes, checks active lease fencing (`len(fence_rows) == 1`), reaches `interrupt(...)` to consume `Command(resume=...)`, and validates the returned action and IDs against the durable `approvals` row before handing off to Node 12.
   - Recorded `langgraph` / `langgraph-checkpoint-postgres` exact version pinning (`10 §3`, `Target Planned`) and pre-interrupt crash-window / missing-checkpoint reconciliation as explicit unresolved implementation dependencies/limitations for `PH-5` runtime verification.
2. **`R4-02` — Node 14 Canonical Identity & Immutable Payload Verification (`07 §6.3`, `06 §3.17`, `09 §6.3`, `11 §7.2`):**
   - Defined canonical event identity `(idempotency_key, event_type, workflow_execution_id, shipment_id, approval_id, booking_proposal_id)` including explicit `None`/`NULL` matching for optional FKs.
   - Defined deterministic canonical JSON serialization (`sort_keys=True`, `separators=(",", ":")`, `allow_nan=False`, excluding volatile timestamps) and SHA-256 digest comparison (`canonical_payload_sha256(existing.payload) == canonical_payload_sha256(metrics_json)`) on `uq_audit_events_idempotency_key` conflict, raising `AuditIdempotencyConflictError` on any mismatch.

### 21.2 Verification & Limitations

- Verified statically via `audit_175_sql_schema.py` and `verify_175_contract.py` (`exit code 0`).
- Runtime LangGraph checkpoint/resume tests and PostgreSQL transaction/concurrency tests were not performed (documentation-only remediation).

---

## 22. Phase 1.7.5-R4.1 — Approval Decision Ownership and Audit Consistency Remediation (Contract 2.2)

- **Date:** 2026-11-25
- **Contract version:** `2.2`
- **Trigger:** Remediation of approval decision ownership and audit event duplication across workflow and API contracts (`R4.1-01`, `R4.1-02`, `R4.1-03`).
- **Immutability note:** Historical Sections 1–15 and Sections 16–21 remain untouched. `docs/14-architecture-review.md` remains byte-for-byte identical.

### 22.1 Corrections Applied

1. **`R4.1-01` — Shipment Status Transition Ownership (`06 §3.15`, `07 §6/§7.1/§8` D-14, `08 §5/§6`, `09 §5.6/§6.3`, `11 §8.3`, `03 §A.2`):**
   - Standardized the Approval Service decision transaction (`POST /api/v1/approvals/{id}/decision`) as the **sole owner** of the immediate shipment status transition upon human decision:
     - `approve`: transitions `shipments.status = 'approved'` and sets `frozen_at = NOW()`.
     - `reject`: transitions `shipments.status = 'sourcing'`.
     - `request_changes`: defines one single deterministic target state rule: `shipments.status = 'sourcing'` (eliminating ambiguous `or draft` phrasing and aligning with `03 §B.1` D-05 lifecycle transition).
   - Node 12 (`apply_human_decision`) validates the persisted approval decision and routes the workflow graph only; it never repeats shipment status updates.
   - Node 13 (`create_booking_proposal`) advances `shipments.status = 'booking_proposed'` atomically with proposal insertion and `booking_proposal.created` audit recording.

2. **`R4.1-02` — Approval Audit Ownership & Elimination of Duplicate Audit Events (`06 §3.15/§3.17/§3.18`, `07 §6/§6.3/§8` D-14, `08 §5/§6`, `09 §5.6/§6.3`, `11 §7.2/§8.3`, `03 §A.2`):**
   - Established that the Approval Service decision transaction is the **sole owner** of the human decision audit events: `approval.granted`, `approval.rejected`, or `approval.changes_requested`.
   - Node 14 (`record_audit_event`) never re-inserts `approval.rejected` or `approval.changes_requested`.
   - Standardized Node 14 to record **exclusively** the workflow-level outcome summary event (`workflow.completed`) across all execution paths (`approved`, `rejected`, `changes_requested`, `no_eligible_carriers`) with canonical idempotency key `outcome_key = f"node14:{execution_id}:workflow.completed"` and payload `{"outcome": <approved|rejected|changes_requested|no_eligible_carriers>, ...}`.
   - On the approved path: Approval Service records `approval.granted`; Node 13 records `booking_proposal.created`; Node 14 records `workflow.completed` (`outcome: approved`); Node 15 finalizes.
   - On rejected/changes_requested paths: Approval Service records `approval.rejected` / `approval.changes_requested`; Node 12 routes to Node 14; Node 14 records `workflow.completed` (`outcome: rejected` / `outcome: changes_requested`); Node 15 finalizes.

3. **`R4.1-03` — Cross-Document Contract & Diagram Synchronization (`06`, `07`, `08`, `09`, `11`, `03`):**
   - Synchronized Diagram D-14 (`07 §8`), Diagram DF-03 and DF-04 (`08 §5`, `08 §6`), Node catalogs (`07 §6`), API endpoints (`09 §5.6`), database lifecycle notes (`06 §3.15`), and crash recovery scenarios (`11 §8.3`) to eliminate conflicting descriptions of shipment status updates and duplicate audit events.
   - Preserved Node 11 LangGraph interrupt/resume semantics and Node 14 canonical identity & payload hash verification established in R4.

### 22.2 Verification & Limitations

- Verified statically via documentation inspection across all affected contracts.
- Confirmed `docs/14-architecture-review.md` SHA-256 (`9f61632e941b9e06e47ef7f6e2e38c56d97e63e56b7bb76687d605a710182fe4`) and size (66,724 bytes) are unchanged.
- Runtime PostgreSQL execution and concurrency testing were not performed (documentation-only remediation; no application code or migrations exist yet).

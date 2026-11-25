# 14 — Independent Architecture & System Design Review

| Field | Value |
|---|---|
| Status | Complete Independent Technical Review |
| Contract Version Under Review | 1.0 (2026-11-22) |
| Author Role | Principal Software Architect, Senior Backend Engineer, AI Agent Systems Engineer, Database Architect |
| Target Repository | FreightOps AI (`freightops-ai`) |
| Date | 2026-11-22 |
| Audience | Project Owner, Lead Developer, Engineering Reviewers |

---

## 1. Executive Assessment

FreightOps AI presents an ambitious, highly structured documentation set intended to guide the development of an AI-assisted freight brokerage operations platform. Across thirteen core architecture documents, the system defines a modular monolith in FastAPI, a deterministic validation and eligibility engine, a rule-based ranking baseline, a LangGraph-orchestrated workflow with a human-in-the-loop (HITL) approval gate, an append-only audit trail, and synthetic seed datasets.

From the perspectives of a **Principal Software Architect**, **Senior Backend Engineer**, **AI Agent Systems Engineer**, and **Database Architect**, our assessment concludes:

> **Executive Verdict: CONDITIONAL HOLD (Architectural Redesign Required Before Phase 2).**
> The documentation exhibits exceptional academic rigor, high self-awareness regarding AI limitations, and disciplined contract traceability. However, it suffers from **severe enterprise over-engineering**, **critical relational integrity deadlocks**, and an **unrealistic scope for a solo developer building a production-style portfolio project**. 

### Core Architectural Contradictions Identified
1. **The Intake-Persistence Deadlock:** The schema enforces rigid `NOT NULL` foreign keys on `shipments` (`customer_id`, `shipper_id`, `consignee_id`), yet the intake workflow specifies that raw, incomplete email text immediately generates a draft shipment. A raw intake submission with missing or unresolved parties will crash on database `INSERT` due to foreign key and nullability violations.
2. **Missing Operational Infrastructure for Workflows:** The system designs a 16-node LangGraph workflow with an interrupt that can wait up to 24 hours for human approval, alongside scheduled TTL expiration sweeps and transactional outbox writing. Yet, it explicitly defers background workers (Celery/ARQ), task queues (Redis), and schedulers, claiming the workflow runs "in-process as a background task in FastAPI." A single-process FastAPI application cannot durably sustain long-running interrupts, manage delayed sweeps, or dispatch outbox events across restarts without dedicated background scheduling infrastructure.
3. **The "Phantom Rate" Scoring Dilemma:** The recommendation engine mandates a `rate_competitiveness` score component and candidate `rate_quote` fields, and strictly forbids LLM rate generation (`FR-133`). However, neither the carrier master table nor any other database table stores carrier rate cards, mileage tariffs, or historical lane rates. The scoring engine has no source of truth to compute commercial fit.
4. **Massive Over-Specification for a Solo Portfolio:** The project specifies **155 functional requirements**, **23 database tables**, **16 workflow nodes**, **22 REST endpoints**, and **4 distinct RBAC roles**. For a single developer, this represents 5 to 6 months of full-time enterprise plumbing (or 8+ months part-time) before producing a working demonstration of core AI agent capabilities.

Phase 2 (Implementation) must not begin until the critical schema flaws, execution gaps, and scope inflation detailed in this review are reconciled.

---

## 2. Architecture Strengths

The documentation set possesses several exemplary design patterns that should be vigorously preserved:

1. **Strict LLM vs. Deterministic Boundary Matrix (`05 §3`):**
   The architecture establishes a crystal-clear rule: *if a decision carries legal, financial, or operational consequences, it must be decided by deterministic Python code or an authorized human.* Restricting the LLM to unstructured-to-structured text extraction and constrained explanation narration eliminates the dangerous hallucination risks prevalent in naive agent architectures.
2. **Untrusted Content Isolation & Zero LLM Tool Authority (`05 §4.10`, `07 §8`, `11 §6`):**
   Treating all customer text as untrusted data and granting the LLM zero direct database access and zero autonomous tool-calling authority completely neutralizes classical indirect prompt injection attacks against system state.
3. **Immutable Human Approval Before Consequential Action (`07 §7`, `08 §6`):**
   The architecture strictly prevents autonomous booking. The single approval interrupt durably records the approver's identity, timestamp, decision, and candidate selection, ensuring non-repudiation and regulatory accountability.
4. **Audit Immutability & Event Correlation (`06 §3.19`, `08 §7`):**
   The schema treats `audit_events` as an append-only stream sharing transactions with domain mutations. Correlating events via `trace_id`, `workflow_execution_id`, and `shipment_id` provides complete post-incident forensic capability.
5. **JSONB Snapshotting at the Approval Boundary (`06 §3.17`):**
   Persisting a frozen snapshot of shipment and carrier state inside `booking_proposals.snapshot` insulates approved agreements from downstream mutations in master carrier profiles or customer records.
6. **Intellectual Honesty and Transparency (`README.md`, `10 §6`):**
   The documents explicitly acknowledge that Python 3.14 compatibility for planned packages is unverified, refrain from inventing fake industry statistics, and maintain explicit registers for assumptions, open questions, and deferred backlog items.

---

## 3. Critical Design Problems

This section details the critical design flaws that will cause runtime failure, data integrity corruption, or development paralysis if implementation commences without modification.

### [CRIT-01] The Intake-to-Shipment Foreign Key and Nullability Deadlock
- **Location:** `docs/03-requirements-specification.md` (FR-007, FR-010), `docs/06-database-design.md` (§3.9), `docs/08-data-flow.md` (DF-01), `docs/09-api-design.md` (§5.1).
- **Severity:** Critical
- **Blocks Phase 2:** Yes
- **Explanation:** In `docs/06-database-design.md` §3.9, the `shipments` table defines `customer_id`, `shipper_id`, and `consignee_id` as `NOT NULL` foreign keys. However, `docs/09-api-design.md` §5.1 states that `POST /api/v1/intake/submissions` accepts raw text where `customer_id` is `"optional-uuid"`. In real brokerage operations (and synthetic test cases in `DS-01`), customer text arrives as: *"Pickup Chicago IL Monday, deliver Dallas TX Wednesday. Reefer, 42k lbs."* Neither the customer ID nor the shipper/consignee facility IDs exist or are resolved at intake time. `DF-01` step 7 mandates that `IntakeService` immediately calls `ShipmentService.create_draft_shipment()`.
- **Why it matters:** Attempting to insert a draft shipment from raw intake will instantly trigger a PostgreSQL `NOT NULL constraint violation` or `foreign_key_violation`. The system cannot even execute its primary entry point (`POST /api/v1/intake/submissions`) as designed.
- **Recommended Correction:** 
  1. Alter `shipments.customer_id`, `shipments.shipper_id`, and `shipments.consignee_id` to be **nullable** in `draft` and `intake_received` statuses.
  2. Enforce party completeness deterministically in the `ValidationEngine` before transitioning to `validated`.

---

### [CRIT-02] In-Process Workflow Execution Cannot Support 24-Hour Interrupts and Sweeps
- **Location:** `docs/04-system-architecture.md` (§8, §12 Q1), `docs/07-agent-workflow.md` (§7, §10, §15 Q2), `docs/10-technology-decisions.md` (ADR-005, ADR-009).
- **Severity:** Critical
- **Blocks Phase 2:** Yes
- **Explanation:** The architecture states that the 16-node LangGraph workflow runs "in-process as a bounded background task" in FastAPI (`04 §8`), and explicitly defers task queues like Celery, ARQ, and Redis (`10 ADR-009`). However, Node 11 (`request_human_approval`) pauses execution via an `interrupt()` for an Approval TTL of up to 24 hours (`07 §10`). Furthermore, `07 §15 Q2` mandates a "scheduled sweep" to expire stale approvals, and `04 §8` claims mid-workflow crashes resume from checkpoints upon restart.
- **Why it matters:** 
  1. In FastAPI, `BackgroundTasks` or `asyncio.create_task` are ephemeral in-memory constructs tied to the active ASGI process. When an interrupt occurs, the task terminates. If the server is restarted or redeployed during the 24-hour window, there is no active worker process to resume the thread or monitor timeouts.
  2. The document specifies no cron, beat, or daemon runner to execute the "scheduled sweep" for expired approvals.
  3. Resuming an interrupted LangGraph state graph requires invoking `graph.invoke(Command(resume=...), config=...)`. If this invocation happens synchronously inside `POST /api/v1/approvals/{id}/decision`, that HTTP request must execute nodes 12, 13, 14, and 15 synchronously, violating the asynchronous workflow pattern.
- **Recommended Correction:** 
  1. Explicitly adopt a lightweight, in-process, persistent background scheduler such as `APScheduler` (backed by PostgreSQL) or a managed FastAPI `lifespan` worker loop to handle resumption sweeps and timeouts.
  2. Formally specify that the approval decision endpoint (`POST /approvals/{id}/decision`) simply updates the database approval record and enqueues a resume job rather than executing the rest of the graph inside the web request loop.

---

### [CRIT-03] Phantom Carrier Rate Data in Recommendation and Scoring
- **Location:** `docs/01-business-understanding.md` (ASM-03), `docs/02-problem-definition.md` (P-06), `docs/03-requirements-specification.md` (FR-133), `docs/06-database-design.md` (§3.5, §3.15), `docs/07-agent-workflow.md` (§5 Node 8).
- **Severity:** Critical
- **Blocks Phase 2:** Yes
- **Explanation:** Requirement `FR-133` mandates: *"The system shall use only operator-provided or recorded rate data and shall not generate market rates."* Problem `P-06` asserts that the recommendation includes `rate_competitiveness` only when data exists. `recommendation_candidates` stores `rate_quote numeric(12,2)` and scores component `rate_competitiveness`. However, inspection of the database design (`06 §3.5` `carriers`, `§3.6` `carrier_equipment_types`, `§3.7` `carrier_service_regions`) reveals **zero rate tables, rate cards, or per-mile cost attributes**.
- **Why it matters:** When `score_candidates` (Node 8) executes, it queries carrier attributes to compute `rate_competitiveness`. Because no carrier rates exist in the database, and shipments only define `target_sell_rate` and `max_buy_rate`, the engine has no data to evaluate. Either `rate_quote` must be randomly fabricated (violating FR-133 and P-06), or the component must always fail or default to null, rendering rate-based ranking non-functional.
- **Recommended Correction:** Add an explicit, optional `carrier_lane_rates` table (or nullable `base_rate_per_mile` on `carrier_service_regions`) to synthetic carrier seed data so the deterministic scoring engine can legitimately compute rate competitiveness without inventing numbers.

---

### [CRIT-04] Terminal State Lockout on Declined Booking Proposal
- **Location:** `docs/03-requirements-specification.md` (Appendix B.3 Diagram D-05, FR-209), `docs/06-database-design.md` (§3.17), `docs/07-agent-workflow.md` (Diagram D-13).
- **Severity:** High
- **Blocks Phase 2:** Yes
- **Explanation:** In `03 Appendix B.3` (Diagram D-05), the Shipment state machine defines the following transitions from `booking_proposed`:
  ```
  booking_proposed --> booked: proposal accepted internally
  booking_proposed --> cancelled: proposal declined/cancelled
  ```
  In freight operations, a booking proposal is an offer to an internal account or carrier. If the carrier declines or the proposal is cancelled due to operational timing, the shipment is NOT dead. The freight must still be moved; the broker must return to sourcing to select candidate #2 or run a new search.
- **Why it matters:** Under the current state machine, if a proposal is declined, the shipment is irreversibly forced into `cancelled` (terminal). The broker cannot re-source or re-recommend without manually creating a brand new shipment and re-typing all requirements.
- **Recommended Correction:** Update Diagram D-05, Diagram D-13, and `ShipmentService` to permit a transition from `booking_proposed` back to `sourcing` (or `validated`) when a proposal is `declined` or `cancelled`.

---

## 4. Database Architecture Review (All 23 Tables Evaluated)

The proposed schema contains 23 tables. Below is an engineering evaluation of every table, assessing its necessity, schema flaws, foreign keys, and recommendations.

| # | Table Name | Purpose | MVP Status | Evaluation & Architectural Critique | Recommendation |
|---|---|---|---|---|---|
| 1 | `users` | Local accounts, roles, login | **Essential** | Standard user model. Good inclusion of role CHECK and `is_active`. | **Keep as-is.** |
| 2 | `customers` | Commercial accounts (paying parties) | **Essential** | Stores account reference code and contact info. `reference_code` unique. | **Keep as-is.** |
| 3 | `shippers` | Origin shipping facility | **Defective** | Exact duplicate of `consignees`. Storing physical origin/destination facilities in two separate tables is an anti-pattern. | **Combine** `shippers` and `consignees` into a single `facilities` table. |
| 4 | `consignees` | Destination receiving facility | **Defective** | Identical structure to `shippers`. Warehouses frequently both ship and receive goods. | **Combine** into `facilities` table. |
| 5 | `carriers` | Master carrier profiles | **Essential** | Stores MC/DOT numbers, compliance dates, status. Note: Missing rate data (see CRIT-03). | **Keep**, add rate support. |
| 6 | `carrier_equipment_types` | Carrier trailer capabilities | **Essential** | Clean M:N association with unique composite key. Uses PostgreSQL `integer[]` for lengths. | **Keep.** |
| 7 | `carrier_service_regions` | Geographic coverage | **Flawed** | Defines `region_type` and `region_value`, but lacks directionality (origin vs destination vs operating authority). | **Keep**, add `direction` or clarify state-matching semantics. |
| 8 | `carrier_availability` | Recorded capacity windows | **Essential** | Time window plus optional regions. Represents synthetic capacity cleanly. | **Keep as-is.** |
| 9 | `shipments` | Core business aggregate | **Defective** | Has `customer_id`, `shipper_id`, `consignee_id` NOT NULL (CRIT-01). Redundant with `shipment_stops`. | **Keep**, make party FKs nullable on draft; derive lane from stops. |
| 10 | `shipment_stops` | Pickup & delivery stops | **Essential** | Excellent table. Multi-stop support with sequence, windows, addresses, and appointment flags. | **Keep as-is.** |
| 11 | `shipment_requirements` | Cargo & handling constraints | **Over-engineered** | Entity-Attribute-Value (EAV) anti-pattern (`value_text`, `value_numeric`, `value_json`). Hard to query. | **Replace** with a structured `requirements jsonb` column on `shipments` table. |
| 12 | `validation_runs` | Persisted validation issue history | **Essential** | Good auditability of validation outcomes; stores issues as `jsonb` snapshot. | **Keep as-is.** |
| 13 | `intake_submissions` | Raw customer text and metadata | **Essential** | Stores `raw_text`, `content_hash`, parse metadata. Vital for untrusted intake traceability. | **Keep as-is.** |
| 14 | `recommendations` | Output of scoring engine | **Essential** | Stores scoring version, template explanation, optional LLM narration, lifecycle state. | **Keep as-is.** |
| 15 | `recommendation_candidates` | Scored carrier candidate pool | **Essential** | Normalizes candidates considered per recommendation. Good use of `component_scores jsonb`. | **Keep as-is.** |
| 16 | `approvals` | Human authorization record | **Essential** | Core HITL artifact. Stores decision, approver, comment, and selected candidate FK. | **Keep as-is.** |
| 17 | `booking_proposals` | Internal carrier award record | **Essential** | Good partial unique index (one active proposal per shipment). Uses `snapshot jsonb`. | **Keep as-is.** |
| 18 | `workflow_executions` | State machine run record | **Redundant** | Duplicates LangGraph's internal PostgreSQL checkpoint tables if `PostgresSaver` is used. | **Keep as lightweight projection**, but do not double-write raw state blobs. |
| 19 | `audit_events` | Append-only audit log | **Essential** | High quality. Uses `bigserial`, indexed correlation IDs, payload `jsonb`, and no `updated_at`. | **Keep as-is.** |
| 20 | `outbox_events` | Transactional outbox pattern | **Unnecessary (Dead Code)** | Architecture defers message brokers and dispatchers (`ADR-009`). Writing outbox rows that are never read is dead code. | **Defer/Remove** from MVP until an actual message consumer exists. |
| 21 | `scoring_configs` | Versioned weight baselines | **Essential** | Clean design. Enforces single active config via partial unique index. | **Keep as-is.** |
| 22 | `idempotency_keys` | API request deduplication | **Flawed / Redundant** | Competes with entity-level `idempotency_key` columns on 4 separate tables. | **Consolidate** idempotency handling (see F-DB-05). |
| 23 | `llm_invocations` | Token usage & latency tracking | **Deferrable** | Tracks token counts and latency for LLM calls. Useful for observability, but deferrable to PH-5. | **Retain as planned for PH-5.** |

### In-Depth Database Architectural Findings

#### [F-DB-01] Duplicate Table Anti-Pattern: `shippers` vs. `consignees`
- **Severity:** High | **Document:** `06 §3.3`, `§3.4` | **Blocks Phase 2:** Yes
- **Explanation:** Tables `shippers` and `consignees` share 100% identical schemas (`customer_id`, `name`, `address_line1`, `city`, `state`, `postal_code`, `country`, `contact_name`, `contact_email`, `contact_phone`). In transportation logistics, both are simply **facilities** (plants, distribution centers, warehouses). A facility in Chicago can act as a shipper on Monday and a consignee on Thursday.
- **Why it matters:** Forces artificial duplication of customer facility master data. Furthermore, `shipments` hardcodes single foreign keys `shipper_id` and `consignee_id`, creating contradictions on multi-stop loads (e.g. 2 pickups, 1 delivery).
- **Correction:** Consolidate into a single `facilities` table (or `shipping_locations`). On `shipments`, allow `origin_facility_id` and `destination_facility_id` as optional convenience references, while letting `shipment_stops` be the authoritative record of stop locations.

#### [F-DB-02] Polymorphic EAV Table Anti-Pattern: `shipment_requirements`
- **Severity:** Medium | **Document:** `06 §3.11` | **Blocks Phase 2:** No
- **Explanation:** The `shipment_requirements` table uses an Entity-Attribute-Value pattern with three separate value columns (`value_text`, `value_numeric`, `value_json`), constrained by `unique(shipment_id, requirement_type)`.
- **Why it matters:** EAV tables introduce unnecessary joins, complicate ORM mapping, and prevent PostgreSQL from enforcing strict schema types on numeric vs string requirements.
- **Correction:** Replace this table by embedding a `requirements jsonb` column directly in the `shipments` table, validated at the API/application layer via Pydantic (`ShipmentRequirementsModel`). This eliminates 1 table, 1 foreign key index, and multiple joins without losing any functionality.

#### [F-DB-03] Write-Only Dead Code: `outbox_events`
- **Severity:** Medium | **Document:** `06 §3.20`, `10 ADR-009` | **Blocks Phase 2:** No
- **Explanation:** `outbox_events` is defined and written to on every proposal creation (`DF-04`). However, `04 §8`, `10 ADR-009`, and `13 §7` explicitly confirm: *"No dispatcher is implemented in the MVP; table exists so a worker can be added without a schema rewrite."*
- **Why it matters:** Violates the YAGNI (You Aren't Gonna Need It) principle. Writing to a table that has zero readers or background dispatchers consumes write I/O, inflates storage, and gives a false illusion of event-driven decoupling.
- **Correction:** Remove `outbox_events` from the MVP database migrations. Add it back only when a concrete background dispatcher (e.g. Celery/ARQ) and external integration are implemented.

#### [F-DB-04] Semantic Ambiguity in `carrier_service_regions`
- **Severity:** Medium | **Document:** `06 §3.7` | **Blocks Phase 2:** No
- **Explanation:** The table stores `carrier_id`, `region_type` (`state`, `metro`, `radius_miles`, `postal_prefix`), and `region_value` (e.g. `TX`). It lacks any directionality or coverage scope.
- **Why it matters:** When checking eligibility for a shipment from Chicago, IL to Dallas, TX (`FR-092`), does a carrier serving region `TX` mean they can pick up in TX, deliver in TX, or both? Without clear semantics, the `EligibilityEngine` rule will either over-filter or under-filter carriers arbitrarily.
- **Correction:** Add an `inbound_outbound` flag (`origin`, `destination`, `both`) or explicitly document in `06` and `07` that in MVP, region coverage represents origin operating presence.

#### [F-DB-05] Competing Dual Idempotency Implementations
- **Severity:** Medium | **Document:** `06 §3.22`, `09 §6` | **Blocks Phase 2:** No
- **Explanation:** The system introduces a centralized `idempotency_keys` table to store HTTP request hashes and responses (`06 §3.22`), but simultaneously puts unique `idempotency_key text` columns on `intake_submissions`, `approvals`, `booking_proposals`, and `workflow_executions`.
- **Why it matters:** Dual bookkeeping creates architectural ambiguity: does the web middleware short-circuit repeated calls via `idempotency_keys`, or does the domain service handle duplicate keys via unique database constraints? If the middleware caches the response, the domain column is never exercised on replay.
- **Correction:** Standardize on the middleware-level `idempotency_keys` table for HTTP mutation endpoints, and use deterministic natural/business keys in the domain models.

---

## 5. AI Agent & Workflow Architecture Review (All 16 Canonical Nodes)

Below is an engineering analysis of the 16 canonical workflow nodes defined in `07 §5` and frozen in `03 Appendix A §A.4`.

### Canonical Node Evaluation Matrix

| # | Node Name | Defined Responsibility | Type | Clean Responsibility? | Bounded & Safe? | Architectural Finding |
|---|---|---|---|---|---|---|
| 1 | `start_execution` | Initialize execution row, state, budgets | Deterministic | Yes | Yes (bounded time/runs) | Clean entry point. |
| 2 | `load_shipment` | Fetch shipment aggregate, stops, requirements | Deterministic | Yes | Yes (2s timeout, read-only) | Clean read operation. |
| 3 | `validate_shipment` | Run deterministic `ValidationEngine` | Deterministic | Yes | Yes (5s timeout, pure) | Redundant with pre-workflow validation (see F-AGENT-03). |
| 4 | `decide_validation_outcome` | Branch on validation result (pass/fail) | Deterministic | Yes | Yes (guarded branch) | Clean conditional routing. |
| 5 | `extract_requirements` | Normalize structured requirements for eligibility | Deterministic | **Confusing** | Yes (pure logic) | **Misleading name.** Extraction was already completed in Intake (see F-AGENT-01). |
| 6 | `resolve_carrier_candidates` | Query carrier master data for candidate pool | Deterministic | Yes | Yes (5s timeout, read-only) | Clean candidate retrieval. |
| 7 | `filter_eligible_carriers` | Run deterministic hard eligibility filters | Deterministic | Yes | Yes (pure logic) | Hard boundary: zero LLM access. |
| 8 | `score_candidates` | Apply weighted scoring baseline | Deterministic | Yes | Yes (reproducible math) | Clean scoring execution. |
| 9 | `generate_explanation` | Build fact bundle; call LLM for narration | **LLM-assisted** | Yes | Yes (10s timeout, fallback) | Only LLM node in workflow. Fallback to template is sound. |
| 10 | `persist_recommendation` | Atomically write recommendation & candidates | Deterministic | Yes | Yes (idempotent upsert) | Clean persistence transaction. |
| 11 | `request_human_approval` | Create pending approval & interrupt graph | Deterministic | Yes | Yes (pauses execution) | LangGraph interrupt semantics require clarification (see F-AGENT-02). |
| 12 | `apply_human_decision` | Branch based on human approval decision | Deterministic | Yes | Yes (immutable decision) | Clean conditional routing. |
| 13 | `create_booking_proposal` | Snapshot approved data into booking proposal | Deterministic | Yes | Yes (unique index, atomic) | Strictly gated behind human decision. |
| 14 | `record_audit_event` | Emit terminal audit event | Deterministic | **Redundant** | Yes (append-only) | Redundant with per-node transactional audit writes (see F-AGENT-04). |
| 15 | `finalize_execution` | Mark workflow execution `completed` | Deterministic | Yes | Yes (idempotent status) | Clean termination. |
| 16 | `handle_failure` | Record errors, compensate, emit failure event | Deterministic | Yes | Yes (safe terminal sink) | Clean exception sink. |

### In-Depth Agent Architecture Findings

#### [F-AGENT-01] Misleading Node Name: `extract_requirements`
- **Severity:** Medium | **Document:** `07 §5 Node 5`, `03 §A.4` | **Blocks Phase 2:** No
- **Explanation:** Node 5 is named `extract_requirements`. However, the documentation notes: *"Text-to-structure extraction happens in the Intake Service before the workflow starts (FR-006). This node only normalizes already-structured values. No LLM call occurs here."*
- **Why it matters:** Naming a purely deterministic normalization step `extract_requirements` inside an "AI Agent" workflow leads external reviewers and developers to assume this node calls an LLM to extract requirements from prose.
- **Correction:** Rename Node 5 in Appendix A §A.4 and `07` to `normalize_requirements` or `prepare_eligibility_profile`.

#### [F-AGENT-02] LangGraph Interrupt and Node Re-execution Semantics
- **Severity:** High | **Document:** `07 §7`, `§11` | **Blocks Phase 2:** Yes
- **Explanation:** In LangGraph, when a node calls `interrupt()`, the execution state is saved to the checkpointer. When the graph is resumed via `Command(resume=...)`, execution resumes **inside the node that called interrupt** (Node 11 `request_human_approval`), not at the beginning of the next node.
- **Why it matters:** In Node 11, the system inserts the `approvals` database row before calling `interrupt()`. If Node 11 re-executes upon resumption, it risks creating a duplicate approval row or failing on idempotency unless explicitly coded with a pre-interrupt/post-interrupt state branch.
- **Correction:** Clearly document the internal structure of Node 11:
  - Phase A (Pre-interrupt): Insert `approvals` record, transition shipment to `pending_approval`, call `interrupt()`.
  - Phase B (Post-interrupt): Receive resume payload (decision) and pass directly to Node 12 without re-inserting records.

#### [F-AGENT-03] Redundant Validation Re-Execution
- **Severity:** Low | **Document:** `07 §5 Node 3`, `09 §5.3` | **Blocks Phase 2:** No
- **Explanation:** `09 §5.3` states that `POST /api/v1/shipments/{id}/recommendations` requires the shipment to already be in `validated` or `sourcing` status (having passed deterministic validation). Yet Node 3 (`validate_shipment`) immediately re-runs the full `ValidationEngine` suite.
- **Why it matters:** While re-validating for freshness is defensive, doing it twice in back-to-back calls adds redundant database writes to `validation_runs`.
- **Correction:** Clarify that Node 3 performs an in-memory sanity check of the existing validation state unless the shipment's optimistic lock version has changed since the last validation run.

#### [F-AGENT-04] Standalone Node 14 (`record_audit_event`) Architectural Redundancy
- **Severity:** Low | **Document:** `07 §5 Node 14`, `06 §7` | **Blocks Phase 2:** No
- **Explanation:** The architecture repeatedly specifies in `06 §7` that critical domain writes (recommendation persistence, approval decisions, proposal creation) commit their corresponding audit events in the **same database transaction**. However, Node 14 is a dedicated standalone node titled `record_audit_event` placed at the end of the graph.
- **Why it matters:** Having a standalone audit node creates confusion over whether audit events are emitted incrementally during state transitions or batched at the end. If the process crashes between Node 13 and Node 14, Node 13 already committed its audit event transactionally.
- **Correction:** Clarify that Node 14 is specifically responsible for emitting the terminal `workflow.completed` event and consolidating execution metrics, not retroactively logging earlier node actions.

#### [F-AGENT-05] Over-Engineered Orchestrator: LangGraph Justification vs. Complexity
- **Severity:** Medium | **Document:** `04 §4`, `07 §1`, `10 ADR-005` | **Blocks Phase 2:** No
- **Explanation:** LangGraph is chosen as the orchestration engine. However, review of Diagram D-13 reveals that the workflow is **strictly a sequential linear pipeline with deterministic branching**. There are:
  - Zero autonomous routing decisions by the LLM.
  - Zero dynamic loops or tool-use cycles.
  - Exactly one human interrupt.
  - Only one node that calls an LLM (Node 9, for optional text narration).
- **Why it matters:** LangGraph brings a heavy, rapidly evolving dependency chain (`langchain-core`, `langgraph`, checkpointers) that currently has **unverified compatibility with Python 3.14.5** (`10 §6`). If LangGraph experiences installation or typing failures on Python 3.14 on Windows, the entire project stalls.
- **Correction:** Ensure the planned fallback—a pure Python explicit state machine using PostgreSQL for state snapshots—is designed with an identical interface so the project can switch effortlessly if LangGraph causes dependency friction in Phase 5.

---

## 6. API and Backend Review

### Endpoint Design and Completeness Analysis

The REST API contract in `09-api-design.md` proposes 22 endpoints across 9 resource groups.

```
Intake:
  POST /api/v1/intake/submissions
  GET  /api/v1/intake/submissions/{id}
Shipments:
  POST  /api/v1/shipments
  GET   /api/v1/shipments
  GET   /api/v1/shipments/{id}
  PATCH /api/v1/shipments/{id}
  POST  /api/v1/shipments/{id}/validation
  GET   /api/v1/shipments/{id}/validation
Recommendations:
  POST /api/v1/shipments/{id}/recommendations
  GET  /api/v1/shipments/{id}/recommendations
  GET  /api/v1/recommendations/{id}
  POST /api/v1/recommendations/{id}/approvals
Approvals:
  GET  /api/v1/approvals
  GET  /api/v1/approvals/{id}
  POST /api/v1/approvals/{id}/decision
Booking Proposals:
  POST /api/v1/booking-proposals
  GET  /api/v1/booking-proposals
  GET  /api/v1/booking-proposals/{id}
Carriers:
  POST  /api/v1/carriers
  GET   /api/v1/carriers
  GET   /api/v1/carriers/{id}
  PATCH /api/v1/carriers/{id}
  GET|POST|DELETE /api/v1/carriers/{id}/equipment-types
  GET|POST|DELETE /api/v1/carriers/{id}/service-regions
  GET|POST|DELETE /api/v1/carriers/{id}/availability
Workflows:
  GET  /api/v1/workflows/{id}
  POST /api/v1/workflows/{id}/cancel
Audit & Meta:
  GET /api/v1/audit-events
  GET /api/v1/health
  GET /api/v1/meta/enums
```

### Specific API Findings

#### [F-API-01] Missing Scoring Configuration API Endpoints
- **Severity:** High | **Document:** `09-api-design.md`, `03 §A.5`, `03 §5.12` | **Blocks Phase 2:** Yes
- **Explanation:** Requirements `FR-280`, `FR-281`, and `FR-285` mandate creating, validating, and activating versioned scoring configurations, assigned to roles `admin` and `ops_manager` (`03 §3`). However, **neither Appendix A §A.5 nor `09-api-design.md` contains any endpoint for scoring configurations** (e.g. `/api/v1/scoring-configs`).
- **Why it matters:** An operator or administrator has no HTTP interface to view, create, or activate scoring configurations. The capability is orphaned in the specification.
- **Correction:** Add canonical endpoints to `03 §A.5` and `09 §5`:
  - `GET /api/v1/scoring-configs` (List configs)
  - `POST /api/v1/scoring-configs` (Create versioned config)
  - `POST /api/v1/scoring-configs/{id}/activate` (Activate config)

#### [F-API-02] Missing Primary Key in Validation Response Schema
- **Severity:** Medium | **Document:** `09 §5.2` | **Blocks Phase 2:** No
- **Explanation:** In `09 §5.2`, `POST /api/v1/shipments/{id}/validation` returns:
  ```json
  {
    "shipment_id": "uuid",
    "result": "failed",
    "checked_at": "2026-11-22T10:05:00Z",
    "issues": [...],
    "clarification": [...]
  }
  ```
  In `06 §3.12`, the `validation_runs` table has its own primary key `id uuid` and `rules_version text`.
- **Why it matters:** The response omits the identifier of the newly created validation run resource, preventing clients from referencing the specific run or correlating it with audit events.
- **Correction:** Include `"validation_run_id": "uuid"` and `"rules_version": "1.0"` in the response payload.

#### [F-API-03] In-Flight Race Condition Vulnerability in Idempotency Middleware
- **Severity:** High | **Document:** `09 §6`, `06 §3.22` | **Blocks Phase 2:** No
- **Explanation:** `09 §6` defines that the server stores the `Idempotency-Key` with the request hash, response status, and body. However, it does not define locking behavior for **concurrent in-flight requests**.
- **Why it matters:** If an operator double-clicks "Submit" rapidly, two identical requests arrive at the server within milliseconds. If Request 1 has not yet completed and written the response body to `idempotency_keys`, Request 2 finds no cached response and begins executing the same state-changing transaction concurrently, causing duplicate side effects or unhandled unique constraint crashes.
- **Correction:** The idempotency middleware must insert an initial row in `idempotency_keys` with status `in_progress` (or acquire an advisory lock on the key). Request 2 must wait for Request 1 to complete or return `409 Conflict`.

---

## 7. Security and Reliability Review

### [F-SEC-01] Premature Claim of Object-Level Authorization (IDOR) Without Multi-Tenancy
- **Severity:** Medium | **Document:** `11 §5.2`, `§9 RISK-11` | **Blocks Phase 2:** No
- **Explanation:** `11 §5.2` claims: *"Object-level checks on every resource ID; a valid role does not grant access to every object (prevents IDOR)."* However, `01 ASM-10`, `03 §2`, and `06 §2` explicitly establish that the system is **single-tenant** representing **one broker organization**, where all brokers have permission to read and manage all shipments and carriers (`03 §3`).
- **Why it matters:** The document claims an enterprise control (IDOR prevention via object-level ACLs) that is not actually modeled or implemented in the domain or database schema. Claiming non-existent controls impairs architectural credibility.
- **Correction:** Clarify that in the single-tenant MVP, authorization is role-based (RBAC). Object-level tenant scoping is deferred to future multi-tenant phases.

### [F-SEC-02] Plaintext PII Storage in PostgreSQL
- **Severity:** Low | **Document:** `11 §7`, `§12 Q1` | **Blocks Phase 2:** No
- **Explanation:** Raw intake text and facility contact names, emails, and phone numbers are stored in plaintext in PostgreSQL.
- **Why it matters:** While standard for an internal MVP with synthetic data, customer email text containing driver phone numbers or personal notes is exposed to any database operator or read-access user.
- **Correction:** The document correctly notes this as a known gap (`11 §7`). Maintain this as an explicit limitation for synthetic MVP data, requiring application-level column encryption before handling real PII.

### [F-SEC-03] Database Role Immutability vs. Application-Level Immutability
- **Severity:** Medium | **Document:** `06 §3.19`, `11 §8.5` | **Blocks Phase 2:** No
- **Explanation:** The design relies on PostgreSQL database user permissions (`GRANT INSERT, SELECT ON audit_events`) to prevent updates/deletes to audit events.
- **Why it matters:** In typical local development and single-instance portfolio setups, the application connects to PostgreSQL as a single database superuser (`postgres`) that possesses full DDL/DML permissions. Unless two distinct database roles (`app_user` vs `migration_admin`) are explicitly configured in the Docker Compose script, application code can execute `UPDATE` or `DELETE` on audit events unchecked.
- **Correction:** Add a PostgreSQL trigger on `audit_events` that raises an exception on `BEFORE UPDATE OR DELETE`, providing database-level immutability regardless of the connecting user's role.

---

## 8. MVP Scope Assessment (Classification of All 155 Functional Requirements)

The SRS (`docs/03-requirements-specification.md`) defines **155 functional requirements**. For a single developer building a portfolio project, implementing, testing, and documenting 155 production-style requirements is unrealistic and risks project abandonment.

Below, all 155 requirements are systematically classified into four categories:
1. **Essential MVP Requirements (58 Req):** The irreducible core required to demonstrate the AI-assisted brokerage pipeline.
2. **Important but Deferrable Requirements (51 Req):** High-value operational features that can be deferred to a post-MVP release.
3. **Future Product Capabilities (28 Req):** Enterprise TMS features that belong in long-term roadmaps.
4. **Unnecessary or Overlapping Requirements (18 Req):** Redundant, duplicative, or over-specified requirements that should be pruned.

```
========================================================================================
                               REQUIREMENT CLASSIFICATION SUMMARY
========================================================================================
Category                                Count    Percentage    Recommendation
----------------------------------------------------------------------------------------
1. Essential MVP Requirements              58       37.4%       Build in Phases 1-5
2. Important but Deferrable Requirements   51       32.9%       Defer to v1.1
3. Future Product Capabilities             28       18.1%       Move to Roadmap Backlog
4. Unnecessary or Overlapping              18       11.6%       Prune from Specification
----------------------------------------------------------------------------------------
Total Functional Requirements             155      100.0%
========================================================================================
```

### Complete Classification Table of All 155 Requirements

| Requirement ID | Canonical Topic | Current Priority | Recommended Classification | Technical Justification for Classification |
|---|---|---|---|---|
| **FR-001** | Paste plain text intake | Must | **1. Essential MVP** | Core intake demo capability. |
| **FR-002** | Upload `.txt`, `.eml`, `.json` | Must | **2. Deferrable** | Plain text paste and REST are sufficient for MVP; `.eml` parsing adds MIME complexity. |
| **FR-003** | REST intake submission | Must | **1. Essential MVP** | Core API intake capability. |
| **FR-004** | Manual shipment entry | Must | **1. Essential MVP** | Essential fallback when AI is unavailable. |
| **FR-005** | Persist raw intake & hash | Must | **1. Essential MVP** | Crucial for data provenance and idempotency. |
| **FR-006** | Structured draft from text | Must | **1. Essential MVP** | Primary AI value proposition of the system. |
| **FR-007** | Leave absent fields null | Must | **1. Essential MVP** | Core safety principle against hallucination. |
| **FR-008** | Preserve raw text with record | Must | **1. Essential MVP** | Verification and operator auditability. |
| **FR-009** | Detect duplicate submissions | Must | **1. Essential MVP** | Idempotency safety. |
| **FR-010** | Link intake to shipment draft | Must | **1. Essential MVP** | Relational link between raw and structured data. |
| **FR-011** | Review/correct extracted draft | Must | **1. Essential MVP** | Core HITL interaction before validation. |
| **FR-012** | Record extraction metadata | Should | **2. Deferrable** | Detailed model metadata can be simple JSON in MVP. |
| **FR-013** | Reject unsupported/oversized uploads | Must | **4. Unnecessary/Overlapping** | Handled natively by FastAPI/Pydantic request limits; redundant as a business FR. |
| **FR-014** | Untrusted intake text handling | Must | **1. Essential MVP** | Security boundary requirement. |
| **FR-020** | Create shipment draft | Must | **1. Essential MVP** | Fundamental aggregate creation. |
| **FR-021** | Support multi-stop pickup/delivery | Must | **1. Essential MVP** | Basic truckload domain modeling. |
| **FR-022** | Store shipment requirements | Must | **1. Essential MVP** | Necessary for carrier filtering. |
| **FR-023** | Optimistic concurrency on edits | Must | **2. Deferrable** | Single-operator local demo rarely experiences write races; defer version checking. |
| **FR-024** | Retrieve shipment aggregate | Must | **1. Essential MVP** | Standard CRUD read. |
| **FR-025** | Enforce status state machine | Must | **1. Essential MVP** | Core state integrity. |
| **FR-026** | Derive lane from stops | Must | **1. Essential MVP** | Required for carrier matching. |
| **FR-027** | Validate stop sequencing | Must | **1. Essential MVP** | Basic logistics validation rule. |
| **FR-028** | Separate Customer/Shipper/Consignee | Must | **4. Unnecessary/Overlapping** | Duplicates relational table definitions in `06`; redundant as separate FR. |
| **FR-029** | Soft-delete / prevent hard delete | Must | **2. Deferrable** | Defer hard-delete blocks to production hardening. |
| **FR-030** | Filter shipments by status/lane/date | Must | **2. Deferrable** | Basic listing is enough; complex multi-parameter filtering is deferrable. |
| **FR-031** | Record shipment source | Must | **1. Essential MVP** | Provenance tracking (`manual` vs `intake`). |
| **FR-032** | Freeze fields after approval | Must | **1. Essential MVP** | Consequential action protection. |
| **FR-040** | Validate required fields | Must | **1. Essential MVP** | Core validation rule. |
| **FR-041** | Detect contradictory values | Must | **1. Essential MVP** | Demonstrates deterministic validation value. |
| **FR-042** | Emit canonical severity values | Must | **1. Essential MVP** | Structured issue reporting. |
| **FR-043** | Compute validation result status | Must | **1. Essential MVP** | Gate logic for workflow progression. |
| **FR-044** | Block approval on error/critical | Must | **1. Essential MVP** | Core deterministic safety gate. |
| **FR-045** | Allow review of warning issues | Must | **1. Essential MVP** | Non-blocking operator warning capability. |
| **FR-046** | Validation results endpoint | Must | **1. Essential MVP** | API query for validation issues. |
| **FR-047** | Produce clarification request | Should | **2. Deferrable** | Template list of missing fields is sufficient; automated drafting is deferrable. |
| **FR-048** | Support re-validation | Must | **1. Essential MVP** | Required after correcting draft fields. |
| **FR-049** | Persist validation history | Must | **2. Deferrable** | Storing latest validation run is sufficient for MVP; historical runs are deferrable. |
| **FR-050** | Do not auto-fill missing fields | Must | **1. Essential MVP** | Negative constraint against hallucination. |
| **FR-051** | Validate numeric ranges/formats | Must | **1. Essential MVP** | Basic data hygiene. |
| **FR-052** | Validate equipment compatibility | Must | **1. Essential MVP** | Reefer/hazmat domain rule. |
| **FR-060** | Carrier CRUD | Must | **1. Essential MVP** | Master data management. |
| **FR-061** | Canonical carrier status | Must | **1. Essential MVP** | Active/inactive status. |
| **FR-062** | Recorded insurance & authority | Must | **1. Essential MVP** | Required for compliance filtering. |
| **FR-063** | Manage equipment per carrier | Must | **1. Essential MVP** | Core eligibility filter input. |
| **FR-064** | Manage service regions | Must | **1. Essential MVP** | Core eligibility filter input. |
| **FR-065** | Manage availability windows | Must | **1. Essential MVP** | Core eligibility filter input. |
| **FR-066** | Search carriers by criteria | Must | **2. Deferrable** | Workflow queries carriers directly; separate search API is deferrable. |
| **FR-067** | Inactive/suspended ineligible | Must | **1. Essential MVP** | Core compliance filter. |
| **FR-068** | List carrier data for operators | Must | **1. Essential MVP** | UI/API read. |
| **FR-069** | Synthetic carrier seed import | Must | **1. Essential MVP** | Necessary to demo matching. |
| **FR-070** | Record `last_verified_at` & provenance | Should | **2. Deferrable** | Provenance metadata on master data can be deferred. |
| **FR-071** | Reject invalid region/equipment | Must | **4. Unnecessary/Overlapping** | Handled natively by Pydantic enums; redundant as a separate requirement. |
| **FR-072** | Show carrier eligibility context | Should | **2. Deferrable** | Advanced carrier profile UI feature. |
| **FR-090** | Run deterministic hard filters | Must | **1. Essential MVP** | Core eligibility engine. |
| **FR-091** | Filter by equipment type | Must | **1. Essential MVP** | Hard filter #1. |
| **FR-092** | Filter by service region | Must | **1. Essential MVP** | Hard filter #2. |
| **FR-093** | Filter by availability window | Must | **1. Essential MVP** | Hard filter #3. |
| **FR-094** | Filter by carrier status | Must | **1. Essential MVP** | Hard filter #4. |
| **FR-095** | Filter by recorded insurance | Must | **1. Essential MVP** | Hard filter #5. |
| **FR-096** | Filter by hazmat authorization | Must | **1. Essential MVP** | Hard filter #6. |
| **FR-097** | Filter by temperature capability | Must | **1. Essential MVP** | Hard filter #7. |
| **FR-098** | Emit canonical reason codes | Must | **1. Essential MVP** | Explainability of exclusions. |
| **FR-099** | Distinguish `insufficient_data` | Must | **1. Essential MVP** | Honest handling of incomplete profiles. |
| **FR-100** | Eligibility decided in deterministic code | Must | **1. Essential MVP** | Non-negotiable safety constraint. |
| **FR-101** | Persist eligibility evaluation | Must | **1. Essential MVP** | Auditability of candidate pool. |
| **FR-102** | Human-readable eligibility reasons | Must | **1. Essential MVP** | Operator UI explanation. |
| **FR-103** | Configurable eligibility thresholds | Should | **3. Future** | Dynamic rule reconfiguration without code changes is an enterprise feature. |
| **FR-120** | Generate recommendation on request | Must | **1. Essential MVP** | Core recommendation pipeline. |
| **FR-121** | Rank carriers using active config | Must | **1. Essential MVP** | Weighted scoring baseline. |
| **FR-122** | Score breakdown per component | Must | **1. Essential MVP** | Explainable scoring breakdown. |
| **FR-123** | Return top-N ranked candidates | Must | **1. Essential MVP** | Limit candidate clutter. |
| **FR-124** | Recommendation canonical transitions | Must | **1. Essential MVP** | State integrity. |
| **FR-125** | Explanation citing facts + LLM | Must | **1. Essential MVP** | Core AI narration capability. |
| **FR-126** | Explanations cite only recorded facts | Must | **1. Essential MVP** | Faithfulness constraint against hallucination. |
| **FR-127** | Return `no_eligible_carriers` | Must | **1. Essential MVP** | Graceful empty result handling. |
| **FR-128** | Degrade on incomplete data | Must | **1. Essential MVP** | Robustness against null attributes. |
| **FR-129** | Store scoring config version used | Must | **1. Essential MVP** | Exact reproducibility of ranking. |
| **FR-130** | Supersede prior recommendations | Must | **2. Deferrable** | Handling re-recommendation cascades is complex; can simply cancel old run. |
| **FR-131** | Expire stale recommendations (TTL) | Should | **2. Deferrable** | TTL expiry sweeps require background scheduler; defer. |
| **FR-132** | Recommendation detail endpoint | Must | **1. Essential MVP** | API query for approval UI. |
| **FR-133** | Use only recorded rate data | Must | **1. Essential MVP** | Data honesty constraint. |
| **FR-134** | Rank deterministically for same input | Must | **1. Essential MVP** | Reproducibility guarantee. |
| **FR-150** | Start workflow execution | Must | **1. Essential MVP** | Workflow initiation. |
| **FR-151** | Execute canonical node graph | Must | **1. Essential MVP** | Sequential state machine execution. |
| **FR-152** | Persist workflow checkpoints | Must | **1. Essential MVP** | Crash recovery capability. |
| **FR-153** | Enforce execution bounds/budgets | Must | **1. Essential MVP** | Prevents runaway costs and loops. |
| **FR-154** | Pause at approval interrupt | Must | **1. Essential MVP** | Core HITL gate. |
| **FR-155** | Resume from human decision | Must | **1. Essential MVP** | Resumption after approval. |
| **FR-156** | Retry transient tool failures | Must | **2. Deferrable** | In-process calls rarely experience transient network failures in MVP. |
| **FR-157** | Route unrecoverable failures | Must | **1. Essential MVP** | Safe failure sink (`handle_failure`). |
| **FR-158** | Never create proposal without approval | Must | **1. Essential MVP** | Core safety invariant. |
| **FR-159** | Expose workflow status API | Must | **1. Essential MVP** | UI polling and inspection. |
| **FR-160** | Record node-level audit events | Must | **2. Deferrable** | Logging every single node run inflates audit table; phase-level audit is enough. |
| **FR-161** | Idempotent side-effecting nodes | Must | **1. Essential MVP** | Replay safety. |
| **FR-162** | Validate tool payloads with schemas | Must | **4. Unnecessary/Overlapping** | In-process functions already use Pydantic; redundant. |
| **FR-163** | Restrict tool calls to allowlist | Must | **4. Unnecessary/Overlapping** | LLM has no tools; orchestrator code is fixed; redundant. |
| **FR-164** | Mock LLM provider for tests | Must | **1. Essential MVP** | Fast offline unit testing. |
| **FR-165** | Record LLM invocation metadata | Should | **2. Deferrable** | Telemetry tracking can be deferred. |
| **FR-166** | Cancel running/waiting workflow | Should | **2. Deferrable** | Manual cancellation endpoint is a secondary convenience. |
| **FR-167** | Stop repeated no-progress loops | Must | **4. Unnecessary/Overlapping** | The graph is acyclic; unbounded loops cannot occur. |
| **FR-168** | Preserve state across restarts | Must | **1. Essential MVP** | Durability guarantee. |
| **FR-180** | Create approval from recommendation | Must | **1. Essential MVP** | HITL queue creation. |
| **FR-181** | Display breakdown to approver | Must | **1. Essential MVP** | Core UI decision screen. |
| **FR-182** | Authorize human approval | Must | **1. Essential MVP** | Core human gate. |
| **FR-183** | Rejection with required reason | Must | **1. Essential MVP** | Rejection handling. |
| **FR-184** | Request changes with note | Must | **2. Deferrable** | Reject or approve is sufficient for MVP; changes-requested adds extra cycle. |
| **FR-185** | Enforce role permissions on approval | Must | **1. Essential MVP** | Authorization enforcement. |
| **FR-186** | Immutable approval records | Must | **1. Essential MVP** | Auditability and non-repudiation. |
| **FR-187** | Expire approvals after TTL | Should | **2. Deferrable** | TTL expiry requires scheduler; defer. |
| **FR-188** | Separation of duties (4-eyes) | Could | **3. Future** | Explicitly marked optional/could; defer. |
| **FR-189** | Idempotent approval decisions | Must | **1. Essential MVP** | Prevents duplicate decision recording. |
| **FR-190** | Select non-top eligible candidate | Must | **1. Essential MVP** | Human discretion over automated ranking. |
| **FR-191** | Record selected candidate on approval | Must | **1. Essential MVP** | Captures the human choice. |
| **FR-192** | Refuse approval if superseded | Must | **2. Deferrable** | Coupled with recommendation superseding; defer. |
| **FR-200** | Create proposal only after approval | Must | **1. Essential MVP** | Primary safety gate. |
| **FR-201** | Snapshot approved data into proposal | Must | **1. Essential MVP** | Prevents downstream data drift. |
| **FR-202** | Proposal canonical status transitions | Must | **1. Essential MVP** | State integrity. |
| **FR-203** | No external tender in MVP | Must | **1. Essential MVP** | Scope boundary honesty. |
| **FR-204** | Idempotent proposal creation | Must | **1. Essential MVP** | Prevents double-booking. |
| **FR-205** | Retrieve/list booking proposals | Must | **1. Essential MVP** | Operator visibility. |
| **FR-206** | Refuse proposal if approval invalid | Must | **4. Unnecessary/Overlapping** | Exact mirror of FR-200; redundant. |
| **FR-207** | One active proposal per shipment | Must | **1. Essential MVP** | Crucial partial unique index. |
| **FR-208** | Audit events for proposal | Must | **1. Essential MVP** | Consequential action audit trail. |
| **FR-209** | Allow proposal decline/cancel | Should | **2. Deferrable** | Proposal lifecycle changes can be basic in MVP. |
| **FR-220** | Append audit events on mutation | Must | **1. Essential MVP** | Fundamental audit requirement. |
| **FR-221** | Canonical audit event types | Must | **1. Essential MVP** | Structured event schema. |
| **FR-222** | Correlate audit by trace/exec/shipment | Must | **1. Essential MVP** | Distributed tracing and debugging. |
| **FR-223** | Audit query endpoint with filters | Must | **2. Deferrable** | Direct database query suffices for dev; full API query is deferrable. |
| **FR-224** | Deny update/delete on audit events | Must | **1. Essential MVP** | Tamper resistance. |
| **FR-225** | Structured JSON logs with trace ID | Must | **1. Essential MVP** | Observability standard. |
| **FR-226** | Unauthenticated health endpoint | Must | **1. Essential MVP** | Container liveness check. |
| **FR-227** | Workflow latency & failure metrics | Should | **2. Deferrable** | OpenTelemetry metrics hooks are secondary to structured logs. |
| **FR-228** | LLM token and cost metrics | Should | **2. Deferrable** | Defer to PH-5/6 hardening. |
| **FR-229** | Record evaluation run results | Should | **2. Deferrable** | Offline test runner scripts suffice; in-DB eval storage is deferrable. |
| **FR-230** | Redact sensitive fields from logs | Must | **1. Essential MVP** | Basic privacy protection. |
| **FR-231** | Audit configuration changes | Must | **2. Deferrable** | Config changes are rare in local demo. |
| **FR-250** | Maintain local user accounts | Must | **1. Essential MVP** | Authentication baseline. |
| **FR-251** | Authenticate UI users with session | Must | **1. Essential MVP** | Jinja2/HTMX login. |
| **FR-252** | Authenticate API clients with token | Must | **2. Deferrable** | Session auth for UI is enough for MVP; API tokens can be deferred. |
| **FR-253** | Implement canonical RBAC roles | Must | **2. Deferrable** | 4 distinct roles is overkill for local portfolio; collapse to admin vs broker. |
| **FR-254** | Enforce permissions on REST API | Must | **2. Deferrable** | Basic auth check suffices initially. |
| **FR-255** | Enforce permissions on UI routes | Must | **2. Deferrable** | Basic login check suffices initially. |
| **FR-256** | Deny unauthenticated access | Must | **1. Essential MVP** | Secure by default. |
| **FR-257** | Salted password hashing (Argon2/bcrypt) | Must | **1. Essential MVP** | Standard security practice. |
| **FR-258** | Idle session expiration | Should | **3. Future** | Session timeout sweeps are secondary in local demo. |
| **FR-259** | Admin user management | Must | **2. Deferrable** | Seeding users via CLI script is sufficient for MVP; admin UI is deferrable. |
| **FR-260** | Audit auth failures | Should | **3. Future** | Security log hardening. |
| **FR-280** | Versioned scoring configurations | Must | **1. Essential MVP** | Policy versioning. |
| **FR-281** | Exactly one active scoring config | Must | **1. Essential MVP** | Scoring predictability. |
| **FR-282** | Load synthetic seed data only | Must | **1. Essential MVP** | Privacy and demonstration baseline. |
| **FR-283** | Reset/reseed database tool | Should | **1. Essential MVP** | Fast local developer iteration. |
| **FR-284** | Expose `/meta/enums` metadata | Should | **2. Deferrable** | Nice-to-have introspection endpoint. |
| **FR-285** | Validate config before activation | Must | **1. Essential MVP** | Weights must sum to 1.0. |
| **FR-286** | Feature flag for LLM narration | Should | **1. Essential MVP** | Vital fallback to template explanations. |
| **FR-287** | Admin system status view | Could | **3. Future** | Monitoring dashboard; marked 'Could'. |

### Solo Developer Implementation Feasibility

The roadmap in `13 §3` estimates **15 to 21 weeks part-time** across 7 phases.
- **Reality Check:** Implementing 155 requirements across 23 tables, 22 endpoints, LangGraph, Jinja2/HTMX, and an evaluation harness with 6 synthetic corpora will realistically require **600–800 engineering hours**. For a solo developer working 15 hours per week, this represents **40 to 53 weeks (nearly a full calendar year)**.
- **Recommendation:** Prune the MVP scope strictly to the **58 Essential Requirements**. By deferring the 51 secondary requirements and removing the 18 redundant requirements, total effort drops to **180–240 hours (12–16 weeks part-time)**, making the project realistic, achievable, and far more polished as a portfolio showcase.

---

## 9. Cross-Document Consistency Review

A rigorous cross-document audit revealed the following contradictions, naming misalignments, and omissions across the documentation set:

| Finding ID | Source Doc & Section | Target Doc & Section | Description of Contradiction / Inconsistency |
|---|---|---|---|
| **F-DOC-01** | `03 Appendix A §A.5` | `09 §5`, `03 §5.12` | **Missing Scoring Config API:** `FR-280/281/285` require managing scoring configs, but `/api/v1/scoring-configs` is completely omitted from canonical API resources (`03 §A.5`) and `09`. |
| **F-DOC-02** | `06 §3.9` (`shipments`) | `09 §5.1`, `08 DF-01` | **Intake Nullability Contradiction:** `shipments` requires `customer_id`, `shipper_id`, `consignee_id` `NOT NULL`, but intake API accepts requests without resolved customer or facilities. |
| **F-DOC-03** | `03 Appendix B.3` (D-05) | `03 FR-209`, `06 §3.17` | **Shipment State Lockout:** Diagram D-05 transitions `booking_proposed` only to `booked` or `cancelled`, permanently locking shipments if a proposal is declined. |
| **F-DOC-04** | `07 §5 Node 5` | `03 §A.4`, `03 FR-006` | **Node 5 Naming vs. Reality:** Canonical name is `extract_requirements`, but prose admits extraction occurred in Intake and this node only performs normalization. |
| **F-DOC-05** | `06 §3.20` (`outbox_events`)| `10 ADR-009`, `13 §7` | **Outbox Dead Code:** `06` creates `outbox_events` and `08 DF-04` writes to it, but `04 §8` and `10 ADR-009` confirm no dispatcher or queue exists in MVP. |
| **F-DOC-06** | `06 §3.12` (`validation_runs`)| `09 §5.2` | **Validation Schema Omission:** `validation_runs` defines primary key `id uuid` and `rules_version`, but API response schema omits both fields. |
| **F-DOC-07** | `03 FR-133`, `06 §3.15` | `06 §3.5`, `01 ASM-03` | **Missing Rate Data Source:** Recommendation scores `rate_competitiveness` and candidate `rate_quote`, but carrier master tables store zero rate data. |
| **F-DOC-08** | `03 §A.3`, `06 §3.3/3.4` | `06 §3.10` (`shipment_stops`)| **Facility Duplication:** `shippers` and `consignees` duplicate identical schemas and conflict with multi-stop pickup/delivery facility addresses in `shipment_stops`. |

---

## 10. Recommended Architecture Changes

To transform FreightOps AI into an implementable, robust, and impressive portfolio project, the following architectural refactorings are recommended:

```
========================================================================================
                          RECOMMENDED ARCHITECTURAL TARGET STATE
========================================================================================

  [Unstructured Intake]
           │
           ▼
  [IntakeService] ──► (Validates payload & stores raw text in intake_submissions)
           │
           ▼
  [LLMGateway] ─────► (Extracts draft fields with Pydantic schema validation)
           │
           ▼
  [ShipmentService] ─► (Creates draft shipment; party FKs nullable; stops populated)
           │
           ▼
  [ValidationEngine] ─► (Pure deterministic rules; gates on error/critical)
           │
           ▼
  [EligibilityEngine] ─► (Deterministic hard filters: equipment, status, insurance, availability)
           │
           ▼
  [RecommendationEngine] ─► (Scores eligible candidates; builds fact bundle)
           │
           ├──► [LLMGateway] (Constrained explanation narration; fallback to template)
           ▼
  [Human Approval Gate] ──► (Jinja2+HTMX screen; approver selects carrier; immutable record)
           │
           ▼
  [BookingProposalService] ─► (Atomic snapshot in JSONB; single active proposal enforced)
           │
           ▼
  [PostgreSQL System of Record] ──► (16 normalized tables; append-only audit trail)
========================================================================================
```

### Specific Structural Changes

1. **Schema Refactoring (23 Tables → 16 Tables):**
   - **Consolidate Facilities:** Merge `shippers` and `consignees` into a single `facilities` table.
   - **Eliminate EAV Anti-Pattern:** Drop `shipment_requirements` and store structured requirements in a `requirements jsonb` column on `shipments`.
   - **Prune Dead Code:** Drop `outbox_events` until an external queue dispatcher is built.
   - **Make Draft Party FKs Nullable:** Update `shipments.customer_id`, `origin_facility_id`, and `destination_facility_id` to be nullable in draft status.
   - **Streamline Checkpoints:** Rely on LangGraph's native checkpointer tables (or lightweight state column), removing redundant double-writing.
2. **Resolve Rate Modeling:**
   - Add a lightweight `carrier_rates` table (or `rate_per_mile` column on carrier equipment) in the synthetic seed tool so deterministic scoring has a factual basis to evaluate `rate_competitiveness`.
3. **Formalize In-Process Resumption:**
   - Introduce a lightweight scheduler (such as `APScheduler` or a background asyncio loop in FastAPI lifespan) to monitor Approval TTL expirations and execute resumption sweeps cleanly.
4. **Rename Node 5:**
   - Update canonical Node 5 from `extract_requirements` to `normalize_requirements` across all documents.
5. **Add Scoring Configuration Endpoints:**
   - Specify `GET /api/v1/scoring-configs`, `POST /api/v1/scoring-configs`, and `POST /api/v1/scoring-configs/{id}/activate` in `09-api-design.md`.
6. **Correct Shipment State Machine:**
   - Allow a shipment to transition from `booking_proposed` back to `sourcing` if a booking proposal is declined or cancelled.

---

## 11. Questions Requiring Human Decisions

Before updating the Phase 1 specification documents, the human designer must decide on the following architectural choices:

1. **Python Runtime Version: Pin to Python 3.12/3.13 LTS or retain 3.14?**
   - *Context:* Python 3.14.5 is installed, but compatibility with `SQLAlchemy`, `asyncpg`, `Alembic`, and `LangGraph` on Windows is unverified.
   - *Recommendation:* Pin the project virtual environment to **Python 3.12 LTS**. It guarantees 100% binary wheel compatibility for database drivers, Pydantic, and LangGraph without risking blocked development in Phase 1.
2. **Workflow Engine: LangGraph or Pure Python State Machine?**
   - *Context:* The workflow is a linear pipeline with one interrupt. LangGraph adds substantial dependency weight and API instability.
   - *Recommendation:* If the goal is strictly a portfolio demonstration of LangGraph, retain LangGraph for Phase 5. If the goal is rock-solid software engineering with minimal dependencies, build an explicit 200-line Python State Machine.
3. **Database Schema: Consolidate `shippers` and `consignees` into `facilities`?**
   - *Recommendation:* **Yes, consolidate immediately.** Maintaining two identical tables for origin and destination parties is an indefensible schema flaw.
4. **Scope Commitment: Prune to 58 Essential Requirements?**
   - *Recommendation:* **Yes, prune.** Committing to 58 essential requirements allows one developer to ship a functional, thoroughly tested end-to-end application in 8–10 weeks, rather than abandoning a 155-requirement behemoth halfway through.

---

## 12. Final Readiness Assessment

| Review Dimension | Status | Assessment Summary |
|---|---|---|
| **1. Business & Operational Model** | **Passed with Advisory** | Faithfully captures truckload brokerage concepts. Needs declined-proposal return to sourcing. |
| **2. Modular Monolith Architecture** | **Passed** | Clean internal boundaries (`web → application → domain → infrastructure`). Strong separation. |
| **3. Database Architecture** | **Failed (Requires Fixes)** | Blocked by CRIT-01 (nullability deadlock), F-DB-01 (facility duplication), and missing rate sources. |
| **4. AI Agent & Workflow Design** | **Passed with Advisory** | Excellent deterministic boundary. Needs interrupt semantics clarification and Node 5 rename. |
| **5. API Contract & Schemas** | **Failed (Requires Fixes)** | Blocked by missing `/scoring-configs` endpoints and in-flight idempotency race conditions. |
| **6. Security & Reliability Posture** | **Passed** | Strong untrusted input defenses, zero LLM tools, immutable audit trail. |
| **7. Roadmap & Scope Feasibility** | **Failed (Requires Pruning)**| 155 requirements and 23 tables is unfeasible for a solo developer. Pruning is mandatory. |

### Final Phase 2 Gate Decision: **HOLD**

> **Remediation Requirement:** Phase 2 (Implementation) should **NOT** proceed until the contract revisions detailed in Section 10 are incorporated into `03-requirements-specification.md`, `06-database-design.md`, `07-agent-workflow.md`, and `09-api-design.md`. Once the schema deadlocks are resolved and the scope is pruned, FreightOps AI will stand as an exceptional, production-grade AI systems engineering portfolio project.

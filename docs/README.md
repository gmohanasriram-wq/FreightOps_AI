# FreightOps AI — Documentation

Phase 1 documentation for an AI-assisted freight brokerage operations platform. Every document represents the reviewed, approved, and frozen architectural contract (Contract 2.2). There is no application code yet.

## Reading order

| # | Document | Primary Scope |
|---|---|---|
| 0 | [Project README](../README.md) | Project pitch, architectural pillars, stack, and document index |
| 1 | [01 Business understanding](./01-business-understanding.md) | Freight brokerage domain, parties, lifecycle, rates, capacity |
| 2 | [02 Problem definition](./02-problem-definition.md) | Ten operational problems, each mapped to AI, deterministic code, or human oversight |
| 3 | [03 Requirements](./03-requirements-specification.md) | 156 functional requirements (95 MVP), single-tenant RBAC, **Appendix A Contracts** |
| 4 | [04 System architecture](./04-system-architecture.md) | Modular monolith, container boundaries, dependency rules, verbatim MVP cut line |
| 5 | [05 Component architecture](./05-component-architecture.md) | Component responsibilities and authoritative LLM vs deterministic boundary matrix |
| 6 | [06 Database design](./06-database-design.md) | 21 database tables, constraints, partial indexes, ER diagrams, audit trigger |
| 7 | [07 Agent workflow](./07-agent-workflow.md) | State schema, 16 canonical nodes, LangGraph checkpoints, HITL interrupt/resume |
| 8 | [09 API design](./09-api-design.md) | REST endpoints, facilities, scoring configs, RFC 9457 errors, idempotency locking |
| 9 | [08 Data flow](./08-data-flow.md) | Five end-to-end operational flows with trust boundaries and failure points |
| 10 | [10 Technology decisions](./10-technology-decisions.md) | Stack evaluation, Python 3.12 target, ADR-001 through ADR-020 |
| 11 | [11 Security and reliability](./11-security-and-reliability.md) | Threat model, audit immutability trigger, idempotency race control |
| 12 | [12 Evaluation strategy](./12-evaluation-strategy.md) | Deterministic vs model metrics, test corpora `DS-01..DS-06`, release gates |
| 13 | [13 Development roadmap](./13-development-roadmap.md) | Phases PH-0 through PH-6, requirement traceability, verbatim cut line |
| 14 | [14 Architecture review](./14-architecture-review.md) | Independent critical architecture assessment and findings report |
| 15 | [15 Architecture revision log](./15-architecture-revision-log.md) | Authoritative log of all Phase 1.6 and 1.7 architectural revisions and defect corrections |

*Note on Reading Order:* `09` precedes `08` because API resource paths and schemas are part of the frozen contract, and the sequence diagrams in `08` reference them.

## Reading paths by audience

| Audience | Recommended path |
|---|---|
| Business / Product Reviewer | `01` → `02` → `03` §1–2 → `04` §1 → `13` → `15` |
| Implementing Engineer | `03` Appendix A → `04` → `05` → `06` → `07` → `09` → `08` → `10` → `13` |
| Security / Reliability Auditor | `05` §3 → `07` §9 → `09` §6 → `11` → `14` |
| AI / Agent Architect | `02` → `05` §3 → `07` → `12` → `10` §4.4–4.5 |

## Source-of-truth hierarchy

When two documents appear to conflict, resolve in this strict precedence order:

1. **`03` Appendix A** — Canonical vocabulary, enums, entity names, workflow nodes, API paths, and event types.
2. **`06` Database Design** — Authoritative table schemas, column types, foreign keys, constraints, and triggers.
3. **`09` API Design** — Request and response shapes, validation rules, HTTP status codes, and error codes.
4. **`07` Agent Workflow** — Canonical node behavior, conditional edges, retry bounds, and interrupt semantics.
5. **Prose descriptions in any document** — Context and explanation, subservient to contracts above.

### Specific authorities

| Architectural Question | Authoritative Source |
|---|---|
| What does this term mean? | `03` Appendix A §A.1 |
| What are the allowed enum values? | `03` Appendix A §A.2 |
| What is this table called and structured? | `03` Appendix A §A.3, detailed in `06` |
| What are the canonical workflow nodes? | `03` Appendix A §A.4, detailed in `07` |
| What is the canonical REST API path? | `03` Appendix A §A.5, detailed in `09` |
| What is the authoritative MVP cut line? | `03` §1.3 (copied verbatim in `04` §10 and `13` §9) |
| Who decides carrier eligibility? | `05` §3 boundary matrix (restated in `07` §14) |

## Contract version and changelog

| Version | Date | Architectural Change Summary |
|---|---|---|
| **2.2** | 2026-11-25 | **Phase 1.7.5 Architecture Remediation.**<br/>- Resolved `BLK-01`: unified atomic lease acquisition (`queued`, `resumption_pending` preserving `attempt_count`, expired `running` incrementing `attempt_count` + bounded compute) and atomic limit exhaustion (`timed_out` vs `failed` + `workflow.failed` audit) across `06`, `07`, `08`, `09`, `11`.<br/>- Resolved `BLK-02`: added `workflow_execution_id` FK correlation on `recommendations` and `approvals` (Decision D1); promoted `shipments.equipment_type` to a first-class nullable-on-draft column constrained to `dry_van`, `reefer`, `flatbed` (Option 1); aligned `shipments.requirements` to 9 canonical JSONB keys; reconciled approval/booking/fencing/Node 13–15 boundaries.<br/>- Resolved `BLK-03`: synchronized Contract 2.2 scope, active 23-operation MVP REST API surface (`03 §A.5` vs `09 §5`), session-cookie + CSRF MVP auth (`FR-252` Post-MVP, Decision B2), and verbatim MVP cut line across `03 §1.3`, `04 §10`, and `13 §9`.<br/>- Resolved `BLK-04`: reconciled requirement inventory to 156 total (95 MVP, 49 Post-MVP, 5 Future, 6 Merged, 1 Removed), promoted `FR-156` to MVP `PH-5` (Decision A1), moved `FR-069` to `PH-1`, and standardized on 7 hard eligibility filters excluding `safety_rating` (Decision C1). |
| **2.1** | 2026-11-23 | **Phase 1.7 Architecture Defect Correction.**<br/>- Corrected draft stop address nullability in database schema and API contracts (DEF-01).<br/>- Separated terminal failure sink (`handle_failure`) from successful workflow finalization; failed executions never overwritten as completed (DEF-02).<br/>- Reconciled requirement inventory across documents: exactly 156 requirements (120 MVP, 24 Post-MVP, 5 Future, 7 Merged/Removed) with active phase assignments on MVP items only (DEF-03).<br/>- Standardized `flat_rate`, `rate_per_mile`, and `source = 'synthetic'` across database and API contracts with unique active constraint (DEF-04).<br/>- Defined transaction boundaries, execution row locking (`SELECT FOR UPDATE`), 4 crash recovery scenarios, configurable 60s lease timeout, and bounded startup recovery check that preserves pending human approvals (DEF-05).<br/>- Synchronized verbatim MVP cut line across `03 §1.3`, `04 §10`, and `13 §9`; confirmed intake upload scope boundary (INC-02); harmonized facilities model (INC-01); established approval command-to-state mapping (INC-03); documented pure Python state machine as architectural contingency pattern (INC-05). |
| **2.0** | 2026-11-22 | **Phase 1.6 Architecture Revision & Contract Freeze.**<br/>- Targeted Python 3.12 runtime (ADR-017).<br/>- Retained LangGraph with PostgreSQL checkpointer and pure Python state machine fallback (ADR-005).<br/>- Consolidated `shippers` and `consignees` into `facilities` entity (ADR-019).<br/>- Draft shipment party FKs made nullable on intake to resolve deadlock (CRIT-01).<br/>- Replaced EAV `shipment_requirements` with `shipments.requirements jsonb` (ADR-020).<br/>- Added `carrier_lane_rates` table for factual rate scoring (CRIT-03).<br/>- Removed `outbox_events` table from MVP schema (ADR-009).<br/>- Renamed Node 5 to `normalize_requirements` (F-AGENT-01).<br/>- Simplified scheduling: deferred Celery, Redis, and APScheduler; event-driven resume on approval decision; deferred automatic TTL sweeps (ADR-018).<br/>- Added re-sourcing transition: proposal decline/cancellation resets shipment to `sourcing` (CRIT-04).<br/>- Added database trigger `prevent_audit_event_mutation()` for audit immutability (F-SEC-03).<br/>- Added atomic `in_progress` concurrency locking to `idempotency_keys` (F-API-03).<br/>- Total database tables frozen at 21; canonical nodes frozen at 16; MVP requirements frozen at 68. |
| 1.0 | 2026-11-22 | Initial Phase 1 documentation and contract freeze draft. |

## Diagram inventory

Diagram identifiers are permanent and stable across releases. Gaps represent reserved identifiers.

| ID | Location | Description |
|---|---|---|
| `D-01` | `01` | Freight operational lifecycle from customer request to delivery |
| `D-03` | `02` | Freight brokerage problems mapped to system capabilities |
| `D-04` | `03` | System context diagram and actor interactions |
| `D-05` | `03` Appendix B | Canonical Shipment state machine (with re-sourcing transition) |
| `D-06` | `03` Appendix B | Canonical Approval state machine |
| `D-07` | `04` | Modular monolith logical container boundaries |
| `D-08` | `04` | Strict module dependency direction (`api` → `services` → `domain` → `infrastructure`) |
| `D-09` | `04` | Single-node deployment topology (FastAPI + PostgreSQL) |
| `D-10` | `05` | Component interaction model |
| `D-11` | `06` | Core domain entity-relationship diagram (21 tables) |
| `D-12` | `06` | Workflow, approval, booking proposal, and audit entity relationships |
| `D-13` | `07` | **Authoritative 16-node LangGraph workflow graph** |
| `D-13a` | `05` | End-to-end happy-path collaboration sequence |
| `D-14` | `07` | Human-in-the-loop interrupt and event-driven resume sequence |
| `D-18` | `11` | Four architectural trust boundaries |
| `D-19` | `12` | Deterministic and model evaluation pipeline |
| `D-20` | `13` | Indicative implementation roadmap timeline |

*Operational Flow Diagrams:* The five end-to-end data flows in `08` are designated `DF-01` through `DF-05`.

## Scope reminder

This documentation set intentionally contains zero application code, zero dependency lockfiles, and zero `.gitignore` files. Phase 2 (Application Implementation) begins only following authorized sign-off on this Contract 2.1 specification.

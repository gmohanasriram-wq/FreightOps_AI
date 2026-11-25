# FreightOps AI

**An AI-assisted freight brokerage operations platform — designed, reviewed, and contract-frozen.**

FreightOps AI is a portfolio project that transforms unstructured customer freight requests into validated shipment aggregates, deterministic carrier recommendations, an authorized human approval, and an internal booking proposal. The design keeps every consequential financial, legal, and operational decision strictly within deterministic Python code or authorized human hands; a language model is employed exclusively for unstructured text extraction and explanation phrasing.

> **Status: Phase 1.7.5 — Architecture Remediation Complete (Contract 2.2).**
> There is no application code, no database, no running service, and no LLM integration in this repository. Every technical statement below describes the authoritative, reviewed architectural contract.

## The business problem

A freight broker operates as the operational intermediary between commercial shippers needing freight moved and motor carriers operating tractor-trailer capacity. Brokers receive high volumes of unformatted requests via email, text, and customer portals — frequently missing critical pickup windows, weight limits, temperature specifications, or equipment details. Brokers must qualify the load, identify verified carriers with active operating authority and valid cargo insurance, compare lane pricing against historical rates, obtain a human booking decision, and eliminate duplicate booking risks.

The core operational problems addressed by FreightOps AI are specified in [02-problem-definition.md](docs/02-problem-definition.md).

## Core workflow

```
Customer text ──► Intake ──► Structured draft shipment ──► Deterministic validation
                                                                    │
                                                                    ▼
Human approval ◄── Explained recommendation ◄── Deterministic eligibility + rate scoring
      │
      ▼
Internal booking proposal (snapshot, single active proposal, no external tender)
```

- **Intake:** Ingests pasted text or REST API intake submissions (direct manual shipment entry `POST /shipments` and plain-text/JSON file uploads deferred to Post-MVP; `.eml` email parsing deferred to Future) (plain text and JSON file uploads deferred to Post-MVP; `.eml` email parsing deferred to Future). Raw text is preserved; missing fields remain `null`. Party foreign keys and stop address fields are nullable on initial draft to support partial intake (CRIT-01, DEF-01).
- **Consolidated Facilities:** A single `facilities` model represents both pickup and delivery locations, with `shipment_stops` acting as the authoritative sequence.
- **Validation Engine:** Evaluates complete shipment aggregates against deterministic business rules, emitting severity-gated issues (`critical`, `error`, `warning`, `info`) with versioned audit runs.
- **Eligibility Engine:** Applies 7 deterministic hard filters (equipment match, service region coverage, availability window, active carrier status, insurance validity, hazmat, temperature) with canonical exclusion codes.
- **Rate-Aware Scoring:** Ranks eligible candidates using active scoring weights and factual rate benchmarks recorded in `carrier_lane_rates` (CRIT-03 & DEF-04), eliminating model rate hallucinations.
- **Human Approval:** Mandatory broker decision gate. Approvers view score breakdowns, fact-grounded explanations, and validation warnings; they may approve the top-ranked recommendation, reject, or request changes (candidate override deferred to Post-MVP).
- **Booking Proposal:** Created atomically upon human approval. Enforces a single active proposal per shipment via a PostgreSQL partial unique index. If declined or cancelled, the shipment returns to `sourcing` (CRIT-04).

## Architectural pillars

| Concern | Architectural Design |
|---|---|
| Architecture Pattern | Modular monolith (`api` → `services` → `domain` → `infrastructure`) in FastAPI |
| Orchestration | Single bounded LangGraph state machine, 16 canonical nodes (Node 5: `normalize_requirements`), persistent PostgreSQL checkpointer |
| Human in the Loop | Native LangGraph `interrupt()`; paused state in PostgreSQL; event-driven resume upon human approval decision |
| Fallback Design | Drop-in deterministic Python state machine fallback designated as architectural contingency pattern (INC-05) |
| Consequential Guard | LLM has **zero tool-calling access and zero database access**; output strictly schema-validated |
| Database Model | PostgreSQL 16+ with 21 tables, JSONB requirements column, and trigger-enforced audit immutability |
| Idempotency | Mandatory `Idempotency-Key` headers with atomic `in_progress` locking and configurable 60s lease timeout |
| Reliability | Simplified scheduling (no Celery/Redis/APScheduler in MVP); approval decision endpoint resumes graph; startup recovery check |

See [04-system-architecture.md](docs/04-system-architecture.md) and [07-agent-workflow.md](docs/07-agent-workflow.md) for detailed contracts.

## Technology stack & runtime target

The target production and test runtime is **Python 3.12** (ADR-017). While the developer host environment currently has Python 3.14.5, planned dependencies will be verified against Python 3.12 during the Phase 1 adoption gate.

**Installed in Environment**

| Package | Installed Version | Role |
|---|---|---|
| Python | 3.14.5 (Host) | Developer environment runtime |
| FastAPI | 0.165.0 | Typed REST API framework |
| Starlette | 1.10.0 | ASGI toolkit |
| Uvicorn | 0.54.0 | ASGI server |
| Pydantic | 2.14.4 | Contract schemas and boundary validation |
| HTTPX | 0.28.1 | Async HTTP client and in-process test client |
| pytest | 9.2.0 | Unit and integration test runner |
| python-dotenv | 1.2.4 | Local 12-factor configuration |
| PyYAML | 6.0.4 | Configuration parsing |
| OpenTelemetry API | 1.45.2 | Vendor-neutral tracing and metrics hooks |

**Target Planned for Implementation (Target: Python 3.12)**
- Jinja2 (server-rendered broker approval UI)
- SQLAlchemy 2.x & Alembic (typed persistence, 21 tables, schema migrations)
- PostgreSQL 16+ & asyncpg / psycopg (database and driver)
- LangGraph & `langgraph-checkpoint-postgres` (durable state checkpoints)
- Docker & Docker Compose (reproducible application deployment)

**Explicitly Deferred from MVP**
- Celery / ARQ / Redis / APScheduler (simplified event-driven resume used instead)
- Transactional outbox table (`outbox_events`) and dispatcher
- Live carrier, TMS, load-board, EDI, or tracking integrations
- Vector databases (Pinecone / pgvector) and ML ranking algorithms

## Documentation catalog

| # | Document | Primary Scope |
|---|---|---|
| 01 | [01 Business understanding](docs/01-business-understanding.md) | Freight brokerage domain, parties, facilities, lifecycle, rates |
| 02 | [02 Problem definition](docs/02-problem-definition.md) | Ten operational problems mapped to architectural capabilities |
| 03 | [03 Requirements specification](docs/03-requirements-specification.md) | 156 functional requirements (95 MVP), single-tenant RBAC, **Appendix A Contracts** |
| 04 | [04 System architecture](docs/04-system-architecture.md) | Modular monolith structure, component catalog, verbatim cut line |
| 05 | [05 Component architecture](docs/05-component-architecture.md) | Component boundaries and authoritative LLM vs deterministic matrix |
| 06 | [06 Database design](docs/06-database-design.md) | Authoritative 21-table schema, constraints, ER diagrams, audit trigger |
| 07 | [07 Agent workflow](docs/07-agent-workflow.md) | 16 canonical nodes, LangGraph interrupt/resume, execution bounds |
| 08 | [08 Data flow](docs/08-data-flow.md) | Five end-to-end operational flows with trust boundaries |
| 09 | [09 API design](docs/09-api-design.md) | REST API endpoints, facilities, scoring configs, RFC 9457 errors |
| 10 | [10 Technology decisions](docs/10-technology-decisions.md) | Stack evaluation, Python 3.12 target, ADR-001 through ADR-020 |
| 11 | [11 Security and reliability](docs/11-security-and-reliability.md) | STRIDE threat model, audit immutability trigger, idempotency locking |
| 12 | [12 Evaluation strategy](docs/12-evaluation-strategy.md) | Test corpora `DS-01..DS-06`, deterministic vs model metrics, release gates |
| 13 | [13 Development roadmap](docs/13-development-roadmap.md) | Phases PH-0 through PH-6, requirement traceability, verbatim cut line |
| 14 | [14 Architecture review](docs/14-architecture-review.md) | Independent critical architecture assessment report |
| 15 | [15 Architecture revision log](docs/15-architecture-revision-log.md) | Comprehensive record of all Phase 1.6 and 1.7 architectural revisions |

Start with [docs/README.md](docs/README.md) for reading order, the source-of-truth hierarchy, and changelog.

## Implementation roadmap summary

| Phase | Milestone | Deliverable / Verification Gate |
|---|---|---|
| `PH-0` | Architecture Defect Correction & Contract Freeze | Approved Contract 2.2 documentation set |
| `PH-1` | Skeleton, Persistence, Auth, Seed | FastAPI + PostgreSQL (21 tables); local auth; synthetic seed |
| `PH-2` | Intake, Facilities, Validation | Paste intake; draft shipment; deterministic validation engine |
| `PH-3` | Carriers, Lane Rates, Eligibility | Carrier master data; `carrier_lane_rates`; hard filters |
| `PH-4` | Scoring, Approvals, Proposals | Active seeded scoring; broker approval; internal booking proposal |
| `PH-5` | Agent Orchestration, Gateway, UI | 16-node LangGraph workflow; persistent checkpoints; Jinja2 UI |
| `PH-6` | Hardening, Audit, Evaluation | DB immutability trigger; evaluation harness; Docker Compose |

## Change control and honesty commitments

- All data in the MVP is synthetic. No proprietary carrier rates or customer identities are utilized.
- Consequential decisions are never delegated to probabilistic models.
- Prior to the first code commit, `.venv/` must be added to `.gitignore`.
- Phase 1 explicitly excludes application code, package installations, and repository commits.

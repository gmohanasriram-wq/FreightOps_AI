# 10 — Technology Decisions

| Field | Value |
|---|---|
| Status | Approved (Phase 1.7.5 Architecture Remediation) |
| Contract version | 2.2 |
| Contract source | [Appendix A](./03-requirements-specification.md#appendix-a--canonical-contracts) |
| Depends on | All prior documents |
| Last updated | 2026-11-25 |
| Audience | Developer, reviewer |

## 1. Purpose

This document records the technology stack choices, evaluation criteria, and Architecture Decision Records (ADRs) for FreightOps AI.

Two honesty rules apply:

1. **No popularity arguments.** A technology is chosen because it solves a concrete problem for this project.
2. **Target runtime vs host environment clarity.** The target production and project runtime is **Python 3.12** (ADR-017). While the developer host machine currently has a Python 3.14.5 virtual environment, planned dependencies will be compatibility-tested against Python 3.12 at the Phase 1 adoption gate.

## 2. Decision framework

A technology is adopted only if it:

1. Solves a problem the MVP actually has.
2. Can be operated by one developer without dedicated distributed infrastructure.
3. Has a clear, low-complexity fallback if unavailable.
4. Does not delegate a consequential financial or operational decision to an unconstrained LLM.

## 3. Stack summary

Status values:
- **Installed** — present in current `.venv` (verified from package metadata).
- **Target Planned** — required for MVP, targeting Python 3.12; compatibility to be verified at Phase 1 adoption gate.
- **Deferred** — not in the MVP.

| Layer | Choice | Status | Why |
|---|---|---|---|
| Runtime Target | Python 3.12 | **Target Planned** | Mature library ecosystem (LangGraph, asyncpg, psycopg, SQLAlchemy); stable C-extensions |
| Web framework | FastAPI 0.165.0 | Installed | Typed request/response models, OpenAPI generation, dependency injection, async support |
| ASGI server | Uvicorn 0.54.0 | Installed | Minimal local ASGI server for FastAPI |
| Validation / schemas | Pydantic 2.14.4 | Installed | Unified schemas for API, configuration, workflow state, and LLM output parsing |
| HTTP client | HTTPX 0.28.1 | Installed | Async client for in-process API testing and outbound LLM calls |
| Configuration | python-dotenv 1.2.4, PyYAML 6.0.4 | Installed | Local 12-factor configuration without an external config server |
| Testing | pytest 9.2.0 | Installed | Standard test framework for unit, integration, and contract test suites |
| Observability API | OpenTelemetry API 1.45.2 | Installed | Vendor-neutral tracing/metrics hooks without requiring an external APM collector |
| UI Templates | Jinja2 | **Target Planned** | Lightweight server-rendered broker review screens without a Node.js frontend build pipeline |
| ORM & Migrations | SQLAlchemy 2.x, Alembic | **Target Planned** | Typed persistence, transaction boundaries, and reproducible versioned schema migrations |
| Database driver | asyncpg or psycopg (v3) | **Target Planned** | High-performance PostgreSQL async driver; evaluated at Phase 1 gate |
| Database | PostgreSQL 16+ | **Target Planned** | ACID transactions, JSONB document querying, partial unique indexes, trigger immutability |
| Workflow engine | LangGraph (+ checkpoint-postgres) | **Target Planned** | Bounded state machine, durable PostgreSQL checkpoints, native interrupt/resume |
| LLM Gateway | Provider-agnostic interface | Target Planned | Abstract interface; mock provider for deterministic tests; real provider optional |
| Task Queue / Scheduler | None (Deferred) | **Deferred** | Celery, ARQ, Redis, and APScheduler excluded from MVP (ADR-018) |
| Transactional Outbox | None (Deferred) | **Deferred** | Outbox table and background dispatcher deferred to Post-MVP (ADR-009) |
| Vector database | Pinecone / pgvector | **Deferred** | Deterministic eligibility rules do not require vector embeddings |
| Embeddings / ML | Sentence Transformers / scikit-learn | **Deferred** | Ranking uses versioned weighted heuristic; ML ranking deferred |
| Containerization | Docker, Docker Compose | **Target Planned** | Reproducible single-command local application and PostgreSQL deployment |

## 4. Technology evaluation

### 4.1 Python runtime (Target: Python 3.12)
- **Why:** High readability, robust data and AI ecosystem, first-class async support, and universal vendor SDK support.
- **Problem solved:** Single language across REST API, deterministic engines, workflow orchestration, tests, and evaluation harnesses.
- **Decision:** Target Python 3.12 (ADR-017). The host virtual environment currently runs Python 3.14.5; the project will establish a Python 3.12 runtime environment during Phase 1 setup.

### 4.2 FastAPI & Pydantic v2
- **Why:** Pydantic-native serialization, automatic OpenAPI documentation, async endpoints, and clean dependency injection.
- **Problem solved:** Strongly-typed HTTP API contracts with strict boundary validation and zero manual schema duplication.

### 4.3 PostgreSQL 16+
- **Why:** True ACID transactions, robust foreign key constraints, high-performance `jsonb` operations (eliminating brittle EAV schemas), partial unique indexes (guaranteeing at most one active proposal per shipment), and trigger-enforced table immutability.
- **Problem solved:** System of record integrity for freight contracts, financial rates, approvals, and immutable audit logs.

### 4.4 LangGraph
- **Why:** Provides explicit graph definition, typed state, native PostgreSQL checkpointing (`langgraph-checkpoint-postgres`), and first-class `interrupt()` semantics for human approvals.
- **Architectural Contingency Pattern (INC-05):** In the event that library wheel compatibility, serialization overhead, or PostgreSQL checkpointer defects arise during implementation, the architecture designates an internal ~200-line deterministic Python state machine as a documented contingency pattern. This pattern preserves all node signatures, schemas, and API contracts. It is strictly an architectural contingency design pattern, not an already-implemented or verified fallback.

### 4.5 LLM Gateway and Providers
- **Why:** Text-to-structure intake extraction and natural language explanation require text generation.
- **Decision:** Provider-agnostic gateway abstraction (`LLMGateway`) with a mock provider for zero-cost, deterministic testing. Live provider (e.g., Gemini 2.5 Flash) is evaluated during Phase 5.

## 5. Architecture Decision Records (ADRs)

### ADR-001 — Modular monolith architecture
- **Context:** Single-developer implementation; domain boundaries evolving; distributed overhead unjustified.
- **Decision:** Single deployable FastAPI application with strict internal layered architecture (`api` → `services` → `domain` → `infrastructure`).
- **Consequences:** Simplified transactions, single deployment artifact, easy local debugging.
- **Status:** Accepted.

### ADR-002 — FastAPI as HTTP framework
- **Context:** Need typed REST endpoints, OpenAPI docs, and async performance.
- **Decision:** FastAPI with Pydantic v2 schemas.
- **Status:** Accepted (Installed).

### ADR-003 — Server-rendered Jinja2 UI
- **Context:** Broker approval screens need fast implementation without JavaScript build pipelines.
- **Decision:** Server-rendered Jinja2 templates served directly by FastAPI.
- **Status:** Accepted (Target Planned).

### ADR-004 — PostgreSQL as system of record; SQLAlchemy 2.x + Alembic
- **Context:** Relational integrity, audit logs, and complex JSON querying required.
- **Decision:** PostgreSQL with 21 tables; SQLAlchemy 2.x ORM and Alembic migrations.
- **Status:** Accepted (Target Planned).

### ADR-005 — LangGraph for bounded workflow orchestration
- **Context:** Need durable checkpoints across multi-step recommendation and human-in-the-loop approval.
- **Decision:** Retain LangGraph with persistent PostgreSQL checkpointer (`AsyncPostgresSaver`) as the authoritative workflow engine. A pure Python state machine is retained strictly as an architectural contingency design pattern.
- **Status:** Accepted (Target Planned).

### ADR-006 — Provider-agnostic LLM gateway
- **Context:** Avoid vendor lock-in; enable offline deterministic testing.
- **Decision:** Define abstract gateway with mock provider; defer live vendor selection to Phase 5.
- **Status:** Accepted.

### ADR-007 — Deterministic eligibility and scoring; LLM not authoritative
- **Context:** Freight matching involves financial commitments and legal requirements.
- **Decision:** Eligibility hard filters and candidate scoring are 100% deterministic code. LLM never decides ranking or pricing.
- **Status:** Accepted.

### ADR-008 — Vector database deferred
- **Context:** Vector search is often added unnecessarily to AI projects.
- **Decision:** No Pinecone or vector database in MVP. Deterministic eligibility uses relational queries.
- **Status:** Accepted (Deferred).

### ADR-009 — Transactional outbox deferred from MVP schema
- **Context:** Previous drafts proposed an `outbox_events` table without a background dispatcher.
- **Decision:** Remove `outbox_events` from MVP database schema (F-DB-03). Proposal and approval mutations are committed atomically within local database transactions.
- **Status:** Accepted (Deferred to Post-MVP).

### ADR-010 — Append-only audit log with PostgreSQL trigger immutability
- **Context:** Regulatory traceability and non-repudiation of broker decisions.
- **Decision:** `audit_events` is insert-only, enforced by database-level trigger `prevent_audit_event_mutation()` and role privilege revocation.
- **Status:** Accepted.

### ADR-011 — Docker Compose deployment
- **Context:** Reproducible local development and demo evaluation.
- **Decision:** Single `docker-compose.yml` defining the FastAPI app and PostgreSQL service.
- **Status:** Accepted.

### ADR-012 — Concurrency-safe idempotency keys
- **Context:** Network retries and user double-clicks must not create duplicate proposals.
- **Decision:** Mandatory `Idempotency-Key` header with atomic `in_progress` locking in `idempotency_keys` table.
- **Status:** Accepted.

### ADR-013 — Synthetic operational data
- **Context:** Real freight and carrier data is proprietary.
- **Decision:** Fictional synthetic dataset seeded via migrations/scripts, clearly marked as synthetic.
- **Status:** Accepted.

### ADR-014 — Paste and REST intake; file upload and email ingestion deferred (INC-02)
- **Context:** Email ingestion (IMAP/webhooks) and complex MIME/file upload parsing introduce extensive operational overhead.
- **Decision:** MVP intake is restricted to raw text paste via UI and structured JSON via REST API (`POST /api/v1/intake/submissions`). Plain text and JSON file uploads are deferred to Post-MVP; `.eml` MIME parsing and email polling are deferred to Future.
- **Status:** Accepted.

### ADR-015 — Pydantic as universal contract layer
- **Context:** Schema validation needed at API boundaries, workflow state, and tool interfaces.
- **Decision:** Pydantic v2 models as authoritative schemas.
- **Status:** Accepted (Installed).

### ADR-016 — pytest + HTTPX test strategy
- **Context:** Comprehensive testing required without external network calls.
- **Decision:** Unit tests for deterministic engines, HTTPX in-process tests for API/workflows, contract tests for schemas.
- **Status:** Accepted (Installed).

### ADR-017 — Target Python 3.12 runtime (ADR Decision 1)
- **Context:** The developer machine currently has Python 3.14.5, which is too new for stable C-extensions and library wheels (e.g., asyncpg, psycopg, torch).
- **Decision:** Target Python 3.12 for production and testing. Planned libraries will be verified against Python 3.12 during the Phase 1 adoption gate. The existing virtual environment is not altered during documentation.
- **Status:** Accepted.

### ADR-018 — Simplified event-driven workflow execution & crash recovery (ADR Decision 5 & DEF-05)
- **Context:** Celery, ARQ, Redis, and APScheduler introduce operational overhead unjustified for a single-developer MVP.
- **Decision:** Exclude external task queues and cron schedulers from the MVP. The human approval decision endpoint (`POST /api/v1/approvals/{id}/decision`) is the authoritative event that commits the decision in PostgreSQL, acquires an execution row lock (`SELECT ... FOR UPDATE` on `workflow_executions`), and resumes the paused workflow execution via `graph.invoke(Command(resume=decision))`. Durability across process restarts is guaranteed by PostgreSQL checkpoint persistence and a bounded startup recovery check (which resumes stranded decided approvals and never expires pending human approvals). Automatic TTL sweeps are deferred. In-progress idempotency keys feature a configurable 60-second recovery lease timeout.
- **Status:** Accepted.

### ADR-019 — Consolidated Facilities entity model (ADR Decision 3)
- **Context:** Separate `shippers` and `consignees` tables duplicated schema and prevented facilities from acting as both pickup and delivery locations.
- **Decision:** Consolidate into a single `facilities` table. `shipment_stops` remains the authoritative representation of pickup and delivery stops.
- **Status:** Accepted.

### ADR-020 — JSONB shipment requirements model (F-DB-02)
- **Context:** The EAV `shipment_requirements` table added schema complexity, query joins, and weak typing without business benefit.
- **Decision:** Store special equipment and cargo requirements directly on `shipments.requirements` as a `jsonb` document.
- **Status:** Accepted.

## 6. Python 3.12 dependency-adoption gate (Phase 1)

Before committing planned dependencies to `pyproject.toml` or `requirements.txt`:
1. Verify `pip install`, module import, and minimal smoke tests against a clean Python 3.12 environment.
2. If any planned package exhibits compatibility issues, activate the documented fallback (e.g., pure Python state machine if LangGraph fails).
3. No dependencies are installed during Phase 1 documentation.

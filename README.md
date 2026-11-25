# FreightOps AI

**An AI-assisted freight brokerage operations platform — working MVP.**

FreightOps AI turns an unstructured customer freight request into a validated shipment, a deterministic carrier recommendation with explainable scoring, an authorized human approval, and an internal booking proposal. Every consequential financial, legal, and operational decision stays inside deterministic Python code or an authorized human's hands. A language model is used only to narrate an explanation that has already been computed from verified facts; it never selects carriers, chooses tools, or changes the workflow.

> **Status: implemented MVP.** The FastAPI application, PostgreSQL schema, deterministic engines, bounded LangGraph workflow, REST API, Jinja2 + HTMX interface, seed data, tests, and demo tooling in this repository all run. The system is a portfolio-grade single-tenant demonstration, not a production deployment.

## The business problem

Freight brokers receive high volumes of unformatted requests by email, text, and customer portal. Requests frequently lack pickup windows, weight, temperature, or equipment details. Brokers must qualify the load, identify carriers with active authority and valid insurance, compare lane pricing against recorded rates, obtain a human booking decision, and avoid duplicate bookings.

FreightOps AI implements that operating loop without inventing any shipment fact, carrier performance claim, or price.

## Core workflow

```
Customer text ──► Intake ──► Draft shipment ──► Deterministic validation
                                                        │
                                                        ▼
Broker approval ◄── Explained recommendation ◄── Eligibility + rate scoring
      │
      ▼
Internal booking proposal (immutable snapshot, one active proposal per shipment)
```

1. **Intake** persists the raw text and creates a draft shipment. Missing fields stay `null`; nothing is invented. If the LLM is unavailable or demo mode is on, the original submission is preserved and the draft is created without fabricated values.
2. **Validation** runs deterministic, versioned rules and records every run and issue.
3. **Carrier discovery and eligibility** apply seven hard filters with canonical exclusion codes: equipment match, service region, availability window, active status, insurance validity, hazmat capability, and temperature capability. Every carrier in the universe is evaluated and persisted; there is no pre-filtering and no safety-rating filter.
4. **Rate-aware scoring** uses the active scoring configuration and recorded lane rates. Four components are active — equipment fit, capacity/timing, rate competitiveness, and data completeness. Lane familiarity and reliability are deferred: they are stored and returned as `null`, never fabricated or coerced to zero. Scores use `Decimal` arithmetic quantized to four places with `ROUND_HALF_UP`.
5. **Ranking** ranks every rankable candidate, not only the top five. Eligibility is kept separate from rankability: an eligible carrier without a usable rate is eligible but unrankable, and the workflow reports `no_rankable_candidates` rather than substituting a different rate.
6. **Explanation** is generated deterministically from verified facts. Optional LLM narration paraphrases that template only.
7. **Human approval** is a mandatory broker decision: approve, reject, or request changes. The LangGraph workflow pauses at `request_human_approval` and resumes after the decision is durably recorded.
8. **Booking proposal** is created only for an approved decision, using the approved candidate, and freezes the shipment. The schema enforces one active proposal per shipment.
9. **Audit** — every consequential action writes an append-only `audit_events` row; a PostgreSQL trigger rejects `UPDATE` and `DELETE`.

## Architecture

| Concern | Implementation |
|---|---|
| Architecture pattern | Modular monolith (`api → services → domain → infrastructure`) on FastAPI |
| Database | PostgreSQL 16+, SQLAlchemy 2.x, Alembic; 21 tables |
| Orchestration | Real `langgraph.graph.StateGraph` with 16 canonical nodes, one `interrupt()`, conditional error routing to a terminal failure sink |
| Durable projection | Workflow state, counters, errors, approvals, recommendations, proposals, and audit events in PostgreSQL; `MemorySaver` holds only in-process resume state |
| Bounds | 40 node executions, 6 LLM calls, 900 compute seconds, 3 attempts, 60-second lease |
| Determinism | Eligibility, rate selection, scoring, ranking, explanation template, and transitions are pure deterministic code |
| LLM guard | No tool-calling and no database access; narration is optional and fact-constrained; demo mode makes no network call |
| Interface | Server-rendered Jinja2 templates with HTMX 1.9.12 and Tailwind CDN |
| Security | Single-tenant RBAC (`viewer` < `broker` < `admin`), server-side sessions, CSRF for cookie-authenticated mutations, mandatory `Idempotency-Key` on workflow and approval mutations, RFC 9457 problem details |

### Technology versions

Python **3.12**, FastAPI 0.165.0, Starlette 1.10.0, SQLAlchemy 2.1.9, Alembic 1.20.1, psycopg 3.3.9, Pydantic 2.14.4, Jinja2 3.1.6, LangGraph 0.6.11, langgraph-checkpoint 3.0.1, langchain-core 1.8.4, pytest 9.2.0.

## Getting started

### Prerequisites

- Python 3.12 (the verified interpreter is `.venv-py312/Scripts/python.exe`)
- PostgreSQL 16+ — either Docker, the bundled local-cluster script, or your own server

### 1. Create the environment and install dependencies

```powershell
python -m venv .venv-py312
.venv-py312\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env   # then set POSTGRES_* values
```

Never commit `.env`. It is ignored by Git.

### 2. Start PostgreSQL

Option A — Docker:

```powershell
docker compose up -d db
```

Option B — portable local cluster (Windows, no Docker or admin rights):

```powershell
.venv-py312\Scripts\python.exe scripts\setup_postgres.py
```

### 3. Create the schema

```powershell
.venv-py312\Scripts\python.exe -m alembic upgrade head
```

### 4. Seed synthetic demo data

```powershell
.venv-py312\Scripts\python.exe scripts\seed_demo.py
```

This creates 16 synthetic carriers, 4 demo shipments (`DEMO-READY-1001`, `DEMO-INELIGIBLE-1002`, `DEMO-UNRANKABLE-1003`, `DEMO-COMBO-1004`), and the active scoring configuration. Every record is labeled synthetic. Seeding is idempotent and never touches user-created shipments.

### 5. Run the application

```powershell
.venv-py312\Scripts\python.exe run_backend.py
```

- Application: <http://127.0.0.1:8000>
- Health dashboard: <http://127.0.0.1:8000/>
- Shipments: <http://127.0.0.1:8000/shipments>
- Approval queue: <http://127.0.0.1:8000/approvals>
- OpenAPI docs: <http://127.0.0.1:8000/docs>

Optional demo logins (used only when all three roles have credentials in `.env`):

```dotenv
DEMO_ADMIN_EMAIL=...
DEMO_ADMIN_PASSWORD=...
DEMO_BROKER_EMAIL=...
DEMO_BROKER_PASSWORD=...
DEMO_VIEWER_EMAIL=...
DEMO_VIEWER_PASSWORD=...
```

The browser UI also works without login for local demonstration: approval decisions fall back to the seeded demo broker. The API never does this and always requires an authenticated session.

## Demo walkthrough

### One-command deterministic walkthrough

```powershell
.venv-py312\Scripts\python.exe scripts\demo_walkthrough.py
```

The script runs the real application in-process and prints every step: seed summary, health, shipment page, recommendation trigger, workflow snapshot, ranked scorecard, approval queue, human approval, completed execution, booking proposal, shipment status, audit count, and the rendered scorecard page. It uses the default offline LLM provider and makes no external network call.

### Browser walkthrough

1. Open `/shipments` and choose **DEMO-READY-1001** (Chicago, IL → Dallas, TX).
2. In the **Carrier Recommendation** panel, click **Run Recommendation Workflow**. The workflow validates, evaluates all 16 synthetic carriers, scores and ranks the rankable ones, and pauses for human approval.
3. Click **Open score breakdown & exclusions** (or **Human approval required**). Review the verified explanation, ranked candidates and component scores, eligible-but-unrankable carriers, excluded carriers with reason codes, and the workflow trace.
4. Under **Human Broker Review**, optionally add a comment and click **Approve & create booking proposal**.
5. The shipment becomes `booking_proposed` and frozen; a booking proposal exists; the workflow is `completed` with outcome `approved`. `/approvals` shows the decision history.
6. Repeat with **DEMO-INELIGIBLE-1002** to see `no_eligible_carriers` (no seeded carrier has flatbed equipment) and **DEMO-UNRANKABLE-1003** to see `no_rankable_candidates` (eligible carriers, no maximum buy ceiling).

The demo is deterministic: identical facts produce identical eligibility decisions, rates, component scores, ranks, and explanation text.

## API summary

All routes below are under `/api/v1`.

| Method | Path | Access |
|---|---|---|
| GET | `/health` | public |
| POST | `/auth/login`, GET `/auth/me`, POST `/auth/logout` | session / CSRF |
| GET | `/carriers`, `/carriers/{id}` | viewer+ |
| POST | `/intake/submissions`, GET `/intake/submissions/{id}` | broker+ / viewer+ |
| GET | `/shipments`, `/shipments/{id}`, PATCH `/shipments/{id}` | viewer+ / broker+ |
| POST | `/shipments/{id}/validation`, GET `/shipments/{id}/validation` | broker+ / viewer+ |
| POST | `/shipments/{id}/recommendations` | broker/admin |
| GET | `/shipments/{id}/recommendations`, `/recommendations/{id}` | viewer+ |
| GET | `/approvals`, `/approvals/{id}` | viewer+ |
| POST | `/approvals/{id}/decision` | broker/admin |
| GET | `/workflows/{workflow_execution_id}` | viewer+ |

Mutations require a session-bound `X-CSRF-Token` when the request is cookie-authenticated. Recommendation triggers and approval decisions additionally require an `Idempotency-Key` header (missing → 422 `ERR-001`). The workflow runs synchronously in the request, so the `202` response reports the durable execution status at return time (`waiting_for_human` or `completed`), not a fabricated `queued`.

```powershell
# login, then use the returned csrf_token and session cookie
curl -c cookies.txt -X POST http://127.0.0.1:8000/api/v1/auth/login `
  -H "Content-Type: application/json" `
  -d '{"email":"broker@example.com","password":"..."}'

curl -b cookies.txt -X POST `
  "http://127.0.0.1:8000/api/v1/shipments/<shipment-id>/recommendations" `
  -H "Content-Type: application/json" -H "X-CSRF-Token: <csrf_token>" `
  -H "Idempotency-Key: demo-0001" -d '{}'
```

## Testing

```powershell
# full suite
.venv-py312\Scripts\python.exe -m pytest -q

# suite with coverage
.venv-py312\Scripts\python.exe -m pytest -q --cov=backend.app --cov-report=term
```

- 190 tests pass.
- Total measured line coverage: 88% of `backend.app`.
- Tests use the configured PostgreSQL database. They create isolated shipment copies with fresh UUIDs and never delete or mutate existing user data.
- Coverage areas include schema and migrations, authentication, CSRF, pagination, intake, validation, carriers, eligibility, rate selection, scoring/ranking, workflow pause and resume paths, approval decisions, API/UI integration, determinism, audit-chain completeness, and database-level audit immutability.

## Repository layout

```
backend/app/
  api/v1/          REST routers (auth, carriers, intake, shipments, recommendations, approvals, workflows)
  core/            configuration, auth/RBAC/CSRF, security, RFC 9457 errors
  db/              engine, session factory, health check
  domain/          eligibility, rate selection, and scoring engines (pure deterministic code)
  models/          SQLAlchemy models for the 21-table schema
  schemas/         Pydantic request/response contracts
  services/        intake, validation, recommendations, approvals, idempotency, audit, LLM gateway, demo seed
  workflows/       LangGraph state, runtime, 16 nodes, graph, workflow service
  templates/       Jinja2 pages and HTMX partials
  ui/              server-rendered UI router
backend/alembic/   migrations (head: 4b1f7c9d2e30)
backend/tests/     automated test suite
scripts/           demo seed, PostgreSQL bootstrap, deterministic walkthrough
docs/              authoritative architecture and design documents
```

## Known limitations

- The LangGraph checkpointer is process-local (`MemorySaver`). An interrupted graph cannot resume after a process restart; the approval decision, audit records, and workflow projection are durable, so the failure is visible and auditable rather than silently lost.
- The workflow executes synchronously inside the HTTP request. There is no background worker, queue, or outbox.
- Lane familiarity and reliability scoring components are deferred until genuine data sources exist. They remain `null`.
- Carrier, rate, insurance, availability, and customer records are synthetic. No live carrier, TMS, load-board, EDI, or tracking integration exists.
- No direct manual shipment creation endpoint and no `.eml` parsing; those are documented as deferred.
- Single-tenant local authentication with in-memory sessions; sessions do not survive a process restart.
- Rate provenance/as-of dates are not persisted in the current schema.
- Top-N is a presentation setting; all rankable candidates are always ranked and persisted.

## Documentation

| # | Document | Scope |
|---|---|---|
| 01 | [Business understanding](docs/01-business-understanding.md) | Domain, parties, facilities, lifecycle, rates |
| 02 | [Problem definition](docs/02-problem-definition.md) | Ten operational problems |
| 03 | [Requirements specification](docs/03-requirements-specification.md) | Functional requirements, RBAC, Appendix A contracts |
| 04 | [System architecture](docs/04-system-architecture.md) | Modular monolith, components, cut line |
| 05 | [Component architecture](docs/05-component-architecture.md) | LLM vs deterministic responsibility matrix |
| 06 | [Database design](docs/06-database-design.md) | 21-table schema, constraints, audit trigger |
| 07 | [Agent workflow](docs/07-agent-workflow.md) | 16 nodes, interrupt/resume, execution bounds |
| 08 | [Data flow](docs/08-data-flow.md) | End-to-end operational flows |
| 09 | [API design](docs/09-api-design.md) | Endpoints, facilities, errors |
| 10 | [Technology decisions](docs/10-technology-decisions.md) | Stack evaluation, ADRs |
| 11 | [Security and reliability](docs/11-security-and-reliability.md) | Threat model, audit immutability, idempotency |
| 12 | [Evaluation strategy](docs/12-evaluation-strategy.md) | Test corpora, release gates |
| 13 | [Development roadmap](docs/13-development-roadmap.md) | Phases PH-0 … PH-6 |
| 14 | [Architecture review](docs/14-architecture-review.md) | Independent assessment (protected; unchanged) |
| 15 | [Architecture revision log](docs/15-architecture-revision-log.md) | Revision history |
| 16 | [Lead developer decisions](docs/16-lead-developer-decision-record.md) | Implementation decisions and milestone records |

All data in this repository is synthetic. No proprietary rates, real carrier identities, or customer data are included.

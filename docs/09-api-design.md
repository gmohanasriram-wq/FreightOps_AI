# 09 — API Design

| Field | Value |
|---|---|
| Status | Approved (Phase 1.7.5 Architecture Remediation) |
| Contract version | 2.2 |
| Contract source | [Appendix A](./03-requirements-specification.md#appendix-a--canonical-contracts) |
| Depends on | [03](./03-requirements-specification.md), [06](./06-database-design.md), [07](./07-agent-workflow.md) |
| Last updated | 2026-11-25 |
| Audience | Developer, reviewer, API consumer |

## 1. Purpose

This document specifies the REST API contract for FreightOps AI. It defines resource paths, HTTP methods, request and response schemas, Pydantic validation rules, standard error structures, and concurrency/idempotency controls.

FastAPI generates OpenAPI schemas from code models at runtime; this document serves as the human-readable architectural authority. All paths defined here are canonical.

## 2. Global conventions

| Concern | Standard |
|---|---|
| Base path | `/api/v1` |
| Content type | `application/json` (errors: `application/problem+json`) |
| Field naming | `snake_case` in JSON payloads and query parameters |
| Path segments | kebab-case (e.g., `/booking-proposals`, `/scoring-configs`) |
| Identifiers | Standard UUIDv4 strings |
| Timestamps | ISO-8601 UTC with trailing `Z` (e.g., `2026-11-22T10:00:00Z`) |
| Currency & Rates | Numeric decimal with associated currency code (default: `"USD"`) |
| Pagination | Query params `limit` (default 50, max 200) and `offset`; responses return `{items, total, limit, offset}` |
| Sorting | Query param `sort` (e.g., `created_at`, `-created_at` for descending) |
| Idempotency | `Idempotency-Key` header on state-changing `POST` requests |
| Concurrency | `If-Match: "<version>"` header on resource updates *(Post-MVP — FR-023)* |

## 3. Authentication and role-based access control (RBAC)

- Authentication (MVP): Authenticated session cookie (`HttpOnly`, `Secure`, `SameSite=Lax`) with CSRF token protection on all state-changing requests (`POST`, `PATCH`, `PUT`, `DELETE`). Bearer token authentication (`Authorization: Bearer <token>`) is **Post-MVP** (`FR-252`).
- Scoping: Single-tenant deployment model. Object access is governed by user role permissions, not multi-tenant organizational boundaries (F-SEC-01).
- Canonical Roles: `admin`, `broker`, `viewer`.

| Endpoint Group | `viewer` | `broker` | `admin` |
|---|---|---|---|
| Health (`/health` MVP; `/meta/enums` Post-MVP — FR-284) | Read | Read | Read |
| Intake (`/intake/submissions`) | Read | Read / Write | Read / Write |
| Facilities (`/facilities`) | Read | Read / Write | Read / Write |
| Shipments & Validation (`/shipments`) | Read | Read / Write | Read / Write |
| Recommendations (`/recommendations`) | Read | Read / Write | Read / Write |
| Scoring Configurations (`/scoring-configs`) *(Post-MVP — FR-280/281/285)* | Read | Read | Read / Write / Activate |
| Approvals (`/approvals`) | Read | Read / Decide | Read / Decide |
| Booking Proposals (`/booking-proposals/{id}`, `/cancel` MVP; `POST` internal Node 13; list Post-MVP) | Read | Read / Write / Cancel | Read / Write / Cancel |
| Carriers & Rates (`/carriers/{id}/lane-rates` MVP; `/carriers` CRUD Post-MVP — FR-060/068) | Read | Read / Write | Read / Write |
| Workflows (`/workflows`) | Read | Read / Cancel | Read / Cancel |
| Audit Events (`/audit-events`) *(Post-MVP — FR-223)* | Read | Read | Read |

## 4. Standard error format (RFC 9457)

All errors return `application/problem+json`:

```json
{
  "type": "https://freightops.invalid/problems/validation-failed",
  "title": "Validation Failed",
  "status": 422,
  "detail": "One or more shipment fields failed business validation.",
  "instance": "/api/v1/shipments/8e6c4391-4cf5-4e08-9df2-43bb22272e12/validation",
  "code": "ERR-001",
  "trace_id": "9f1c7d2e-4b6a-4d1e-8a2b-3c4d5e6f7a8b",
  "errors": [
    {
      "field": "destination_facility_id",
      "message": "Destination facility is required before validation can pass."
    }
  ]
}
```

### 4.1 Canonical error catalog

| Code | HTTP | Meaning | Typical cause |
|---|---|---|---|
| `ERR-001` | 422 | Validation failed | Malformed body, invalid enum, or business rule failure |
| `ERR-002` | 401 | Unauthenticated | Missing, expired, or malformed credentials |
| `ERR-003` | 403 | Forbidden | User role lacks sufficient permissions |
| `ERR-004` | 404 | Not found | Requested resource identifier does not exist |
| `ERR-005` | 409 | Conflict | Concurrency collision, frozen entity modification, or invalid status transition |
| `ERR-006` | 409 | Duplicate or in-flight request | Idempotency key already in-flight or reused with differing body |
| `ERR-007` | 422 | Unprocessable intake | Empty text or unsupported intake format |
| `ERR-008` | 415 | Unsupported media type | Unsupported upload file extension or MIME type |
| `ERR-009` | 413 | Payload too large | Upload payload exceeds 100 kB limit |
| `ERR-010` | 429 | Rate limited | Request velocity limit exceeded |
| `ERR-011` | 503 | Service unavailable | Database or external service connectivity failure |
| `ERR-012` | 422 | Workflow budget exceeded | Node budget (40) or LLM call budget (6) reached |
| `ERR-013` | 409 | Invalid approval | Approval not in pending status or already decided |
| `ERR-014` | 409 | Stale recommendation | Recommendation superseded by newer generation |
| `ERR-015` | 500 | Internal server error | Unhandled system exception |

## 5. Endpoint catalog

### 5.1 Intake

*Scope Boundary (INC-02):* In MVP, intake supports pasted unstructured text via UI and structured JSON via REST API (`POST /api/v1/intake/submissions`). Plain text and JSON file uploads are deferred to Post-MVP; `.eml` MIME email parsing and email integrations are deferred to Future.

#### `POST /api/v1/intake/submissions`
- **Purpose:** Accept unstructured text via paste or structured JSON payload; persist submission and create linked draft Shipment.
- **Roles:** `broker`, `admin`.
- **Headers:** `Idempotency-Key` (required).
- **Request Body:**
  ```json
  {
    "channel": "paste",
    "raw_text": "Need reefer pickup in Chicago IL on Monday 11/24, delivery Dallas TX Wednesday 11/26. 42000 lbs frozen poultry, 34-38F.",
    "customer_id": null,
    "client_request_id": "CUST-REF-9021"
  }
  ```
- **Response `201 Created`:**
  ```json
  {
    "submission_id": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "channel": "paste",
    "content_hash": "sha256:7f83b1657ff1fc53b92dc18148a1d65dfc2d4b1fa3d677284addd200126d9069",
    "shipment_id": "8e6c4391-4cf5-4e08-9df2-43bb22272e12",
    "received_at": "2026-11-22T10:00:00Z",
    "parse_metadata": {
      "model": "gemini-2.5-flash",
      "extracted_fields": ["origin", "destination", "dates", "weight", "equipment", "temperature"]
    }
  }
  ```
- **Errors:** `ERR-001`, `ERR-002`, `ERR-003`, `ERR-006`, `ERR-007`, `ERR-009`.

#### `GET /api/v1/intake/submissions/{submission_id}`
- **Purpose:** Retrieve raw submission text, extraction metadata, and linked shipment ID.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** Full submission object with `raw_text`, `parse_metadata`, and `extraction_error`.

---

### 5.2 Facilities (Consolidated Shippers and Consignees)

#### `POST /api/v1/facilities`
- **Purpose:** Create a facility (pickup location, delivery location, or combined facility).
- **Roles:** `broker`, `admin`.
- **Request Body:**
  ```json
  {
    "name": "Chicago Cold Storage Logistics Center",
    "code": "ORD-CS-01",
    "facility_type": "cold_storage",
    "address_line1": "100 Logistics Blvd",
    "address_line2": "Dock Bay 4",
    "city": "Chicago",
    "state": "IL",
    "postal_code": "60601",
    "country": "US",
    "timezone": "America/Chicago",
    "appointment_required": true,
    "operating_hours": "Mon-Fri 06:00-18:00 CT"
  }
  ```
- **Response `201 Created`:** Facility object with generated `id`, timestamps, and `is_active: true`.
- **Errors:** `ERR-001`, `ERR-002`, `ERR-003`, `ERR-005` (code collision).

#### `GET /api/v1/facilities`
- **Purpose:** Search and filter facilities.
- **Roles:** `viewer`, `broker`, `admin`.
- **Query Params:** `q`, `city`, `state`, `facility_type`, `is_active`, `limit`, `offset`, `sort`.
- **Response `200 OK`:** Paginated facility list `{items, total, limit, offset}`.

#### `GET /api/v1/facilities/{facility_id}`
- **Purpose:** Retrieve facility details.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** Facility aggregate.

#### `PATCH /api/v1/facilities/{facility_id}`
- **Purpose:** Update facility details (hours, appointment requirements, contact information).
- **Roles:** `broker`, `admin`.
- **Request Body:** Partial facility fields.
- **Response `200 OK`:** Updated facility object.

---

### 5.3 Shipments

#### `POST /api/v1/shipments` *(Post-MVP — FR-004)*

> **MVP Note:** In MVP, shipments are created via `POST /api/v1/intake/submissions` (FR-001/FR-002). Direct manual shipment creation via `POST /api/v1/shipments` is deferred to Post-MVP (`FR-004`).
- **Purpose:** Create a manual shipment record.
- **Roles:** `broker`, `admin`.
- **Headers:** `Idempotency-Key` (recommended).
- **Request Body:**
  ```json
  {
    "customer_id": "optional-uuid",
    "origin_facility_id": "optional-uuid",
    "destination_facility_id": "optional-uuid",
    "reference_number": "PO-99120",
    "equipment_type": "reefer",
    "commodity": "Frozen Poultry",
    "weight_lbs": 42000,
    "target_sell_rate": 2400.00,
    "max_buy_rate": 2100.00,
    "currency": "USD",
    "requirements": {
      "temperature_range": {"min_f": 34, "max_f": 38},
      "hazmat": false,
      "appointment": true,
      "notes": "24 pallets"
    },
    "stops": [
      {
        "sequence": 1,
        "stop_type": "pickup",
        "facility_id": "optional-uuid",
        "city": "Chicago",
        "state": "IL",
        "window_start": "2026-11-24T08:00:00Z",
        "window_end": "2026-11-24T12:00:00Z",
        "appointment_required": true
      },
      {
        "sequence": 2,
        "stop_type": "delivery",
        "facility_id": "optional-uuid",
        "city": "Dallas",
        "state": "TX",
        "window_start": "2026-11-26T08:00:00Z",
        "window_end": "2026-11-26T17:00:00Z",
        "appointment_required": false
      }
    ]
  }
  ```
  *Draft Tolerance & Gating (CRIT-01 & DEF-01 resolution):* In draft status (`status: "draft"` or `"intake_received"`), party references (`customer_id`, `origin_facility_id`, `destination_facility_id`, stop `facility_id`) as well as stop address fields (`name`, `address_line1`, `city`, `state`, `postal_code`) are nullable to allow raw draft creation from incomplete intake text. However, the deterministic `ValidationEngine` strictly enforces complete facility/address data and stop sequencing before the shipment can transition to `validated`. Approvals are hard-blocked while any stop address is incomplete.
- **Response `201 Created`:** Created shipment object (`status: "draft"`, `version: 1`).
- **Errors:** `ERR-001`, `ERR-002`, `ERR-003`, `ERR-006`.

#### `GET /api/v1/shipments`
- **Purpose:** List and filter shipments.
- **Roles:** `viewer`, `broker`, `admin`.
- **Query Params:** `status`, `customer_id`, `origin_region`, `destination_region`, `equipment_type`, `created_from`, `created_to`, `limit`, `offset`, `sort`.
- **Response `200 OK`:** Paginated `{items, total, limit, offset}`.

#### `GET /api/v1/shipments/{shipment_id}`
- **Purpose:** Retrieve shipment aggregate with stops, requirements JSONB, and current status.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** Full shipment record.

#### `PATCH /api/v1/shipments/{shipment_id}`
- **Purpose:** Update mutable shipment fields before approval.
- **Roles:** `broker`, `admin`.
- **Headers:** `If-Match: "<version>"` *(Post-MVP — FR-023)*.
- **Response `200 OK`:** Updated shipment record with incremented version.
- **Errors:** `ERR-001`, `ERR-004`, `ERR-005` (concurrency mismatch or shipment frozen).

#### `POST /api/v1/shipments/{shipment_id}/validation`
- **Purpose:** Execute deterministic validation rules on the shipment aggregate.
- **Roles:** `broker`, `admin`.
- **Response `200 OK`:**
  ```json
  {
    "validation_run_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "shipment_id": "8e6c4391-4cf5-4e08-9df2-43bb22272e12",
    "rules_version": "2026.1",
    "result": "passed",
    "checked_at": "2026-11-22T10:05:00Z",
    "issues": []
  }
  ```
  *(Returns `result: "failed"` with populated `issues` array if party references are missing, weight is invalid, or dates are in conflict).*
- **Errors:** `ERR-002`, `ERR-004`, `ERR-005`.

#### `GET /api/v1/shipments/{shipment_id}/validation`
- **Purpose:** Retrieve the most recent validation run and history.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** Validation run aggregate with `validation_run_id`, `rules_version`, and `issues`.

---

### 5.4 Scoring Configurations (F-API-01) *(Post-MVP — FR-280, FR-281, FR-285)*

> **MVP Note:** MVP uses the single seeded active row in `scoring_configurations`. Scoring configuration management endpoints below are deferred to Post-MVP.

#### `GET /api/v1/scoring-configs` *(Post-MVP)*
- **Purpose:** List all scoring configurations and identify the active version.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** List of scoring config objects (`id`, `name`, `version`, `is_active`, weights).

#### `POST /api/v1/scoring-configs` *(Post-MVP)*
- **Purpose:** Create a new version of scoring configuration weights.
- **Roles:** `admin`.
- **Request Body:**
  ```json
  {
    "name": "Margin-First Autumn 2026",
    "weight_equipment_fit": 0.20,
    "weight_lane_familiarity": 0.20,
    "weight_capacity_timing": 0.15,
    "weight_rate_competitiveness": 0.25,
    "weight_reliability": 0.15,
    "weight_data_completeness": 0.05
  }
  ```
  *Validation Rule:* Weights must strictly sum to `1.000` (tolerance `0.001`). Newly created configs are `is_active: false` until explicitly activated.
- **Response `201 Created`:** Created configuration record.
- **Errors:** `ERR-001`, `ERR-003`.

#### `GET /api/v1/scoring-configs/{config_id}` *(Post-MVP)*
- **Purpose:** Retrieve details of a specific scoring configuration.
- **Roles:** `viewer`, `broker`, `admin`.

#### `POST /api/v1/scoring-configs/{config_id}/activate` *(Post-MVP)*
- **Purpose:** Atomically activate a configuration version (setting prior active config to `is_active = false`).
- **Roles:** `admin`.
- **Response `200 OK`:** Activated configuration object.
- **Errors:** `ERR-003`, `ERR-004`.

---

### 5.5 Recommendations

#### `POST /api/v1/shipments/{shipment_id}/recommendations`
- **Purpose:** Trigger the carrier recommendation workflow for a validated shipment.
- **Roles:** `broker`, `admin`.
- **Headers:** `Idempotency-Key` (required).
- **Request Body:**
  ```json
  {
    "scoring_config_id": null,
    "top_n": 5
  }
  ```
- **Response `202 Accepted`:**
  ```json
  {
    "workflow_execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "shipment_id": "8e6c4391-4cf5-4e08-9df2-43bb22272e12",
    "status": "queued"
  }
  ```
- **Errors:** `ERR-001`, `ERR-004`, `ERR-005`, `ERR-006`.

#### `GET /api/v1/shipments/{shipment_id}/recommendations`
- **Purpose:** List recommendations generated for a shipment.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** List of recommendation summaries.

#### `GET /api/v1/recommendations/{recommendation_id}`
- **Purpose:** Retrieve full recommendation detail, candidate ranking, component scores, and explanation.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:**
  ```json
  {
    "recommendation_id": "550e8400-e29b-41d4-a716-446655440000",
    "shipment_id": "8e6c4391-4cf5-4e08-9df2-43bb22272e12",
    "status": "ready",
    "scoring_config_version": 2,
    "explanation": {
      "template": "Rank 1: Apex Freight chosen for verified reefer capacity and favorable rate competitiveness.",
      "narration": "Apex Freight is recommended as primary carrier due to 98% on-time reliability and historical lane rate of $2,050.",
      "provider": "gemini-2.5-flash"
    },
    "candidates": [
      {
        "carrier_id": "11111111-2222-3333-4444-555555555555",
        "carrier_name": "Apex Freight LLC",
        "rank": 1,
        "eligibility_status": "eligible",
        "composite_score": 0.885,
        "component_scores": {
          "equipment_fit": 1.0,
          "lane_familiarity": 0.90,
          "capacity_timing": 0.85,
          "rate_competitiveness": 0.88,
          "reliability": 0.98,
          "data_completeness": 0.90
        },
        "lane_rate_used": 2050.00
      }
    ],
    "ineligible_candidates": []
  }
  ```

**Lifecycle and nullability (D-024, D-033 Option A):**
- `status` may be `ready`, `no_eligible_carriers`, or `no_rankable_candidates` for completed generation. `ready` requires at least one ranked candidate.
- `candidates` contains every eligible candidate. Ranked candidates carry non-null `rank` and `composite_score`. Eligible-unrankable candidates remain in `candidates` with `rank = null`, `composite_score = null`, `lane_rate_used = null`, and `component_scores.rate_competitiveness = null`; they are excluded from ranked top-N views and are never placed in `ineligible_candidates`.
- `ineligible_candidates` contains only `ineligible` and `insufficient_data` evaluations.
- `component_scores.lane_familiarity` and `component_scores.reliability` are explicit nulls (deferred). They must not carry numeric values in the MVP.
- A `no_rankable_candidates` response has an empty ranked list and preserves every eligible-unrankable candidate. It is not a processing failure.

---

### 5.6 Approvals

#### `GET /api/v1/approvals`
- **Purpose:** List pending and completed approvals (the broker queue).
- **Roles:** `viewer`, `broker`, `admin`.
- **Query Params:** `status`, `shipment_id`, `requested_by`, `limit`, `offset`, `sort`.
- **Response `200 OK`:** Paginated approvals queue.

#### `GET /api/v1/approvals/{approval_id}`
- **Purpose:** Retrieve approval details with candidate comparisons and decision audit.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** Approval detail record.

#### `POST /api/v1/approvals/{approval_id}/decision`
- **Purpose:** Submit an authoritative broker decision and resume the paused workflow execution.
- **Roles:** `broker`, `admin`.
- **Headers:** `Idempotency-Key` (required).
- **Request Body:**
  ```json
  {
    "decision": "approve",
    "comment": "Approved at target buy rate $2,050. Verified reefer unit specs."
  }
  ```
  *Allowed decisions (INC-03):* `"approve"`, `"reject"`, `"request_changes"`.
- **Response `200 OK`:**
  ```json
  {
    "approval_id": "99999999-aaaa-bbbb-cccc-dddddddddddd",
    "status": "approved",
    "decided_by": "broker-user-uuid",
    "decided_at": "2026-11-22T10:30:00Z",
    "workflow_execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
  }
  ```
- **Transaction & Resumption Boundaries (DEF-05 & Phase 1.7.1):**
  - **Transaction Boundary:** Submitting an approval decision executes within a single ACID database transaction:
    1. Lock approval row (`SELECT ... FROM approvals WHERE id = :id FOR UPDATE`).
    2. Lock workflow execution row (`SELECT ... FROM workflow_executions WHERE id = :exec_id FOR UPDATE`).
        3. Update `approvals`: set `status = :decision` (`approved`, `rejected`, `changes_requested`), `decided_by = :user_id`, `decided_at = NOW()`, `decision_comment = :comment` (`selected_candidate_id` remains `NULL` in MVP; candidate override is Post-MVP per `FR-190`/`FR-191`). Note that `approvals.resumed_at` remains `NULL`.
    4. Transition `shipments.status`: `'approved'` (`frozen_at = NOW()`) if approved (Node 13 subsequently advances to `'booking_proposed'`); `'sourcing'` if rejected or changes requested (matching `03 §B.1` D-05).
    5. Set `workflow_executions.status = 'resumption_pending'`, clear any prior lease (`lease_token = NULL`, `lease_owner = NULL`, `lease_expires_at = NULL`), storing the durable intent to resume.
    6. Record immutable audit event (`approval.granted`, `approval.rejected`, or `approval.changes_requested`).
    7. Commit transaction.
  - **Execution Lease Acquisition & Budget Enforcement (DEF-05, Phase 1.7.3 & Phase 1.7.4):** Immediately post-commit, the application attempts to claim an exclusive execution lease with an incremented fencing counter, enforcing attempt limits and cumulative active compute budgets:
    ```sql
UPDATE workflow_executions
SET status = 'running',
    cumulative_compute_seconds = CASE
      WHEN status = 'running' THEN LEAST(900, cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer))
      ELSE cumulative_compute_seconds
    END,
    lease_token = gen_random_uuid(),
    lease_epoch = lease_epoch + 1,
    lease_owner = :worker_id,
    lease_expires_at = NOW() + INTERVAL '60 seconds',
    attempt_started_at = NOW(),
    attempt_count = CASE
      WHEN status = 'resumption_pending' THEN GREATEST(1, attempt_count)
      ELSE attempt_count + 1
    END,
    updated_at = NOW()
WHERE id = :execution_id
  AND cumulative_compute_seconds < 900
  AND (
    (status = 'queued' AND attempt_count = 0)
    OR (status = 'resumption_pending' AND attempt_count <= max_attempt_count)
    OR (
      status = 'running'
      AND lease_expires_at < NOW()
      AND attempt_count < max_attempt_count
      AND NOW() < attempt_started_at + INTERVAL '10 minutes'
      AND (cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer)) < 900
    )
  )
RETURNING id, status, lease_token, lease_epoch, attempt_count, cumulative_compute_seconds;
```
    If acquired, the worker resumes the LangGraph workflow past the interrupt:
    `graph.invoke(Command(resume={"action": decision, "comment": comment}), config=...)`.
    Active workers heartbeat every 15–20s (max 30s) to renew the lease, verifying `lease_expires_at > NOW()`, `NOW() < attempt_started_at + INTERVAL '10 minutes'`, and `(cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))) <= 900`. Upon successful finalization (Node 15), the worker commits status `completed`, records final `cumulative_compute_seconds`, and marks `approvals.resumed_at = NOW()` inside the SAME ACID transaction.
  - **Complete Canonical Decision Coverage (Phase 1.7.2):**
    - **`approve`:** Resumes workflow to Node 12, which validates the persisted approval and routes to Node 13 (`create_booking_proposal`), executing fencing check, approval verification, shipment transition (`booking_proposed`, `frozen_at = COALESCE(frozen_at, NOW())`), `INSERT ... ON CONFLICT (approval_id) DO NOTHING`, and `booking_proposal.created` audit insertion in one ACID transaction; Node 14 records the workflow summary audit event (`workflow.completed`, `outcome: approved`); Node 15 finalizes.
    - **`reject`:** Resumes workflow to Node 12, which validates the persisted decision and routes to Node 14; Node 14 records the workflow summary audit event (`workflow.completed`, `outcome: rejected`); Node 15 finalizes execution without creating a proposal. (The Approval Service decision transaction is the sole owner of the transition to `sourcing` and the `approval.rejected` audit event; Node 12 does not repeat the transition and Node 14 does not re-insert `approval.rejected`).
    - **`request_changes`:** Resumes workflow to Node 12, which validates the persisted decision and routes to Node 14; Node 14 records the workflow summary audit event (`workflow.completed`, `outcome: changes_requested`); Node 15 finalizes execution without creating a proposal. (The Approval Service decision transaction is the sole owner of the deterministic transition to `sourcing` and the `approval.changes_requested` audit event; Node 12 does not repeat the transition and Node 14 does not re-insert `approval.changes_requested`).
  - **Crash Recovery & Idempotent Resumption (DEF-05 & Phase 1.7.1):**
    - If the server crashes *after* the approval transaction commits but *before* graph resumption completes:
      - The decision is durably persisted in `approvals` with `resumed_at IS NULL`, and `workflow_executions.status` is `'resumption_pending'`.
      - When the client retries `POST /approvals/{id}/decision` or a startup recovery sweep runs, the system discovers that `approvals.status` is already decided while `approvals.resumed_at IS NULL`.
      - The system skips re-recording the decision, atomically claims the execution lease, and immediately resumes the LangGraph execution from its PostgreSQL checkpoint using the stored decision.
      - If the recovery worker crashes again, the 60-second lease expires, allowing a subsequent retry or sweep to safely reclaim ownership without human intervention or data duplication.
- **Errors:** `ERR-001`, `ERR-003`, `ERR-004`, `ERR-005`, `ERR-006`, `ERR-013`.

---

### 5.7 Booking Proposals

#### `POST /api/v1/booking-proposals` *(Post-MVP / Internal-Only — FR-158, FR-200)*

> **MVP Note:** Public manual creation via `POST /api/v1/booking-proposals` is not exposed in MVP. Booking proposals are created exclusively inside workflow Node 13 after human approval.
- **Purpose:** Create an internal booking proposal from an approved approval (normally invoked by workflow).
- **Roles:** `broker`, `admin`.
- **Headers:** `Idempotency-Key` (required).
- **Request Body:**
  ```json
  {
    "approval_id": "99999999-aaaa-bbbb-cccc-dddddddddddd"
  }
  ```
- **Response `201 Created`:** Created proposal record.
- **Errors:** `ERR-003`, `ERR-005` (already exists or approval not approved).

#### `GET /api/v1/booking-proposals` *(Post-MVP — FR-205)*
- **Purpose:** List booking proposals.
- **Roles:** `viewer`, `broker`, `admin`.
- **Query Params:** `status`, `shipment_id`, `carrier_id`, `limit`, `offset`.

#### `GET /api/v1/booking-proposals/{booking_proposal_id}`
- **Purpose:** Retrieve proposal record and frozen JSONB rate/carrier snapshot.
- **Roles:** `viewer`, `broker`, `admin`.

#### `POST /api/v1/booking-proposals/{booking_proposal_id}/cancel`
- **Purpose:** Cancel an unaccepted booking proposal, resetting the shipment to `sourcing`.
- **Roles:** `broker`, `admin`.
- **Request Body:** `{"reason": "Carrier rejected rate offer."}`
- **Response `200 OK`:** Updated proposal (`status: "cancelled"`), shipment reset to `sourcing`.
- **Errors:** `ERR-004`, `ERR-005`.

---

### 5.8 Carriers & Carrier Lane Rates

#### `POST /api/v1/carriers` *(Post-MVP — FR-060, FR-068)*
- **Purpose:** Create a Carrier master record.
- **Roles:** `broker`, `admin`.
- **Response `201 Created`:** Created Carrier record.

#### `GET /api/v1/carriers` *(Post-MVP — FR-060, FR-068)*
- **Purpose:** Search and filter carrier records.
- **Roles:** `viewer`, `broker`, `admin`.
- **Query Params:** `status`, `equipment_type`, `region_value`, `q`, `limit`, `offset`.

#### `GET /api/v1/carriers/{carrier_id}` *(Post-MVP — FR-060, FR-068)*
- **Purpose:** Retrieve carrier profile, equipment types, service regions, and availability.
- **Roles:** `viewer`, `broker`, `admin`.

#### `GET /api/v1/carriers/{carrier_id}/lane-rates`
- **Purpose:** List active and historical synthetic rate benchmarks for this carrier.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:** List of `carrier_lane_rates` records.

#### `POST /api/v1/carriers/{carrier_id}/lane-rates`
- **Purpose:** Record an active synthetic lane rate benchmark for carrier rate scoring (DEF-04).
- **Roles:** `broker`, `admin`.
- **Request Body:**
  ```json
  {
    "origin_region": "IL",
    "destination_region": "TX",
    "equipment_type": "reefer",
    "flat_rate": 2050.00,
    "rate_per_mile": 2.15,
    "min_rate": 1800.00,
    "currency": "USD",
    "source": "synthetic",
    "effective_date": "2026-11-01",
    "expiration_date": "2026-12-31"
  }
  ```
  *Constraint:* At most one active rate per carrier, origin region, destination region, and equipment type is permitted (`is_active = true`). At least one of `flat_rate` or `rate_per_mile` must be provided. Time-series historical rate analytics are deferred to Post-MVP.
- **Response `201 Created`:** Created lane rate record.

---

### 5.9 Workflows

#### `GET /api/v1/workflows/{workflow_execution_id}`
- **Purpose:** Inspect workflow state, current node, execution budgets, and status.
- **Roles:** `viewer`, `broker`, `admin`.
- **Response `200 OK`:**
  ```json
  {
    "workflow_execution_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
    "shipment_id": "8e6c4391-4cf5-4e08-9df2-43bb22272e12",
    "status": "waiting_for_human",
    "current_node": "request_human_approval",
    "attempt_count": 1,
    "llm_call_count": 1,
    "node_execution_count": 11,
    "error": null,
    "trace_id": "9f1c7d2e-4b6a-4d1e-8a2b-3c4d5e6f7a8b",
    "started_at": "2026-11-22T10:10:00Z"
  }
  ```

#### `POST /api/v1/workflows/{workflow_execution_id}/cancel` *(Post-MVP — FR-166)*
- **Purpose:** Terminate a running or paused workflow.
- **Roles:** `broker`, `admin`.
- **Response `200 OK`:** Workflow execution updated to `status: "cancelled"`.

---

### 5.10 Audit & Health

#### `GET /api/v1/audit-events` *(Post-MVP — FR-223)*
- **Purpose:** Query the immutable audit event log.
- **Roles:** `viewer`, `broker`, `admin`.
- **Query Params:** `shipment_id`, `workflow_execution_id`, `event_type`, `from`, `to`, `limit`, `offset`.

#### `GET /api/v1/health`
- **Purpose:** Service health check.
- **Roles:** Unauthenticated.
- **Response `200 OK`:** `{"status": "ok", "database": "ok", "llm_provider": "ready"}`.

#### `GET /api/v1/meta/enums` *(Post-MVP — FR-284)*
- **Purpose:** Retrieve canonical system enums for UI forms.
- **Roles:** Authenticated.

## 6. Idempotency, Concurrency, and Crash Recovery Semantics (F-API-03 / DEF-05)

1. **Header Requirement:** Active MVP state-changing mutations (`POST /intake/submissions`, `POST /facilities`, `PATCH /facilities/{id}`, `PATCH /shipments/{id}`, `POST /shipments/{id}/validation`, `POST /shipments/{id}/recommendations`, `POST /approvals/{id}/decision`, `POST /booking-proposals/{id}/cancel`, `POST /carriers/{id}/lane-rates`) require an `Idempotency-Key` header (UUID recommended).
2. **Atomic In-Progress Locking & Configurable Lease:**
   - When a mutation arrives, the API layer attempts an atomic insert into `idempotency_keys` with `status = 'in_progress'`.
   - **Race Condition Handling:** If a concurrent request arrives with the identical key while the first is `in_progress`, the server rejects the second request immediately with HTTP `409 Conflict` (`ERR-006`: "Request with this idempotency key is currently being processed").
   - **Stale Lease Recovery (DEF-05):** The in-progress lease duration defaults to **60 seconds** (`IDEMPOTENCY_LEASE_SECONDS = 60`). If a key remains `status = 'in_progress'` past 60 seconds without an active database row lock, it is considered stranded due to a worker crash. A retried request reclaims the key, sets `created_at = now()`, and proceeds.
3. **Execution Lease, Fencing Tokens, and Execution Budget Enforcement (DEF-05, Phase 1.7.3 & Phase 1.7.4):**
   - Operating system process IDs (PIDs) are explicitly **not** used as proof of execution ownership because container restarts and Kubernetes pods cause PID collisions and invisibility.
   - Execution ownership is governed strictly by database leases and monotonically increasing fencing counters on `workflow_executions`:
     - `lease_token uuid`: Cryptographic token identifying the active lease session (cleared to NULL on `waiting_for_human` and terminal states).
     - `lease_epoch integer`: Monotonically increasing fencing counter incremented on every lease acquisition.
     - `lease_owner text`: Worker instance identifier (cleared to NULL on `waiting_for_human` and terminal states).
     - `lease_expires_at timestamptz`: Absolute wall-clock expiry time (initial 60-second window; cleared to NULL on `waiting_for_human` and terminal states).
     - `cumulative_compute_seconds integer`: Monotonically accumulated active compute duration (excluding human wait; hard ceiling 900s).
     - `max_attempt_count integer`: Maximum permitted execution attempts (default 3).
   - **Atomic Lease Acquisition & Budget Guard:** A worker or recovery sweep claims a lease ONLY if `cumulative_compute_seconds < 900` AND the execution is `queued` (`attempt_count = 0`), `resumption_pending` (`attempt_count <= max_attempt_count`, preserving `attempt_count`), or an expired `running` execution (`lease_expires_at < NOW() AND attempt_count < max_attempt_count`, incrementing `attempt_count` and accumulating bounded crash-window compute):

```sql
UPDATE workflow_executions
SET status = 'running',
    cumulative_compute_seconds = CASE
      WHEN status = 'running' THEN LEAST(900, cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer))
      ELSE cumulative_compute_seconds
    END,
    lease_token = gen_random_uuid(),
    lease_epoch = lease_epoch + 1,
    lease_owner = :worker_id,
    lease_expires_at = NOW() + INTERVAL '60 seconds',
    attempt_started_at = NOW(),
    attempt_count = CASE
      WHEN status = 'resumption_pending' THEN GREATEST(1, attempt_count)
      ELSE attempt_count + 1
    END,
    updated_at = NOW()
WHERE id = :execution_id
  AND cumulative_compute_seconds < 900
  AND (
    (status = 'queued' AND attempt_count = 0)
    OR (status = 'resumption_pending' AND attempt_count <= max_attempt_count)
    OR (
      status = 'running'
      AND lease_expires_at < NOW()
      AND attempt_count < max_attempt_count
      AND NOW() < attempt_started_at + INTERVAL '10 minutes'
      AND (cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer)) < 900
    )
  )
RETURNING id, status, lease_token, lease_epoch, attempt_count, cumulative_compute_seconds;
```

     *Protection of Inactive Executions:* Transitions to `waiting_for_human` (Node 11) or terminal states clear all lease fields so paused or finished executions can never be reclaimed.
   - **Terminal Status and Conditional Atomic Audit Behavior on Limit Exhaustion:**
     If an execution hits `cumulative_compute_seconds >= 900` (`timed_out`) or exhausts `max_attempt_count` (`failed`), a single atomic data-modifying CTE updates the execution and inserts `workflow.failed` **only from the updated row**. If the execution already transitioned to another terminal state, 0 rows return, 0 audit events are inserted, and the transaction rolls back:
```sql
BEGIN;

WITH exhausted AS (
  UPDATE workflow_executions
  SET status = CASE
        WHEN cumulative_compute_seconds >= 900
          OR (status = 'running' AND NOW() >= attempt_started_at + INTERVAL '10 minutes')
          OR (status = 'running' AND (cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer)) >= 900)
          THEN 'timed_out'
        ELSE 'failed'
      END,
      error_code = CASE
        WHEN cumulative_compute_seconds >= 900
          OR (status = 'running' AND (cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer)) >= 900)
          THEN 'MAX_COMPUTE_BUDGET_EXCEEDED'
        WHEN status = 'running' AND NOW() >= attempt_started_at + INTERVAL '10 minutes'
          THEN 'MAX_CONTINUOUS_ATTEMPT_EXCEEDED'
        ELSE 'MAX_ATTEMPTS_EXCEEDED'
      END,
      error_message = CASE
        WHEN cumulative_compute_seconds >= 900
          OR (status = 'running' AND (cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer)) >= 900)
          THEN 'Execution aborted: 15-minute cumulative active compute budget exceeded'
        WHEN status = 'running' AND NOW() >= attempt_started_at + INTERVAL '10 minutes'
          THEN 'Execution aborted: 10-minute continuous attempt limit exceeded'
        ELSE 'Execution aborted: maximum execution attempts (3) exhausted'
      END,
      lease_token = NULL,
      lease_owner = NULL,
      lease_expires_at = NULL,
      completed_at = NOW(),
      updated_at = NOW()
  WHERE id = :execution_id
    AND status IN ('queued', 'running', 'resumption_pending')
    AND (
      cumulative_compute_seconds >= 900
      OR (
        status = 'running'
        AND lease_expires_at < NOW()
        AND (
          attempt_count >= max_attempt_count
          OR NOW() >= attempt_started_at + INTERVAL '10 minutes'
          OR (cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), lease_expires_at) - attempt_started_at))::integer)) >= 900
        )
      )
      OR (status = 'resumption_pending' AND attempt_count > max_attempt_count)
    )
  RETURNING id, shipment_id, status, error_code, attempt_count, cumulative_compute_seconds, trace_id
),
audit_insert AS (
  INSERT INTO audit_events (
      event_type, actor_type, actor_id, shipment_id, workflow_execution_id, trace_id, payload, created_at
  )
  SELECT
      'workflow.failed',
      'system',
      NULL,
      e.shipment_id,
      e.id,
      e.trace_id,
      jsonb_build_object(
        'error_code', e.error_code,
        'attempt_count', e.attempt_count,
        'cumulative_compute_seconds', e.cumulative_compute_seconds
      ),
      NOW()
  FROM exhausted e
)
SELECT id, status, error_code
FROM exhausted;

-- Application transaction protocol:
-- 1. Check returned rows: if len(rows) == 1 -> COMMIT.
-- 2. If len(rows) == 0 (e.g. execution already transitioned to completed/failed/timed_out/cancelled, or lease was reclaimed):
--    ROLLBACK (zero audit rows were inserted by the CTE) and return/raise UnexpectedTerminalTransitionError without emitting a duplicate audit event.
-- 3. If len(rows) > 1: ROLLBACK and raise IntegrityError.
COMMIT;
```
   - **Active Compute vs Human Wait Time Accounting:**
     - `cumulative_compute_seconds` measures ONLY active execution compute across attempts.
     - When Node 11 pauses for human approval, the pre-approval compute duration is committed:
           Application-managed ACID transaction and LangGraph `interrupt()` protocol (`langgraph` + `langgraph-checkpoint-postgres` exact version pin is an unresolved implementation dependency in `10 §3` to be verified at the `PH-1`/`PH-5` gate; no invented `resume_payload` parameter is used):
    ```python
    def request_human_approval(state: WorkflowState) -> dict:
        # Check durable PostgreSQL approval state + checkpoint state
        existing = db.execute(
            "SELECT id, workflow_execution_id, recommendation_id, status, decision_comment, resumed_at "
            "FROM approvals WHERE workflow_execution_id = :execution_id",
            {"execution_id": state["execution_id"]},
        ).fetchone()

        if existing is None and state.get("approval_id") is None:
            # --- FIRST EXECUTION: fenced pause, pending approval + audit, commit BEFORE interrupt() ---
            with db.begin() as tx:
                wf_res = tx.execute(NODE_11_FENCE_PAUSE_SQL, params)
                if wf_res.rowcount != 1:
                    tx.rollback()
                    raise ExecutionLeaseFencingError("Stale lease, expired attempt window, or exhausted budget at Node 11")

                appr_row = tx.execute(INSERT_PENDING_APPROVAL_SQL, appr_params).fetchone()
                if appr_row is not None:
                    approval_id = appr_row.id
                    audit_res = tx.execute(INSERT_APPROVAL_REQUESTED_AUDIT_SQL, {..., "approval_id": approval_id})
                    if audit_res.rowcount != 1:
                        tx.rollback()
                        raise AuditWriteError("Expected exactly 1 approval.requested audit row")
                else:
                    row = tx.execute(
                        "SELECT id FROM approvals WHERE workflow_execution_id = :execution_id",
                        {"execution_id": state["execution_id"]},
                    ).fetchone()
                    if row is None:
                        tx.rollback()
                        raise IntegrityError("Missing approval row after conflict")
                    approval_id = row.id

                tx.commit()
        else:
            # --- RESUME EXECUTION: reconstruct from durable state; do NOT repeat pause/inserts ---
            approval_id = state.get("approval_id") or (existing.id if existing else None)
            if existing is None or existing.id != approval_id or existing.resumed_at is not None:
                raise InvalidApprovalStateError("Missing, mismatched, or already-resumed approval on Node 11 resume")

            with db.begin() as tx:
                fence_rows = tx.execute(FENCE_CHECK_SQL, params).fetchall()
                if len(fence_rows) != 1:
                    tx.rollback()
                    raise ExecutionLeaseFencingError("Stale lease or exhausted budget on Node 11 resume")
                tx.commit()

        # Both first execution and resume execution MUST reach interrupt() to pause or consume Command(resume=...)
        decision_payload = interrupt({"approval_id": approval_id, "recommendation_id": state["recommendation_id"]})

        # Post-interrupt validation against durable PostgreSQL approval record
        decided = db.execute(
            "SELECT id, workflow_execution_id, recommendation_id, status, decision_comment, resumed_at "
            "FROM approvals WHERE workflow_execution_id = :execution_id",
            {"execution_id": state["execution_id"]},
        ).fetchone()
        expected_status = {"approve": "approved", "reject": "rejected", "request_changes": "changes_requested"}.get(
            (decision_payload or {}).get("action")
        )
        if (
            decided is None
            or decided.id != approval_id
            or decided.workflow_execution_id != state["execution_id"]
            or decided.recommendation_id != state["recommendation_id"]
            or decided.status not in ("approved", "rejected", "changes_requested")
            or decided.resumed_at is not None
            or expected_status != decided.status
        ):
            raise InvalidApprovalStateError("Resumed decision failed durable approval/identity verification")

        return {
            "approval_id": decided.id,
            "human_decision": decided.status,
            "decision_comment": decided.decision_comment,
        }
    ```
    ```sql
    -- NODE_11_FENCE_PAUSE_SQL:
    UPDATE workflow_executions
    SET status = 'waiting_for_human',
        cumulative_compute_seconds = LEAST(900, cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer)),
        lease_token = NULL,
        lease_owner = NULL,
        lease_expires_at = NULL,
        updated_at = NOW()
    WHERE id = :execution_id
      AND lease_token = :my_current_lease_token
      AND lease_epoch = :my_current_lease_epoch
      AND lease_expires_at > NOW()
      AND NOW() < attempt_started_at + INTERVAL '10 minutes'
      AND (cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer) <= 900;
    ```
     - While `status = 'waiting_for_human'`, compute is stopped. The broker may take minutes, hours, or days to submit a decision; this human wait time contributes zero seconds to `cumulative_compute_seconds`.
     - Upon lease acquisition from `resumption_pending`, `attempt_started_at = NOW()` is set, granting a fresh 10-minute continuous attempt window while preserving `cumulative_compute_seconds`.
   - **Heartbeat Protocol & Renewal Interval:** Active workers renew their lease every **15 to 20 seconds** (maximum interval: 30 seconds). Renewal enforces both the continuous attempt bound (10 minutes) and the cumulative active compute budget (15 minutes / 900 seconds):
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
   - **Atomic Race Condition & Heartbeat vs Takeover Mechanics:**
     PostgreSQL row-level write locks (`UPDATE` row serialization) eliminate race conditions between concurrent heartbeat renewals and lease takeovers:
     - *Heartbeat commits before Takeover:* Worker A's heartbeat acquires the row lock while its lease is unexpired (`lease_expires_at > NOW()`). Worker A extends `lease_expires_at = NOW() + 60s` and commits. When Worker B's takeover query executes against the updated row, `lease_expires_at < NOW()` evaluates to FALSE. Worker B's UPDATE affects 0 rows, and Worker B aborts takeover safely.
     - *Takeover commits before Heartbeat:* If Worker A stalls past 60s, its lease expires. Worker B's takeover query acquires the row lock, advances `lease_epoch = lease_epoch + 1`, assigns a new `lease_token`, resets `attempt_started_at = NOW()`, and commits. When Worker A wakes up and its delayed heartbeat executes, `lease_token = :my_token AND lease_epoch = :my_epoch` evaluates to FALSE. Worker A's UPDATE affects 0 rows.
   - **Loss of Ownership Behavior:** If a heartbeat fails (returns 0 rows affected), the worker immediately aborts execution, sets an internal abort flag, raises `ExecutionLeaseFencingError`, and ceases all database writes.
   - **Exact Transaction Boundaries for Nodes 13, 14, and 15:**
  - **Node 13 (Booking Proposal Creation — Atomic Approval, Freeze, Proposal & Audit Transaction):**
    Application-managed ACID transaction protocol (executes all steps in one transaction; rolls back on any failure):
    ```python
    with db.begin() as tx:
        # 1. Lease/fencing check (must return exactly 1 row)
        fence_rows = tx.execute(FENCE_CHECK_SQL, params).fetchall()
        if len(fence_rows) != 1:
            tx.rollback()
            raise ExecutionLeaseFencingError("Stale lease or exhausted execution budget")

        # 2. Verify approval is in 'approved' state (must return exactly 1 row)
        appr = tx.execute(
            "SELECT id, status FROM approvals WHERE id = :approval_id FOR UPDATE",
            {"approval_id": approval_id},
        ).fetchone()
        if appr is None or appr.status != "approved":
            tx.rollback()
            raise InvalidApprovalStateError("Approval must be in approved status")

        # 3. Freeze & transition shipment inside the same transaction (must update exactly 1 row)
        ship_res = tx.execute(
            "UPDATE shipments SET status = 'booking_proposed', frozen_at = COALESCE(frozen_at, NOW()), updated_at = NOW() "
            "WHERE id = :shipment_id AND status IN ('approved', 'booking_proposed')",
            {"shipment_id": shipment_id},
        )
        if ship_res.rowcount != 1:
            tx.rollback()
            raise StateTransitionError("Shipment not in approved/booking_proposed state")

        # 4. Idempotent booking proposal insert
        inserted = tx.execute(INSERT_PROPOSAL_ON_CONFLICT_SQL, proposal_params).fetchone()
        if inserted is not None:
            proposal_id = inserted.id
            # 5. Insert mandatory booking_proposal.created audit event in the SAME transaction (no duplicate on replay)
            tx.execute(INSERT_BOOKING_PROPOSAL_CREATED_AUDIT_SQL, {..., "booking_proposal_id": proposal_id})
        else:
            existing = tx.execute(
                "SELECT id, status FROM booking_proposals WHERE approval_id = :approval_id",
                {"approval_id": approval_id},
            ).fetchone()
            if existing is None:
                tx.rollback()
                raise IntegrityError("Missing booking proposal after conflict")
            proposal_id = existing.id

        # 6. Commit all operations together
        tx.commit()
    ```
    ```sql
    -- FENCE_CHECK_SQL:
    SELECT lease_epoch FROM workflow_executions
    WHERE id = :execution_id
      AND lease_token = :my_token
      AND lease_epoch = :my_epoch
      AND lease_expires_at > NOW()
      AND NOW() < attempt_started_at + INTERVAL '10 minutes'
      AND (cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer) <= 900
    FOR UPDATE;

    -- INSERT_PROPOSAL_ON_CONFLICT_SQL:
    INSERT INTO booking_proposals (id, shipment_id, approval_id, carrier_id, proposal_number, status, snapshot, idempotency_key, created_by, created_at, updated_at)
    VALUES (gen_random_uuid(), :shipment_id, :approval_id, :carrier_id, :proposal_number, 'proposed', :snapshot, :idempotency_key, :user_id, NOW(), NOW())
    ON CONFLICT (approval_id) DO NOTHING
    RETURNING id, status;

    -- INSERT_BOOKING_PROPOSAL_CREATED_AUDIT_SQL:
    INSERT INTO audit_events (event_type, actor_type, actor_id, shipment_id, workflow_execution_id, approval_id, booking_proposal_id, trace_id, payload, created_at)
    VALUES ('booking_proposal.created', 'system', NULL, :shipment_id, :execution_id, :approval_id, :booking_proposal_id, :trace_id, :proposal_audit_payload, NOW());
    ```
  - **Node 14 (Workflow Audit Recording — Database-Enforced Idempotency & Canonical Replay Verification):**
    Application-managed ACID transaction protocol (the Approval Service transaction owns the human decision audit event `approval.granted`, `approval.rejected`, or `approval.changes_requested`; Node 13 atomically records `booking_proposal.created`; Node 14 records exclusively the workflow outcome summary event `workflow.completed` across all execution paths) using `audit_events.idempotency_key` (`uq_audit_events_idempotency_key`):
    - **Canonical Event Identity:** `(idempotency_key, event_type, workflow_execution_id, shipment_id, approval_id, booking_proposal_id)` — `event_type` is always `'workflow.completed'`; `approval_id` is non-null on approval paths (`approved`, `rejected`, `changes_requested`) and explicitly `NULL` (`None`) on `no_eligible_carriers`; `booking_proposal_id` is non-null on `approved` and explicitly `NULL` (`None`) on `rejected`, `changes_requested`, and `no_eligible_carriers`.
    - **Canonical Immutable Payload:** `metrics_json` contains only deterministic immutable fields (`outcome`, `final_shipment_status`, `node_execution_count`, `llm_call_count`, `attempt_count`, `cumulative_compute_seconds`, `recommendation_id`, `error_code`); volatile timestamps (`created_at`) are excluded. `outcome` is one of `'approved'`, `'rejected'`, `'changes_requested'`, or `'no_eligible_carriers'`. Canonicalization sorts keys recursively (`json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)`) with explicit `null` values preserved, and verifies SHA-256 digest equality.
    ```python
    def canonical_payload_sha256(payload: dict) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    with db.begin() as tx:
        # 1. Lease/fencing check (must return exactly 1 row)
        fence_rows = tx.execute(FENCE_CHECK_SQL, params).fetchall()
        if len(fence_rows) != 1:
            tx.rollback()
            raise ExecutionLeaseFencingError("Stale lease or exhausted execution budget")

        # 2. Database-enforced idempotent audit insert (deterministic key per execution: node14:<execution_id>:workflow.completed)
        canonical_outcome_event = "workflow.completed"
        outcome_key = f"node14:{execution_id}:workflow.completed"
        inserted_audit = tx.execute(
            INSERT_OUTCOME_AUDIT_SQL,
            {**audit_params, "canonical_outcome_event": canonical_outcome_event, "idempotency_key": outcome_key},
        ).fetchone()
        if inserted_audit is None:
            # Re-execution after crash before checkpoint advance: verify canonical identity & immutable payload digest
            existing = tx.execute(
                "SELECT id, idempotency_key, event_type, workflow_execution_id, shipment_id, "
                "       approval_id, booking_proposal_id, payload "
                "FROM audit_events WHERE idempotency_key = :idempotency_key",
                {"idempotency_key": outcome_key},
            ).fetchone()
            if (
                existing is None
                or existing.idempotency_key != outcome_key
                or existing.event_type != canonical_outcome_event
                or existing.workflow_execution_id != execution_id
                or existing.shipment_id != shipment_id
                or existing.approval_id != approval_id
                or existing.booking_proposal_id != booking_proposal_id
                or canonical_payload_sha256(existing.payload) != canonical_payload_sha256(metrics_json)
            ):
                tx.rollback()
                raise AuditIdempotencyConflictError(
                    "Existing audit_events row does not match expected canonical identity or immutable payload"
                )

        # 3. Commit
        tx.commit()
    ```
    ```sql
    -- INSERT_OUTCOME_AUDIT_SQL:
    INSERT INTO audit_events (
        event_type, actor_type, actor_id, shipment_id, workflow_execution_id,
        approval_id, booking_proposal_id, trace_id, idempotency_key, payload, created_at
    ) VALUES (
        :canonical_outcome_event, 'system', NULL, :shipment_id, :execution_id,
        :approval_id, :booking_proposal_id, :trace_id, :idempotency_key, :metrics_json, NOW()
    )
    ON CONFLICT (idempotency_key) WHERE idempotency_key IS NOT NULL DO NOTHING
    RETURNING id;
    ```
  - **Node 15 (Finalization):**
    Application-managed ACID transaction protocol validating fencing, lease expiry, attempt deadline, cumulative budget, and conditional `approvals.resumed_at` update:
    ```python
    with db.begin() as tx:
        # 1. Fenced completion update (must affect exactly 1 row)
        wf_res = tx.execute(FINALIZE_WORKFLOW_SQL, params)
        if wf_res.rowcount != 1:
            tx.rollback()
            raise ExecutionLeaseFencingError("Stale lease or exhausted execution budget")

        # 2. Conditional approval resumption timestamp (approval path only; omitted for no_eligible_carriers)
        if approval_id is not None:
            appr_res = tx.execute(
                "UPDATE approvals SET resumed_at = NOW(), updated_at = NOW() "
                "WHERE id = :approval_id AND resumed_at IS NULL",
                {"approval_id": approval_id},
            )
            if appr_res.rowcount != 1:
                tx.rollback()
                raise ApprovalResumptionConflictError("Expected exactly 1 undecided-resumption approval row")

        # 3. Commit only after all required updates succeed
        tx.commit()
    ```
    ```sql
    -- FINALIZE_WORKFLOW_SQL:
    UPDATE workflow_executions
    SET status = 'completed',
        cumulative_compute_seconds = LEAST(900, cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer)),
        lease_token = NULL, lease_owner = NULL, lease_expires_at = NULL,
        completed_at = NOW(), updated_at = NOW()
    WHERE id = :execution_id
      AND lease_token = :my_token AND lease_epoch = :my_epoch
      AND lease_expires_at > NOW()
      AND NOW() < attempt_started_at + INTERVAL '10 minutes'
      AND (cumulative_compute_seconds + EXTRACT(EPOCH FROM (NOW() - attempt_started_at))::integer) <= 900;
    ```
   - **Proof of Stale-Worker Isolation:** A stalled worker waking up after losing its lease cannot commit side effects because Worker B advanced `lease_epoch`. Any mutation attempted by the stale worker fails the fencing check (`SELECT lease_epoch ... FOR UPDATE` or `UPDATE ... WHERE lease_epoch = :my_epoch`), immediately aborts, and rolls back cleanly without writing side effects.
4. **Completion and Caching:**
   - When the operation succeeds within the database transaction, `idempotency_keys.status` updates to `'completed'`, storing `response_code` (e.g., 200 or 201) and `response_body`.
   - Subsequent replays return the cached response verbatim. Completed keys are retained for 24 hours.
5. **Failure Handling:**
   - If the request raises a transient exception or unhandled error, `idempotency_keys.status` transitions to `'failed'` or the lock row is deleted, allowing safe client retries.
6. **Replay Mismatch:**
   - If an idempotency key is reused with a differing request payload hash, the server returns HTTP `409 Conflict` (`ERR-006`: "Idempotency key reused with different request payload").
7. **Four Crash Recovery Scenarios (DEF-05 & Phase 1.7.1):**
   - **Scenario 1: Crash before approval decision transaction commits.**
     *State:* DB transaction rolls back; `approvals.status = 'pending'`, `approvals.decided_at IS NULL`, `workflow_executions.status = 'waiting_for_human'`, `workflow_executions.lease_expires_at IS NULL`.
     *Recovery:* Client retries `POST /approvals/{id}/decision`; proceeds normally as a fresh decision submission.
   - **Scenario 2: Crash after approval decision commits but before workflow resumption starts.**
     *State:* `approvals.status = 'approved'`, `approvals.decided_at IS NOT NULL`, `approvals.resumed_at IS NULL`, `workflow_executions.status = 'resumption_pending'`, checkpointer contains checkpoint at `request_human_approval`.
     *Recovery:* Discovered immediately upon client retry or background recovery sweep. The system notices decision is saved but `resumed_at IS NULL`. It atomically claims the execution lease, re-hydrates the LangGraph state from the checkpointer, and resumes execution past the interrupt using the stored decision. Zero duplicate side effects occur.
   - **Scenario 3: Crash during resumed workflow execution (e.g. inside proposal creation).**
     *State:* `workflow_executions.status = 'running'`, `lease_owner = 'worker-A'`, `lease_expires_at = NOW() + 45s`. Process dies.
     *Recovery:* After 60 seconds, the execution lease expires (`lease_expires_at < NOW()`). The client retry or recovery sweep reclaims the lease atomically with a new `lease_token`. LangGraph resumes from the last persisted node checkpoint. Proposal creation (Node 13) checks if an active proposal already exists for the approval before inserting, guaranteeing idempotency.
   - **Scenario 4: Crash after workflow completion before HTTP response returns to client.**
     *State:* `approvals.status = 'approved'`, `approvals.resumed_at = NOW()`, `workflow_executions.status = 'completed'`, `idempotency_keys.status = 'completed'`.
     *Recovery:* Client retries `POST /approvals/{id}/decision`; system detects `approvals.resumed_at IS NOT NULL` and returns `200 OK` with the existing approval and proposal details immediately from the cache without re-invoking the workflow.
8. **Startup and Periodic Recovery Check Semantics:**
   - On application startup and via passive sweeps, the system discovers stranded resumptions using a targeted query:
     ```sql
SELECT w.id, w.shipment_id, w.status, w.attempt_count, w.max_attempt_count,
       w.cumulative_compute_seconds, w.lease_expires_at,
       a.id AS approval_id, a.status AS approval_status, a.resumed_at
FROM workflow_executions w
LEFT JOIN approvals a ON a.workflow_execution_id = w.id
WHERE w.cumulative_compute_seconds < 900
  AND (
    (
      w.status = 'resumption_pending'
      AND w.attempt_count <= w.max_attempt_count
      AND a.status IN ('approved', 'rejected', 'changes_requested')
      AND a.resumed_at IS NULL
    )
    OR (
      w.status = 'running'
      AND w.lease_expires_at < NOW()
      AND w.attempt_count < w.max_attempt_count
      AND NOW() < w.attempt_started_at + INTERVAL '10 minutes'
      AND (w.cumulative_compute_seconds + GREATEST(0, EXTRACT(EPOCH FROM (LEAST(NOW(), w.lease_expires_at) - w.attempt_started_at))::integer)) < 900
    )
  )
ORDER BY w.updated_at ASC
FOR UPDATE OF w SKIP LOCKED;
```
   - **Strict Distinction between Undecided Approvals and Interrupted Resumptions:**
     - Undecided pending approvals (`workflow_executions.status = 'waiting_for_human'`, `approvals.status = 'pending'`) are **NEVER** returned by this query and are **NEVER** expired or auto-resumed. They remain parked indefinitely until an authorized human acts.
     - Only executions with a recorded decision (`a.status IN ('approved', 'rejected', 'changes_requested')`) whose resumption was interrupted (`a.resumed_at IS NULL`) are claimed and resumed.
9. **Database-Enforced Idempotency for Booking Proposals (Phase 1.7.2):**
   - The system does not rely exclusively on SELECT-before-INSERT.
   - The database schema enforces proposal uniqueness via `booking_proposals.approval_id UNIQUE NOT NULL REFERENCES approvals(id)` and a partial unique index on `shipment_id WHERE status IN ('proposed', 'accepted')`.
   - Node 13 executes proposal creation using atomic insert-on-conflict:
     ```sql
     INSERT INTO booking_proposals (id, shipment_id, approval_id, carrier_id, proposal_number, status, snapshot, idempotency_key, created_by, created_at, updated_at)
     VALUES (gen_random_uuid(), :shipment_id, :approval_id, :carrier_id, :proposal_number, 'proposed', :snapshot, :idempotency_key, :user_id, NOW(), NOW())
     ON CONFLICT (approval_id) DO NOTHING
     RETURNING id, status;
     ```
   - If two concurrent workers attempt proposal creation, PostgreSQL's unique B-tree index serializes the operations: exactly one worker inserts; the other hits `ON CONFLICT` and reuses the existing proposal.
   - If a crash occurs after proposal insertion but before workflow finalization, upon resumption the worker hits `ON CONFLICT (approval_id)`, reuses the existing proposal, and finalizes cleanly without duplicate records.

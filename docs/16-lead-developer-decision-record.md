# 16 — Lead Developer Decision Record (PH-4)

| Field | Value |
|---|---|
| Document | Lead Developer Decision Record — PH-4 carrier matching and recommendation |
| Contract version | 2.2 |
| Authority | Lead Developer |
| Status | Active record. D-014 through D-033 are approved as stated. D-033 is resolved by Option A (§16A.7) and the Task 004-H implementation decisions (§23). Items in §17 are updated accordingly; §21 preserves the historical pre-implementation gate. |
| Date recorded | 2026-11-25 |
| Scope | PH-4 scoring, ranking, rate selection, and candidate persistence |
| Implementation authorization | **Project-owner authorization recorded 2026-11-25:** implement the FreightOps AI MVP end-to-end. Decisions D-033 and the component formulas are resolved for implementation in §16A.7 and §23 under that authorization. |
| Supersedes | The working recommendations in Task 004-B and Task 004-C for D-014 through D-026, where those recommendations differ from this record. Their evidence and analysis remain valid. |

> This record exists so future implementation tasks do not have to interpret conversation history, task reports, or code comments. Where a decision below conflicts with a higher-precedence contract, the contract governs and the conflict must be escalated; it must not be resolved silently.

---

## 1. Purpose, authority, and classification

### 1.1 Purpose

This document converts the Lead Developer's PH-4 decisions into an authoritative, traceable record covering:

- the scoring objective and the deferred components;
- the MVP weights, configuration keys, validation rules, ranking tie-break, precision, and candidate-persistence rules;
- the rate date policy, lane matching, missing-rate behavior, `min_rate` treatment, and currency matching.

It also records the unresolved decisions that still block a complete PH-4 implementation, the required API implications, and the existing source-document conflicts. It does not modify those source documents.

### 1.2 Authority and precedence

The authoritative basis is Contract 2.2 as expressed in:

1. `docs/03-requirements-specification.md` Appendix A (vocabulary and enumerations), §1.2 (precedence), and §1.3 (MVP cut line).
2. `docs/06-database-design.md` (schema truth).
3. `docs/09-api-design.md` (wire truth).
4. `docs/07-agent-workflow.md` (workflow truth).
5. Descriptive prose in any document.

The Lead Developer decisions in this record resolve ambiguities left by those sources. They are binding for PH-4 implementation, but they are **not** contract-defined requirements. A decision being consistent with a requirement does not make the decision itself contract-defined.

No `docs/15-implementation-scope.md` exists in the repository. The latest approved implementation scope used for this record is `docs/03 §1.3` (authoritative MVP cut line) and `docs/13-development-roadmap.md` (approved roadmap). No substitute document was invented.

### 1.3 Classification legend

| Label | Meaning | Binding? |
|---|---|---|
| **Contract-defined requirement** | A rule stated by Contract 2.2 in `docs/03`, `docs/06`, `docs/09`, or `docs/07`. | Yes, by precedence |
| **Lead Developer-approved decision** | A decision approved by the Lead Developer and recorded here. | Yes, for PH-4 implementation |
| **Engineering proposal** | A recommendation from Task 004-A, 004-B, or 004-C that was not adopted, or an implementation suggestion in this record. | No |
| **Unresolved question** | A question with no approved answer. It must not be implemented by assumption. | Blocks the affected work |

Every decision D-014 through D-026 is classified as a **Lead Developer-approved decision**, even where contract text supports it. The contract references are supporting evidence, not the source of approval.

### 1.4 What this record does not do

- It does not modify `docs/03`, `docs/06`, `docs/07`, `docs/09`, `docs/12`, `docs/13`, `docs/15-architecture-revision-log.md`, `docs/14-architecture-review.md`, or `docs/README.md`.
- It does not modify source code, tests, models, migrations, API schemas, scoring formulas, weights, dependencies, or `.gitignore`.
- It does not resolve the conflicts recorded in §19. Those require separate documentation authorization.
- It does not approve any decision listed in §17.
- It does not start PH-4 or PH-5 implementation.

---

## 2. Source inspection

### 2.1 Files inspected

| Source | Status | Sections used |
|---|---|---|
| `docs/03-requirements-specification.md` | Present, inspected | §1.2 precedence; §1.3 MVP cut line; §5.2 FR-026/027; §5.3 FR-073; §5.6 FR-120–125, FR-127, FR-132–134; Appendix A.2 score components and reason codes |
| `docs/06-database-design.md` | Present, inspected | §2 money/currency convention; §3.8 `carrier_lane_rates`; §3.9 `shipments`; §3.13 `recommendations`; §3.14 `recommendation_candidates`; §3.19 `scoring_configs` |
| `docs/05-component-architecture.md` | Present, inspected | §4.7 lane rates; §4.8 eligibility; §4.9 Recommendation Engine |
| `docs/07-agent-workflow.md` | Present, inspected | §6 Nodes 6–10 (candidate resolution, eligibility, scoring, explanation, persistence) |
| `docs/08-data-flow.md` | Present, inspected | DF-02 boundaries and sequence; lane-rate loading (lines 143-145, 170) |
| `docs/09-api-design.md` | Present, inspected | §2 currency/rate convention; §5.5 recommendation trigger and detail; §5.8 lane-rate endpoints |
| `docs/10-technology-decisions.md` | Present, inspected | ADR-007 deterministic eligibility/scoring |
| `docs/11-security-and-reliability.md` | Present, inspected | §6 hallucinated-rate mitigation and absolute guarantee |
| `docs/12-evaluation-strategy.md` | Present, inspected | EV-04, EV-05, EV-06; DS-03/DS-04; §5.3–5.4 |
| `docs/13-development-roadmap.md` | Present, inspected | §2 sequencing; §4 PH-3 and PH-4; §7 deferred backlog; §9 MVP cut line |
| `docs/15-implementation-scope.md` | **Absent** | No such file exists. Its contents are not inferred or fabricated. |
| `docs/15-architecture-revision-log.md` | Present, inspected | CRIT-03, F-DB-04, DEF-04 (rate-data and schema revision context) |
| `task-004-a-carrier-matching-specification.md` | Present, inspected | Existing specification and identified ambiguities |
| `task-004-b-business-rule-resolution.md` | Present, inspected | §12 decision register (D-004-B-014 through D-004-B-039) |
| `task-004-c-rate-policy-resolution.md` | Present, inspected | D-022 through D-026 proposals, worked examples, schema implications |
| Existing Lead Developer decision records | **None found** | No prior `docs/16-*` or equivalent PH-4 decision record exists. `docs/10` ADRs and `docs/15-architecture-revision-log.md` are architecture records, not this decision record. |
| `docs/14-architecture-review.md` | Present, protected | Not modified. SHA-256 verified before and after this task. |

### 2.2 Contract facts referenced

These are **contract-defined facts**, not Lead Developer decisions. They support the decisions but do not decide them.

| Fact | Source |
|---|---|
| Lane is derived from the first pickup and last delivery | FR-026 (`03` line 169) |
| Validated shipments require complete city/state and pickup/delivery windows | `REQ-ADDR`, `REQ-WNDW` (`backend/app/domain/validation/engine.py:143-170`) |
| Rates are synthetic recorded benchmarks; `flat_rate`, `rate_per_mile`, `source='synthetic'` | FR-073 (`03` line 212); `06 §3.8`; DEF-04 (`15` line 752) |
| At most one active rate per raw carrier/origin/destination/equipment | `06 §3.8` partial unique index (line 212) |
| `effective_date` and `expiration_date` are nullable and have no defined selection semantics | `06 §3.8` (lines 205-206) |
| `currency` defaults to USD on both shipments and lane rates | `06 §3.8` line 203; `06 §3.9` line 235 |
| `min_rate` is a nullable numeric with only a `>= 0` CHECK | `06 §3.8` line 202 |
| Candidate `rank`, `total_score`, and `rate_quote` are nullable | `06 §3.14` lines 347, 351-352 |
| `component_scores` is non-null JSONB defaulting to `{}` | `06 §3.14` line 350 |
| `eligibility` is one of `eligible`, `ineligible`, `insufficient_data`; no rate-availability value exists | `06 §3.14` line 348; Appendix A.2 |
| Exactly one active scoring configuration is permitted | `06 §3.19` line 920; `13 §4 PH-4` |
| Eligibility and scoring are deterministic; the LLM cannot change them | ADR-007 (`10` lines 115-118); `11 §6` line 106 |
| `no_eligible_carriers` is defined for zero eligible candidates, not zero ranked candidates | FR-127 (`03` line 244); `07` Node 10 |
| The canonical score-component vocabulary contains six names | Appendix A.2 (`03` line 494) |

### 2.3 Existing decision records

No existing Lead Developer decision record was found. This file is a new record. `docs/10-technology-decisions.md` contains ADR-001 through ADR-020, and `docs/15-architecture-revision-log.md` contains architecture revision findings; neither records the PH-4 business decisions below.

---

## 3. Decision index

### 3.1 Approved decisions

| ID | Title | Status | Classification | Primary follow-up |
|---|---|---|---|---|
| D-014 | Scoring objective | **Approved** | Lead Developer decision | Component formulas still unresolved |
| D-015 | Deferred scoring components | **Approved** | Lead Developer decision | Breakdown representation to be specified |
| D-016 | MVP scoring weights | **Approved** | Lead Developer decision | Formulas still unresolved |
| D-017 | Stored scoring configuration keys | **Approved** | Lead Developer decision | None for storage; API mapping not authorized |
| D-018 | Weight validation | **Approved** | Lead Developer decision | Error-code mapping to be specified |
| D-019 | Ranking tie-break | **Approved** | Lead Developer decision | None |
| D-020 | Scoring precision | **Approved** | Lead Developer decision | Rounding boundary must be documented in implementation |
| D-021 | Candidate persistence | **Approved** | Lead Developer decision | API top-N/nullability representation |
| D-022 | Rate date policy | **Approved with clarification** | Lead Developer decision | As-of date is not persisted in the current schema |
| D-023 | Lane matching | **Approved with clarification** | Lead Developer decision | Normalized-duplicate guards are application-level |
| D-024 | Missing usable rate | **Approved with clarification** | Lead Developer decision | Zero-ranked lifecycle resolved by D-033 Option A |
| D-025 | Minimum rate | **Approved** | Lead Developer decision | Future production semantics still undefined |
| D-026 | Currency matching | **Approved** | Lead Developer decision | Explicit currency required on lane-rate writes |
| D-027 | Candidate universe | **Approved** | Lead Developer decision | MVP policy; not a scalability claim |
| D-028 | Inactive equipment and service-region rows | **Approved** | Lead Developer decision | Fixtures must include active rows for pass cases |
| D-029 | Eligibility precedence and missing-data policy | **Approved** | Lead Developer decision | API representation of `insufficient_data` remains pending |
| D-030 | Filter applicability | **Approved** | Lead Developer decision | None |
| D-031 | Availability | **Approved** | Lead Developer decision | Optional availability columns ignored in MVP |
| D-032 | Insurance validity | **Approved** | Lead Developer decision | Uses D-022 pickup-date convention |
| D-033 | Recommendation lifecycle, including the zero-ranked outcome | **Approved — Option A** | Lead Developer decision, resolved for implementation under project-owner authorization | `no_rankable_candidates` status and matching workflow outcome; see §16A.7 |

### 3.2 Not approved in this record

The following remain unresolved and must not be treated as approved by implication:

- D-035 through D-039 — test harness, lane-rate GET/POST scope, and DS-03/DS-04 fixtures.
- The API contract authorization for lane-rate write behavior (D-036–D-038).

Resolved for implementation under project-owner authorization:

- D-033 — recommendation lifecycle including the zero-ranked outcome (Option A, §16A.7).
- The exact formulas and normalizations for all four active scoring components (§23).
- The API contract representation for null `rank`/`composite_score`/`lane_rate_used`, deferred-component visibility, and eligible-unrankable candidates (`docs/09 §5.5`; §23).

D-034 is outside this record. No status is asserted for it.

D-027 through D-032 are approved in §16A. D-028 and D-032 were unrecorded before Task 004-G; they were explicitly allocated and recorded there. Their allocation is not approval by omission.

---

## 4. D-014 — Scoring objective

| Field | Value |
|---|---|
| Decision ID | D-014 |
| Title | Scoring objective |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- Approved objective: balanced carrier selection, combining operational suitability and commercial competitiveness.
- The MVP composite score uses four components:
  - `equipment_fit`
  - `capacity_timing`
  - `rate_competitiveness`
  - `data_completeness`
- `lane_familiarity` and `reliability` are deferred because the current schema does not provide genuine historical data sources to support them.
- Do not create synthetic reliability scores or use lane-rate records as a lane-familiarity proxy.

**Rationale:** A balanced objective prevents the cheapest carrier from winning automatically and prevents operational fit from being ignored. The four active components are the ones the current schema can support with factual data. The two deferred components have no genuine historical source: the schema contains no reliability history and no lane-familiarity history. Synthesizing them, or using lane rates as a familiarity proxy, would create false commercial evidence.

**Constraints and consequences:**

- Only the four active components participate in the MVP composite score (D-016).
- `lane_familiarity` and `reliability` must not be seeded, synthesized, or proxied. They remain in the canonical vocabulary of Appendix A.2, but not in the MVP arithmetic.
- They must remain visible as unavailable/deferred in the score breakdown (D-015).
- This decision states the objective and component set. It does **not** define any component formula or normalization. Approving D-014 is not approving a scoring formula.
- `rate_competitiveness` depends on the rate-selection rules D-022, D-023, D-024, and D-026; it also depends on the still-unresolved rate formula.

**Source references:**

- Task 004-D §2, D-014 (authority for this record).
- `docs/03` §5.6 FR-121 (rank eligible carriers using the active configuration); Appendix A.2 line 494 (canonical component names).
- `docs/12` §5.3 lines 69-71 (balanced ranking intent; superior rate competitiveness should rank above incomplete/expensive carriers).
- `docs/15` CRIT-03 line 58 (factual rate data; deterministic rate competitiveness).
- Task 004-B §12.3 D-004-B-014/D-004-B-015 (working analysis; superseded where inconsistent with this record).

**Dependencies / follow-ups:**

- Exact formulas and normalizations for `equipment_fit`, `capacity_timing`, `rate_competitiveness`, and `data_completeness`: **unresolved and blocking** (§17).
- D-015 and D-016 record the deferral and weights.

---

## 5. D-015 — Deferred scoring components

| Field | Value |
|---|---|
| Decision ID | D-015 |
| Title | Deferred scoring components |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- `lane_familiarity` is excluded from the MVP composite score.
- `reliability` is excluded from the MVP composite score.
- Both must remain visible as unavailable/deferred in the score breakdown.
- Future activation requires genuine data sources and a revised scoring configuration.

**Rationale:** A component without genuine data would either be constant (adding no signal) or fabricated (adding false signal). Excluding both from the arithmetic prevents invented evidence. Keeping them visible as unavailable/deferred preserves transparency and prevents consumers from assuming the MVP breakdown is complete without them.

**Constraints and consequences:**

- The MVP configuration must not contain `lane_familiarity` or `reliability` keys (D-017).
- The score breakdown must represent both as unavailable/deferred. The exact representation is not specified by this decision; it must not be a numeric score.
- No synthetic reliability score, and no lane-rate-derived familiarity proxy, may be created (D-014).
- Activating either component later requires (a) a genuine data source, and (b) a revised scoring configuration. It is not a seed-only change.
- The canonical six-component vocabulary in Appendix A.2 is unchanged; deferral is an MVP scoring decision, not a vocabulary deletion.
- The current descriptive/evaluation passages that still assume these components conflict with this decision; see R-04 in §19. They must not be used as implementation targets or test oracles.

**Source references:**

- Task 004-D §2, D-015 (authority for this record).
- `docs/03` Appendix A.2 line 494 (canonical component names).
- `docs/06` schema (no reliability or lane-familiarity history table).
- `docs/12` §5.3–5.4 and `docs/08` line 170 (pre-decision prose; conflict R-04).
- Task 004-B §12.3 D-004-B-015.

**Dependencies / follow-ups:**

- Representation of deferred components in `component_scores` and the API: pending API contract authorization.
- Future activation: not authorized; requires a new decision and revised configuration.

---

## 6. D-016 — MVP scoring weights

| Field | Value |
|---|---|
| Decision ID | D-016 |
| Title | MVP scoring weights |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

| Component | Weight |
|---|---:|
| `equipment_fit` | 0.30 |
| `capacity_timing` | 0.25 |
| `rate_competitiveness` | 0.30 |
| `data_completeness` | 0.15 |
| **Total** | **1.00** |

**Rationale:** The weights give equal top priority to equipment fit and rate competitiveness (0.30 each), with capacity/timing next (0.25) and data completeness last (0.15). This expresses the balanced objective: a carrier must be operationally suitable and commercially competitive, not merely cheap. The weights sum exactly to 1.00, so a complete candidate's weighted total is directly comparable on a `[0,1]` scale.

**Constraints and consequences:**

- These are the only MVP weights. They must not be replaced by example values from `docs/09 §5.5`, which is a pre-decision illustration and contains deferred components and an internally inconsistent total.
- The weights are non-negative and sum to 1.00, satisfying D-018.
- The weights do not define the component formulas. A weight of 0.30 for `rate_competitiveness` does not state how a quote maps to a `[0,1]` score.
- The weights are stored in exactly one active scoring configuration (D-017; `06 §3.19`).

**Source references:**

- Task 004-D §2, D-016 (authority for this record).
- Task 004-C §3 approved context (weights and active components).
- `docs/03` FR-121/FR-122; `docs/06 §3.19`; `docs/13 §4 PH-4`.
- Task 004-B D-004-B-016 (working analysis).

**Dependencies / follow-ups:**

- Component formulas: unresolved and blocking.
- D-018 validation; D-020 precision.

---

## 7. D-017 — Stored scoring configuration keys

| Field | Value |
|---|---|
| Decision ID | D-017 |
| Title | Stored scoring configuration keys |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

```json
{
  "equipment_fit": 0.30,
  "capacity_timing": 0.25,
  "rate_competitiveness": 0.30,
  "data_completeness": 0.15
}
```

Use exactly these four unprefixed keys. Do not store deferred components in the MVP configuration.

**Rationale:** One canonical key set removes ambiguity between the unprefixed names used in component scores and any prefixed request fields. Storing only the four active components makes the configuration match the arithmetic actually performed and prevents deferred components from being silently scored.

**Constraints and consequences:**

- Stored keys are exactly `equipment_fit`, `capacity_timing`, `rate_competitiveness`, `data_completeness`.
- No `weight_` prefix is stored.
- `lane_familiarity` and `reliability` must not appear in the MVP configuration.
- Mapping prefixed API fields to canonical keys is a future API concern; it is not authorized here.
- Missing, unknown, or deferred keys are rejected by D-018.

**Source references:**

- Task 004-D §2, D-017 (authority for this record).
- `docs/06 §3.19` (`weights` JSONB).
- `docs/03` Appendix A.2 (unprefixed canonical names).
- Task 004-B D-004-B-017.

**Dependencies / follow-ups:**

- Any interactive scoring-configuration API is Post-MVP (`docs/13 §9`) and is not authorized.

---

## 8. D-018 — Weight validation

| Field | Value |
|---|---|
| Decision ID | D-018 |
| Title | Weight validation |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- All four weights must be nonnegative.
- Their sum must be within `1.000 ± 0.001`.
- Missing, unknown, or deferred component keys must be rejected.
- Invalid configurations must fail validation.
- Never silently normalize invalid weights.

**Rationale:** Validation must reject a configuration rather than repair it. Silent normalization would change the commercial intent without an audit trail. The `0.001` tolerance accommodates decimal representation while still detecting a materially wrong weight set. Rejecting missing, unknown, and deferred keys prevents partial or ambiguous configurations.

**Constraints and consequences:**

- A valid sum lies within the inclusive interval `0.999` to `1.001`.
- Each weight must be `>= 0`.
- The key set must be exactly the four canonical keys in D-017. A missing key, an extra key, a prefixed key, a deferred key, or an unknown key fails validation.
- Invalid configuration causes validation failure; it is not normalized, defaulted, or partially applied.
- `docs/06 §3.19` says the keys "sum to 1.0"; D-018's tolerance is the approved operational tolerance. This is consistent with the approved decision and does not modify the schema.
- The error code or HTTP mapping for an invalid configuration is not specified here. `docs/05 §4.9` says an invalid config makes the recommendation `failed`; the exact API error remains a contract concern.

**Source references:**

- Task 004-D §2, D-018 (authority for this record).
- `docs/06 §3.19`; `docs/09` scoring-configuration validation text (Post-MVP API); `docs/05 §4.9`.
- Task 004-B D-004-B-018.

**Dependencies / follow-ups:**

- Error-code mapping if an API is later authorized.

---

## 9. D-019 — Ranking tie-break

| Field | Value |
|---|---|
| Decision ID | D-019 |
| Title | Ranking tie-break |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

1. `total_score` descending.
2. `carrier_id` ascending when scores are equal.

Do not introduce a price-based tie-break.

**Rationale:** FR-134 requires deterministic ranking. Score descending expresses the ranking objective; `carrier_id` ascending supplies a stable, arbitrary-but-deterministic order when scores are equal. A price-based tie-break would embed a second commercial preference not approved by the weights and would reintroduce the "cheapest wins" behavior the objective rejects.

**Constraints and consequences:**

- Sort key: `(-total_score, carrier_id)`.
- `carrier_id` comparison is deterministic and independent of display name.
- No price, rate, carrier name, created time, or random value may break ties.
- Candidates with null `total_score` are not ranked (D-021/D-024), so they do not participate in this ordering.
- Scores are compared as stored four-decimal values (D-020).

**Source references:**

- Task 004-D §2, D-019 (authority for this record).
- `docs/03` FR-121/FR-134; `docs/05 §4.9` ("deterministic tie-break").
- Task 004-B D-004-B-019.

**Dependencies / follow-ups:**

- None for ordering. Formula approval is still required to produce the scores being ordered.

---

## 10. D-020 — Scoring precision

| Field | Value |
|---|---|
| Decision ID | D-020 |
| Title | Scoring precision |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- Use Python `Decimal`, not binary floating-point arithmetic, for scoring and persistence.
- Normalize component scores to `[0,1]`.
- Store component scores to four decimal places.
- Calculate the weighted total from the stored four-decimal component values.
- Store the total to four decimal places.
- Use `ROUND_HALF_UP`.

Document the rounding boundary explicitly and consistently.

**Rationale:** Decimal arithmetic avoids binary floating-point drift and makes persisted values reproducible. Four decimal places match the `numeric(6,4)` storage. Computing the total from the stored four-decimal component values makes the persisted component breakdown and total internally consistent: a reader can reproduce the total from the stored components. `ROUND_HALF_UP` supplies a single, documented boundary mode.

**Constraints and consequences:**

- No `float` may participate in scoring arithmetic or persistence.
- Component values are normalized to `[0,1]` before storage.
- Each component is rounded to four decimal places using `ROUND_HALF_UP`; the rounding boundary is the fifth decimal digit. For non-negative values, a fifth digit of 5 or greater rounds the fourth digit up.
- The total is the weighted sum of the **stored four-decimal component values**, then rounded to four decimal places with `ROUND_HALF_UP`. It is not computed from unrounded intermediate values.
- The persisted total may therefore differ from a full-precision weighted sum. Tests must assert the approved arithmetic, not a full-precision oracle.
- A missing component under D-024 produces no total; no renormalization is permitted (D-024).
- The implementation must state the rounding boundary in code comments and tests.

**Source references:**

- Task 004-D §2, D-020 (authority for this record).
- `docs/06 §3.14` (`total_score numeric(6,4)`), `docs/06 §2` (numeric money/score convention).
- Task 004-B D-004-B-020.

**Dependencies / follow-ups:**

- Component formulas must define their raw values and normalization before rounding can be applied.

---

## 11. D-021 — Candidate persistence

| Field | Value |
|---|---|
| Decision ID | D-021 |
| Title | Candidate persistence |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- Persist every evaluated candidate, not only the top five.
- Eligible and rankable candidates receive scores and ranks.
- Ineligible and insufficient-data candidates are persisted with null scores and ranks.
- Eligible but unrankable candidates are also persisted with null total score and rank.
- Rank all rankable eligible candidates before applying the response top-N limit.
- Default response limit is five.
- Candidates outside the top five retain their database ranks.

**Rationale:** Persisting every evaluated candidate is auditable and supports explanation, review, and re-sourcing. Limiting only the response keeps the database complete. Separating intrinsic database rank from the response limit prevents the rank of a candidate from changing merely because a different top-N was requested. Persisting eligible-unrankable candidates with nulls makes missing-rate cases visible without inventing a score.

**Constraints and consequences:**

- Persistence scope: every candidate actually evaluated in the recommendation, including ineligible and insufficient-data candidates.
- Ranked candidates: `eligibility = eligible`, a usable rate, a computed `total_score`, and a `rank`.
- Ineligible and insufficient-data candidates: `total_score = NULL`, `rank = NULL`.
- Eligible-unrankable candidates: `eligibility = eligible`, `total_score = NULL`, `rank = NULL`, `rate_quote = NULL`, and an explicit unavailable rate component (D-024).
- All rankable eligible candidates are ranked before the response is truncated to `top_n`.
- Default `top_n` is 5.
- A candidate ranked 6 or lower in the database keeps that rank even when the response returns only 5.
- The response must not renumber ranks based on the requested limit.
- Null score is not zero and must not be sorted as zero (D-024).
- Persisting ineligible candidates does not mean they are eligible or rankable; eligibility remains explicit.

**Source references:**

- Task 004-D §2, D-021 (authority for this record).
- `docs/03` FR-123, FR-132; `docs/07` Node 10; `docs/06 §3.14`.
- `docs/05 §4.9`; Task 004-B D-004-B-021.

**Dependencies / follow-ups:**

- API representation of null `rank`/`composite_score`/`lane_rate_used` and eligible-unrankable candidates: pending contract authorization (§18).
- D-033 for the status when zero candidates are ranked.

---

## 12. D-022 — Rate date policy

| Field | Value |
|---|---|
| Decision ID | D-022 |
| Title | Rate date policy |
| Status | **Approved with clarification** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- Only active lane-rate rows are considered.
- Capture one `as_of_date` per workflow execution.
- Derive it from the UTC calendar date of the shipment's first pickup `window_start`.
- The timestamp must have an unambiguous timezone. Do not silently interpret timezone-naive timestamps.
- A rate is date-valid when:
  - `effective_date <= as_of_date`, when effective date is non-null.
  - `expiration_date >= as_of_date`, when expiration date is non-null.
- Null effective or expiration dates are unbounded.
- Do not fall back to the current evaluation date.
- Do not introduce an automatic rate-expiry job.

**Rationale:** The pickup date is the date on which the rate must actually apply. Using the evaluation date can select a rate that is expired or not yet effective at pickup. Capturing one as-of date per execution prevents results from changing across midnight and makes one execution internally consistent. Inclusive bounds and null-as-unbounded are deterministic and match conventional date-window semantics. Active-only selection prevents historical or replaced rows from being selected. No auto-expiry job is needed because selection already excludes date-invalid rows, and no scheduler exists in the MVP.

**Constraints and consequences:**

- `as_of_date` is captured once, before evaluating any candidate or rate, and reused for the entire execution.
- It is the UTC calendar date of the first pickup stop's `window_start` (the earliest pickup by stop sequence; the first pickup used for FR-026 lane derivation).
- `window_start` must be timezone-aware. A timezone-naive value is a data defect and must not be silently interpreted as UTC, local time, or any other zone.
- Both date comparisons are inclusive: a rate effective on the as-of date is valid; a rate expiring on the as-of date is valid.
- A null `effective_date` has no lower bound; a null `expiration_date` has no upper bound.
- `is_active = false` excludes the row regardless of dates.
- No fallback to the current evaluation date. If the first pickup window is missing, the shipment is not in the validated state expected by the workflow; all rates are unavailable for that execution and the data defect is recorded. Do not invent an as-of date.
- No automatic rate-expiry job, sweep, or background transition is introduced.
- **Schema limitation:** the as-of date is not persisted on the recommendation or candidate. Reproducing a recommendation after the shipment stops change depends on external logs. This is recorded in §18 and this section, not fixed by this task.
- **Operational consequence:** an expired or future-effective active row remains active and occupies the partial-unique-index slot. It is unselectable under D-022 until replaced or deactivated. A second active row with the same raw key cannot be inserted.
- This approval supersedes Task 004-B's working recommendation of an evaluation-date snapshot (D-004-B-022). The approved reference date is the pickup date.

**Source references:**

- Task 004-D §2, D-022 (authority for this record).
- `docs/06 §3.8` lines 205-207 (nullable dates, `is_active`).
- `docs/09 §5.8` lines 550-551 (date example); `docs/07` Node 8; `docs/08` lines 143-145.
- Task 004-C §3, D-022 (analysis and worked examples).
- `backend/app/domain/validation/engine.py` `REQ-WNDW` (pickup window required before validation).

**Dependencies / follow-ups:**

- Persisting the as-of date or a rate snapshot is a future schema decision; not authorized here.
- D-023 and D-026 determine the lane and currency filters applied alongside the date filter.

---

## 13. D-023 — Lane matching

| Field | Value |
|---|---|
| Decision ID | D-023 |
| Title | Lane matching |
| Status | **Approved with clarification** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- Match the persisted shipment origin and destination lane fields.
- Normalize by trimming, collapsing repeated whitespace, normalizing case, and standardizing comma spacing.
- Require exact normalized origin and destination matches.
- Require exact equipment and carrier matching.
- Do not reverse origin and destination.
- Do not use state, metro, hierarchical, geographic, or fuzzy fallback.
- Do not use external geocoding.
- Apply duplicate guards at both write-time and read-time.
- Do not remove meaningful punctuation or infer geographic equivalence.

**Rationale:** The persisted shipment lane fields are the single derivation point for FR-026; re-deriving inside the rate engine would create a second, potentially divergent definition. Normalizing only cosmetic differences (whitespace and case) makes matching robust without inventing geographic equivalence. Exact origin and destination matching, with no reversal and no hierarchy, is deterministic and auditable. The database unique index is on raw strings, so normalized duplicates can exist; explicit write-time and read-time guards are required to avoid arbitrary selection.

**Constraints and consequences:**

- The shipment key is `shipments.lane_origin` and `shipments.lane_destination`. Do not re-derive the lane from stops inside the rate-selection logic.
- Normalization applies to both the shipment lane values and the rate `origin_region` / `destination_region`.
- Normalization rules: trim leading/trailing whitespace; collapse repeated internal whitespace; normalize case for comparison; standardize comma spacing. The implementation must choose and document one deterministic comma-spacing rule; the Task 004-C proposal (no space before a comma, one space after) is an engineering detail consistent with the approved normalization, not a separately approved rule.
- The comparison is case-insensitive after normalization. Stored values are not rewritten by the read path.
- Punctuation that carries meaning is not removed. For example, `St. Louis` and `St Louis` are different normalized keys; abbreviations are not expanded. Seed data must use consistent spelling.
- Origin compares to origin and destination to destination. Reversal never matches.
- Equipment must match exactly (canonical enum), and the rate row must belong to the same carrier.
- No state-only fallback, no metro expansion, no hierarchical or geographic matching, no fuzzy matching, no external geocoding.
- A null shipment lane field matches no rate; this is a D-024 missing-rate outcome, not an eligibility failure.
- **Write-time duplicate guard:** before creating or seeding an active rate, reject a key that normalizes to an existing active key for the same carrier and equipment.
- **Read-time duplicate guard:** if more than one active row survives the lane, date, and currency filters, do not choose arbitrarily; treat the rate as unavailable under D-024 and record a deterministic data-defect reason.
- The database cannot enforce normalized uniqueness with the current raw-string index. The guard is application-level; no migration is authorized by this record.
- **Coverage consequence:** validated shipments have city and state (`REQ-ADDR`), and the current derivation produces `"City, State"`. State-only rate keys such as `IL` cannot match under exact normalized comparison. Synthetic seed rates for scenarios expected to rank must use city-level keys. See R-03.
- The lane-format provenance question remains open (R-02). D-023 approves the matching policy; it does not establish the authority for the `"City, State"` derivation comment.

**Source references:**

- Task 004-D §2, D-023 (authority for this record).
- `docs/03` FR-026 line 169; `docs/06 §3.8` lines 197-198 and 212; `docs/06 §3.9` lines 236-237.
- `backend/app/api/v1/shipments.py:31-56` (`derive_lane_strings`; code evidence only).
- `backend/app/domain/validation/engine.py:143-170` (city/state required).
- Task 004-C §4 (normalization proposal and ambiguity analysis).

**Dependencies / follow-ups:**

- Seed lane-key convention and fixture design (D-039) must follow the city-level consequence.
- Any normalized-key database constraint would be a future schema decision, not authorized here.

---

## 14. D-024 — Missing usable rate

| Field | Value |
|---|---|
| Decision ID | D-024 |
| Title | Missing usable rate |
| Status | **Approved with clarification** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

**Option C is approved.**

When a carrier has no usable matching lane rate:

- Keep the carrier's eligibility result as `eligible`, provided it passes all hard filters.
- Set `rate_quote = NULL`.
- Set the rate component score to explicit null/unavailable.
- Set `total_score = NULL`.
- Set `rank = NULL`.
- Persist the candidate.
- Exclude it from the ranked top-N results.
- Do not redistribute or renormalize the missing rate-component weight.
- Do not invent a neutral rate score.

Important distinction:

`eligible` does not necessarily mean `rankable`.

An eligible carrier without a usable rate is an eligible but unrankable candidate.

**D-024 lifecycle qualification (verbatim):**

Do not approve or implement the proposed `ready` outcome when zero candidates are ranked. That lifecycle decision remains pending D-033.

**Resolution (2026-11-25):** D-033 Option A (§16A.7) resolves this qualification. Eligible-but-zero-rankable recommendations use `no_rankable_candidates`, never `ready`.

**Rationale:** Rate availability is a data-availability condition, not an eligibility filter. The canonical eligibility vocabulary has no "no rate" value, and adding one would create an eighth hard filter. Option C preserves the approved eligibility result, represents the missing quote explicitly, and avoids both fabricated commercial data (a neutral score) and a silent change to the approved weights (renormalization). It also avoids failing an entire recommendation because one carrier lacks a rate.

**Constraints and consequences:**

- A carrier that passes all hard filters remains `eligibility = eligible`, even when no usable rate exists. No rate-related `ineligibility_code` may be added.
- `rate_quote = NULL`.
- `component_scores` must represent `rate_competitiveness` as explicit null/unavailable, not as a numeric score. The exact JSON encoding must be deterministic and documented; it must not be `0`, `0.5`, or any other invented number.
- `total_score = NULL`; `rank = NULL`.
- The candidate is persisted (D-021).
- The candidate is excluded from the ranked top-N. It is not counted as one of the top N ranked candidates.
- No renormalization: the remaining weights are not rescaled. The total is absent, not computed from a partial weight set.
- No neutral rate score.
- `eligible` and `rankable` are distinct. Consumers must not infer rankability from eligibility.
- **Zero-ranked lifecycle outcome (resolved by D-033 Option A):** when eligible candidates exist but none can be ranked, the recommendation status is `no_rankable_candidates`. It is not `ready`, `no_eligible_carriers`, or `failed`. Every evaluated candidate is still persisted with explicit nulls where required.
- No usable rate includes: no row, inactive row, date-invalid row, lane mismatch, normalized-duplicate ambiguity, currency mismatch, and a per-mile-only row that cannot produce a flat quote. All take this same path.
- The per-mile-only case is a derived consequence of the schema, not a separately approved rate policy: no distance field exists and `rate_quote` is a flat total. If a per-mile quote or conversion is intended, it requires a new decision and a distance source.
- A per-mile-only rate must not become a quote. `rate_quote` remains null; no distance calculation is authorized.
- The explanation must state the factual reason without inventing a rate or a competitiveness claim. Template fallback applies.

**Source references:**

- Task 004-D §2, D-024 (authority for this record).
- `docs/03` Appendix A.2 (nine reason codes; no "no rate" code); FR-127 line 244; FR-133 line 250.
- `docs/06 §3.14` lines 347-352 (nullable rank, total, quote; eligibility values).
- `docs/05 §4.9` line 218 (error conditions); `docs/11 §6` line 102 (factual rates); ADR-007.
- Task 004-C §5 (Option C analysis and alternatives).
- Task 004-B D-004-B-024 (working analysis; its renormalization recommendation is superseded by Option C).

**Dependencies / follow-ups:**

- D-033 Option A resolves the zero-ranked recommendation status; no longer blocking.
- API representation of null `rank`, `composite_score`, `lane_rate_used`, and explicit null/unavailable rate component is authorized in `docs/09 §5.5` and §23; no longer blocking for the response implementation.
- D-026 for currency-mismatch availability.

---

## 15. D-025 — Minimum rate

| Field | Value |
|---|---|
| Decision ID | D-025 |
| Title | Minimum rate |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- `min_rate` is metadata only.
- It is not a quote.
- It is not a runtime pricing floor.
- It is not a scoring input.
- Synthetic seed data must maintain `min_rate <= flat_rate` whenever both values are present.

**Rationale:** `min_rate` has no defined business meaning in the contract. It appears only as a nullable column and an API example. Treating it as a floor, a fallback quote, or a scoring input would invent a commercial rule. Metadata-only treatment is the only option that cannot corrupt pricing. The seed invariant keeps synthetic records internally coherent without turning `min_rate` into a runtime rule.

**Constraints and consequences:**

- `min_rate` must never populate `rate_quote`.
- It must never be used in `rate_competitiveness` or any component score.
- It must never be used to rank, filter, or make a carrier eligible/ineligible.
- It must not be applied as a runtime floor or cap to `flat_rate`. Because it is not a floor, the selection logic must not reject or clamp a flat rate based on `min_rate`.
- If a synthetic record has both values, seed validation must enforce `min_rate <= flat_rate`. This is a data-quality rule for synthetic fixtures, not a runtime pricing rule.
- The database has no `min_rate <= flat_rate` CHECK, and this record does not authorize adding one.
- A future production use requires a new decision that defines the meaning, the behavior when `flat_rate < min_rate`, and any schema/API validation. Until then, no behavior may depend on `min_rate`.

**Source references:**

- Task 004-D §2, D-025 (authority for this record).
- `docs/06 §3.8` line 202 (column only); `docs/09 §5.8` line 547 (example only); DEF-04 line 752.
- Task 004-C §6 (analysis).
- Task 004-B D-004-B-025.

**Dependencies / follow-ups:**

- None for MVP behavior. Future production semantics are undefined.

---

## 16. D-026 — Currency matching

| Field | Value |
|---|---|
| Decision ID | D-026 |
| Title | Currency matching |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |

**Decision statement (approved, verbatim):**

- Normalize currency using trimming and uppercase conversion.
- Require exact normalized currency matching.
- A currency mismatch makes the rate unusable for scoring under D-024.
- Currency mismatch does not make the carrier ineligible.
- Do not implement FX conversion.
- Do not treat USD as a wildcard.
- Require explicit currency on lane-rate writes.
- Confirm that the rate currency matches the shipment's explicit comparison currency.

**Rationale:** The schema and contract contain no FX source, rate date, conversion rule, rounding rule, or audit trail. Converting would invent commercial data. Exact matching is deterministic and prevents silent mispricing. A mismatch is a data-availability condition, not an eligibility failure, so it follows D-024. USD is a stored default, not a universal currency.

**Constraints and consequences:**

- Both currency values are normalized by trimming and uppercasing before comparison.
- Matching requires exact equality of the normalized three-letter code.
- A mismatch makes the rate unusable under D-024: `rate_quote = NULL`, rate component explicit null/unavailable, `total_score = NULL`, `rank = NULL`; the carrier remains `eligible`.
- No FX conversion, triangulation, inference, or external provider.
- USD is not a wildcard. A USD rate is not usable for a CAD shipment; a CAD rate is not usable for a USD shipment.
- No silent default at read time. A blank or malformed stored value that does not exactly equal the shipment's normalized currency makes the rate unusable. This record does not add an ISO 4217 validation rule; it records the exact-match consequence.
- Lane-rate writes must require an explicit currency; the schema default is not a substitute for an explicit write value.
- In the current schema, the shipment's explicit comparison currency is `shipments.currency` (not null, default USD). The comparison is against that field. If a future schema introduces a separate comparison currency, a new decision is required.
- The schema default remains a stored value: if a writer omits currency, the database stores USD as documented. The write path should still require an explicit value to avoid accidental defaults.
- No external FX provider, dependency, or network call may be added.

**Source references:**

- Task 004-D §2, D-026 (authority for this record).
- `docs/06 §2` line 22; `docs/06 §3.8` line 203; `docs/06 §3.9` line 235; `docs/09 §2` line 28; `docs/09 §5.8` line 548.
- Task 004-C §7 (analysis).
- Task 004-B D-004-B-026.

**Dependencies / follow-ups:**

- Lane-rate write API (D-036/D-037/D-038) must enforce explicit currency if implemented.
- Any future FX capability requires a new decision and authorization.

---

## 16A. Eligibility policy decisions (D-027–D-033)

This section records the Lead Developer approvals finalized in Task 004-G. D-027 through D-032 are approved. D-033 remains unresolved for the reason stated in §16A.7.

### 16A.1 D-027 — Candidate universe

| Field | Value |
|---|---|
| Decision ID | D-027 |
| Title | Candidate universe |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |
| Dependencies | D-021, D-029, D-030, D-031; FR-090–FR-101 |

**Decision statement (approved):**

- Node 6 loads all carrier records.
- Node 6 applies no equipment and no service-region pre-filter.
- Node 6 applies no status pre-filter.
- Node 7 evaluates the seven hard-filter categories for every loaded carrier.
- Preserve every evaluated candidate and its exclusion reasons.
- Do not silently omit a candidate because it fails a filter.
- This is an MVP policy. It is not a claim that an unlimited candidate query is production-scalable.

**Rationale:** Appendix A.2 defines `equipment_mismatch` and `region_not_served`; a Node 6 equipment or region pre-filter would make those canonical codes unreachable. FR-101 requires persisting eligibility results per candidate, and FR-090 requires the deterministic hard filters to decide eligibility. A full carrier universe is the only candidate set that produces every canonical outcome consistently. Performance is a separate future concern and must not be addressed by adding a hard filter.

**Constraints and consequences:**

- The initial carrier query has no `WHERE` predicate on status, equipment, region, availability, insurance, or rates.
- Child rows are loaded without inner joins that would drop carriers with no child records.
- Iteration order must be deterministic (for example, `carriers.id` ascending).
- No pagination, `LIMIT`, or threshold is approved by this decision.
- A future scale bound requires a new decision and must not be one of the seven hard filters.
- `docs/07` Node 6 is clarified to match this decision; the 16-node workflow structure is unchanged.

**Source references:**

- Task 004-E §4 and §11.1; Task 004-F §2–§3; Task 004-G §3 and §6.
- `docs/07` Node 6 and Node 7; `docs/03` FR-090–FR-101 and Appendix A.2.
- `docs/06 §3.14` candidate persistence constraints.

**Dependencies / follow-ups:**

- D-029, D-030, and D-031 define how Node 7 evaluates each category.
- A separate documentation task must keep Node 6 and any workflow diagrams consistent if they are revised again.

---

### 16A.2 D-028 — Inactive equipment and service-region rows

| Field | Value |
|---|---|
| Decision ID | D-028 |
| Title | Inactive equipment and service-region rows |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |
| Dependencies | D-027, D-029 |

**ID allocation note:** D-028 was unrecorded before Task 004-G. This decision explicitly allocates the ID to inactive equipment and service-region rows. No existing decision scope is displaced or changed. The allocation is not approval by omission.

**Decision statement (approved):**

- Ignore inactive `carrier_equipment_types` and `carrier_service_regions` records for matching and for existence.
- If active records exist but none match the shipment, evaluate the corresponding known failure: `equipment_mismatch` or `region_not_served`.
- If no active records exist at all, classify the relevant filter as unknown and include `missing_data`.
- Apply the same rule independently to the equipment filter and the service-region filter.
- No split into two decision IDs is required: the rule is one policy applied to two relationship tables.

**Rationale:** Inactive rows represent retired capabilities and must not satisfy a current filter. Treating an inactive row as a known mismatch would conflate "retired" with "known non-coverage." Treating the absence of active rows as a mismatch would violate FR-099's distinction between missing data and a known negative. The same existence-versus-match logic applies to both relationship tables.

**Constraints and consequences:**

- An inactive row is never used to pass a filter.
- An inactive row is never used by itself to establish a known failure.
- Active rows establish the comparison set. If that set is non-empty and has no match, the failure is known.
- If the active set is empty, the result is unknown and `missing_data` is added under D-029.
- Seed fixtures must include active equipment and region rows for carriers intended to pass.

**Source references:**

- Task 004-E §3.3–§3.4 and §11.2; Task 004-F §4.3; Task 004-G §4.
- `docs/06 §3.5–§3.6` (`is_active`, unique constraints).
- `docs/03` FR-091, FR-092, FR-099.

**Dependencies / follow-ups:**

- D-027 ensures carriers with no active rows are still loaded and evaluated.
- D-029 defines the `missing_data` code and precedence.

---

### 16A.3 D-029 — Eligibility precedence and missing-data policy

| Field | Value |
|---|---|
| Decision ID | D-029 |
| Title | Eligibility precedence and missing-data policy |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |
| Dependencies | D-027, D-028, D-030, D-031, D-032; D-021, D-024 |

**Decision statement (approved):**

1. Any known applicable hard-filter failure produces `ineligible`.
2. Otherwise, any required unknown information produces `insufficient_data`.
3. Otherwise, the candidate is `eligible`.
4. Preserve all independently established failure codes.
5. Add `missing_data` when required information is unknown.
6. Deduplicate reason codes.
7. Sort reason codes deterministically in the canonical Appendix A.2 order.
8. A known failure takes precedence over missing information when determining eligibility.

**Operational rules:**

- Evaluate every applicable filter; do not short-circuit the reported code set.
- If any applicable filter fails, `eligibility = ineligible`, even if another applicable filter is unknown.
- If no applicable filter fails and at least one is unknown, `eligibility = insufficient_data`.
- If all applicable filters pass, `eligibility = eligible`.
- `missing_data` accompanies failure codes on an `ineligible` candidate. The `eligibility` column, not the presence of `missing_data`, states the classification.
- An `insufficient_data` candidate's code array contains only `missing_data` unless a failure also exists, in which case the candidate is `ineligible`.
- An `eligible` candidate's code array is empty.
- Codes are stored only as canonical codes. Human-readable prose is not a substitute.
- A missing usable lane rate is not an eligibility failure (D-024). The candidate remains `eligible` and becomes unrankable.

**Required-information rules:**

- Active equipment rows and active evaluable service-region rows are required to distinguish a known mismatch from missing capability data.
- `insurance_expiry_date` is required to evaluate insurance; null is unknown.
- Absence of availability rows is a known failure under FR-093, not missing data.
- `carriers.status`, `hazmat_authorized`, and `temperature_capable` are NOT NULL in the schema; they do not produce missing data. A schema violation is a data defect.
- The unknown set is limited to applicable filters. A non-applicable filter contributes no unknown.

**Canonical code order:** `equipment_mismatch`, `region_not_served`, `no_capacity`, `insurance_expired`, `carrier_inactive`, `carrier_suspended`, `hazmat_not_authorized`, `temperature_not_supported`, `missing_data`.

**Rationale:** A known failure is definitive. Allowing missing information to outrank it would make an unusable carrier appear potentially usable. Retaining every failure code plus `missing_data` gives an order-independent audit and preserves the factual data gap without changing the classification. Appendix A.2 order prevents a second, invented vocabulary ordering.

**Constraints and consequences:**

- An ineligible candidate may carry `missing_data` alongside failure codes.
- No new eligibility value and no new reason code are introduced.
- `ineligibility_codes text[]` supports multiple codes; no schema change is required.
- Consumers must read `eligibility` to determine classification.

**Source references:**

- Task 004-E §5–§7 and §11.3; Task 004-F §4; Task 004-G §3.
- `docs/03` FR-090, FR-098–FR-101, Appendix A.2 line 493.
- `docs/06 §3.14` (`eligibility`, `ineligibility_codes`).

**Dependencies / follow-ups:**

- API representation of `insufficient_data` candidates remains a contract/API decision (§18, A-11 and the `insufficient_data` placement gap).
- D-032 supplies the insurance null rule.

---

### 16A.4 D-030 — Filter applicability

| Field | Value |
|---|---|
| Decision ID | D-030 |
| Title | Filter applicability |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |
| Dependencies | D-029 |

**Decision statement (approved):**

- Hazmat authorization is checked only when the shipment requires hazmat handling.
- Temperature capability is checked only when the shipment requires temperature-controlled transport.
- A non-applicable filter produces no exclusion code and no `missing_data`.
- Do not invent additional applicability conditions.

**Trigger rules:**

- Hazmat is applicable only when `shipments.requirements.hazmat` is the JSON boolean `true`. `false`, an absent key, or `null` is not a requirement.
- Temperature is applicable only when `shipments.requirements.temperature_range` expresses a temperature requirement: an object with at least one numeric `min_f` or `max_f`. An absent key, `null`, an empty object, or an object with no numeric bound is not a requirement.
- Do not infer a requirement from `equipment_type` alone. In particular, do not treat `reefer` equipment as a temperature requirement when no range is recorded.
- When applicable, carrier `false` is a known failure: `hazmat_not_authorized` or `temperature_not_supported`. Carrier `true` passes.
- Carrier booleans are NOT NULL; a null value is a schema/data defect and must not be coerced to pass.
- A malformed shipment requirement value is a shipment defect; fail the run safely rather than marking carriers ineligible.

**Rationale:** The canonical requirement keys express the shipment's need. Boolean coercion or equipment-type inference would create a requirement the shipment did not state. A non-applicable check cannot be missing, so it must not add `missing_data`.

**Source references:**

- Task 004-E §3.7–§3.8 and §11.4; Task 004-F §5.3; Task 004-G §3.
- `docs/03` FR-096, FR-097, Appendix A.2 requirement keys.
- `docs/06 §3.4` (`hazmat_authorized`, `temperature_capable`).

---

### 16A.5 D-031 — Availability

| Field | Value |
|---|---|
| Decision ID | D-031 |
| Title | Availability |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |
| Dependencies | D-022, D-029 |

**Decision statement (approved):**

- Use the first pickup window.
- Compare timestamps in UTC.
- Use inclusive any-overlap semantics.
- No availability rows produce `no_capacity`.
- Availability rows with no overlapping window produce `no_capacity`.
- Ignore optional availability columns whose semantics are undefined in the MVP.
- Do not invent constraints for those optional fields.

**Operational rules:**

- The shipment window is `[window_start, window_end]` of the first pickup stop (lowest stop `sequence`).
- Pass iff at least one row satisfies `available_from <= pickup.window_end AND available_until >= pickup.window_start`.
- Compare absolute instants; both availability columns and the pickup window are timezone-aware.
- Do not use the current evaluation time.
- `origin_region`, `destination_region`, and `equipment_type` on `carrier_availability` are ignored whether null or populated. They do not pass, fail, or produce `missing_data`.
- Availability is carrier-wide in the MVP, not lane-specific.
- A timezone-naive stored timestamp is a data defect and must not be silently interpreted as UTC or local time.

**Rationale:** Any overlap is the least restrictive deterministic reading of recorded capacity and does not require the carrier to be free for the entire customer window. FR-093 makes absence of a window a known failure, so it is not `insufficient_data`. The optional columns have no defined matching semantics and no normalization rule; inventing one would create unauthorized constraints.

**Constraints and consequences:**

- No availability rows and no overlap are both `no_capacity`.
- No missing-data outcome exists for availability.
- Lane-specific availability requires a separate future decision and a normalization definition.
- Non-state service-region matching remains a separate unresolved question; it is not part of D-031.

**Source references:**

- Task 004-E §3.5 and §11.5; Task 004-F §5.1; Task 004-G §3.
- `docs/03` FR-093.
- `docs/06 §3.7` and §3.10 (availability and stop windows).

---

### 16A.6 D-032 — Insurance validity

| Field | Value |
|---|---|
| Decision ID | D-032 |
| Title | Insurance validity |
| Status | **Approved** |
| Classification | Lead Developer-approved decision |
| Authority | Lead Developer |
| Recorded | 2026-11-25 |
| Dependencies | D-022, D-029 |

**ID allocation note:** D-032 was unrecorded before Task 004-G. This decision explicitly allocates the ID to insurance validity. No existing decision scope is displaced or changed. The allocation is not approval by omission.

**Decision statement (approved):**

- Insurance expiration before the first pickup date produces `insurance_expired`.
- Expiration equal to the pickup date is valid.
- Expiration after the pickup date is valid.
- A null expiration date produces `insufficient_data` and `missing_data`.
- No separate insurance record exists in the current schema; use `carriers.insurance_expiry_date`.

**Operational rules:**

- The pickup date is the UTC calendar date of the first pickup stop's `window_start`, consistent with the approved D-022 date convention.
- The comparison is inclusive: coverage is valid through the expiry date.
- A null expiry is not expired. It is an absent required value under D-029.
- Do not substitute the current date, `last_verified_at`, or `authority_status_recorded`.
- A carrier without a carrier row is not a candidate; there is no separate insurance row to be missing.

**Rationale:** FR-095 requires a recorded validity check against the pickup date. Before the date is expired; equal to and after the date are valid under an inclusive reading consistent with D-022. A null is not a recorded expiry and cannot establish failure. The schema has only the carrier column, so no separate-record semantics are invented.

**Source references:**

- Task 004-E §3.6 and §11; Task 004-F §5.2; Task 004-G §4.
- `docs/03` FR-095.
- `docs/06 §3.4` (`insurance_expiry_date` nullable).
- `docs/16` D-022 (date convention).

**Dependencies / follow-ups:**

- D-029 records the null-as-unknown and `missing_data` rules.
- Any future insurance history table or external verification requires a new decision.

---

### 16A.7 D-033 — Recommendation lifecycle (resolved: Option A)

| Field | Value |
|---|---|
| Decision ID | D-033 |
| Title | Recommendation lifecycle, including the zero-ranked outcome |
| Status | **Approved — Option A**, resolved for implementation under the project-owner end-to-end authorization |
| Classification | Lead Developer decision |
| Authority | Lead Developer; implementation resolution recorded 2026-11-25 |
| Recorded | 2026-11-25 |
| Dependencies | D-021, D-024; FR-120, FR-127 |

**Decision statement (Option A):**

When a completed recommendation has one or more eligible candidates but zero rankable candidates, persist it with the new canonical status `no_rankable_candidates`. Add `no_rankable_candidates` to Appendix A.2 recommendation statuses, the `recommendations.status` CHECK constraint, and the workflow outcome vocabulary. Do not use `ready`, `no_eligible_carriers`, or `failed` for this case.

**Resolved lifecycle:**

| Situation | Recommendation status | Workflow outcome | Basis |
|---|---|---|---|
| At least one candidate is eligible and rankable | `ready` with ranked candidates | approval path, then `approved` / `rejected` / `changes_requested` | FR-120, FR-121, FR-123 |
| All evaluated candidates are ineligible | `no_eligible_carriers` | `no_eligible_carriers` | FR-127 (zero eligible candidates) |
| All evaluated candidates are `insufficient_data` | `no_eligible_carriers` | `no_eligible_carriers` | FR-127 (zero eligible candidates) |
| No carrier records exist | `no_eligible_carriers` | `no_eligible_carriers` | FR-127 (zero candidates) |
| Eligible candidates exist but none are rankable | `no_rankable_candidates` | `no_rankable_candidates` | D-024 plus this decision |

**Rationale:** Each status states the actual business result. Option A requires no new outcome column, preserves every evaluated candidate, and makes the zero-ranked path auditable without reusing a status whose definition it does not satisfy. It is implemented as a completed business outcome, not a system failure.

**Constraints and consequences:**

- `ready` requires at least one rankable candidate. It is never used for zero ranked candidates.
- `no_eligible_carriers` requires zero eligible candidates. It is never used when eligible candidates exist.
- `failed` describes an execution failure only; eligible-but-unrankable is not `failed`.
- Every evaluated candidate remains persisted (D-021). Eligible-unrankable candidates keep `rank = NULL`, `total_score = NULL`, and explicit null `rate_competitiveness` (D-024).
- No approval interrupt is created for `no_eligible_carriers` or `no_rankable_candidates`; both complete through Node 14 (`workflow.completed`) and Node 15.
- The workflow outcome is stored in `workflow_executions.state`; no schema change is required for the outcome vocabulary.
- The recommendation status CHECK is updated by migration `4b1f7c9d2e30`; downgrade refuses to rewrite audited rows.

**Implemented contract surfaces:**

- `docs/03` Appendix A.2 and FR-127 note.
- `docs/06 §3.13` and §3.14 component encoding note.
- `docs/07` Nodes 8, 10, 14 and §7.1 conditional-edge rule.
- `docs/09 §5.5` lifecycle and nullability note.
- `backend/app/domain/scoring/engine.py`, `backend/app/services/recommendations.py`, and regression tests.

**Source references:**

- `docs/03` FR-120, FR-124, FR-127; Appendix A.2 recommendation statuses.
- `docs/06 §3.13` (`recommendations.status`, no outcome field).
- `docs/07` Node 8, Node 10, Node 14.
- `docs/16` D-021, D-024, §2.2, §18 A-11.
- Task 004-F §6.4 and §7; Task 004-G §5.

---

## 17. Unresolved decisions and blockers

The following are **not approved** by this record. They must be resolved before the dependent work is implemented.

### 17.1 Blocking business decisions

| ID | Topic | Why it blocks | Current status |
|---|---|---|---|
| D-033 | Recommendation lifecycle, including the zero-ranked outcome | Option A adds `no_rankable_candidates` and a matching workflow outcome. See §16A.7. | **Resolved — Option A** |
| — | Exact formulas and normalizations for `equipment_fit`, `capacity_timing`, `rate_competitiveness`, and `data_completeness` | Implemented for the MVP with documented, deterministic assumptions in §23. | **Resolved for implementation (§23)** |

### 17.2 Blocking contract/API decisions

| ID | Topic | Why it blocks | Current status |
|---|---|---|---|
| — | Nullable `rank`, `composite_score`, `lane_rate_used` in the API schema | Authorized by the `docs/09 §5.5` lifecycle/nullability note. | **Authorized** |
| — | Eligible-unrankable candidates in `candidates` | Authorized: remain in `candidates` with null rank/score, never in `ineligible_candidates`. | **Authorized** |
| — | Explicit null/unavailable rate component encoding | Authorized: explicit JSON null in `component_scores.rate_competitiveness`; DB stores null. | **Authorized** |
| — | Deferred-component visibility in the breakdown | Authorized: explicit nulls for `lane_familiarity` and `reliability`. | **Authorized** |
| — | Zero-ranked recommendation status | Resolved by D-033 Option A: `no_rankable_candidates`. | **Resolved** |

### 17.3 Test, scope, and fixture decisions

| ID | Topic | Why it matters | Current status |
|---|---|---|---|
| D-035 | Null `workflow_execution_id` in PH-4 tests | PH-4 cannot be tested through the PH-5 workflow trigger without a decision. | Unresolved |
| D-036 | Lane-rate GET scope (active vs historical) | R-01 conflict; affects the read API. | Unresolved |
| D-037 | POST lane-rate conflict behavior | Determines duplicate-active handling. | Unresolved |
| D-038 | Lane-rate endpoints as PH-3 prerequisite vs PH-4 work | Phase sequencing; rate scoring needs a way to create/seed rates. | Unresolved |
| D-039 | DS-03/DS-04 fixtures and EV-05 baseline | Ranked scenarios need city-level rates and approved formulas. | Unresolved |

### 17.4 Decisions not addressed

D-034 is not recorded here. This document asserts no status for it and it must not be treated as approved by omission. D-028 and D-032 were unrecorded before Task 004-G; they are now explicitly allocated and approved in §16A.2 and §16A.6. That allocation is not approval by omission.

### 17.5 Explicit non-implications

- Approving D-016 does not approve a scoring formula.
- Approving D-021 does not approve the `ready` zero-ranked status.
- Approving D-022 does not approve persisting the as-of date.
- Approving D-023 does not approve a normalized-key database constraint or a state/metro fallback.
- Approving D-024 does not approve renormalization, a neutral score, or a new eligibility code.
- Approving D-026 does not approve FX conversion or a USD wildcard.
- Approving D-027 does not approve unlimited production-scale queries or pagination.
- Approving D-028 does not approve using inactive rows to pass a filter.
- Approving D-029 does not approve the API representation of `insufficient_data`.
- Approving D-031 does not approve lane-specific availability or non-state region matching.
- Approving D-032 does not approve external insurance verification or a separate insurance record.

---

## 18. API contract implications

These are required implications of the approved decisions. **Task 004-H update:** A-01 through A-11 are authorized by the `docs/09 §5.5` lifecycle/nullability note and §23; their row-level "Pending" markers below preserve the pre-implementation record. A-12 (lane-rate write behavior) remains pending D-036–D-038.

| # | Implication | Basis | Current contract state | Authorization status |
|---|---|---|---|---|
| A-01 | `rank` may be `null`. | D-021, D-024; `06 §3.14` nullable rank | Example shows an integer; nullability not stated in the response schema | **Pending** |
| A-02 | `composite_score` may be `null`. | D-021, D-024; `total_score` nullable | Example shows `0.885`; nullability not stated | **Pending** |
| A-03 | `lane_rate_used` may be `null`. | D-024; derived from nullable `rate_quote`; no separate DB column | Example shows `2050.00`; nullability not stated | **Pending** |
| A-04 | Eligible-unrankable candidates remain in `candidates`. | D-021, D-024 | `candidates` and `ineligible_candidates` exist, but the eligible-unrankable case is not described | **Pending** |
| A-05 | Eligibility status and rankability are represented separately. | D-024 ("eligible does not necessarily mean rankable") | Only `eligibility_status` and `rank` are shown; no explicit rankability indicator | **Pending** |
| A-06 | A null score is not zero. | D-021, D-024 | Not stated | **Pending** |
| A-07 | A missing rate is not represented as carrier ineligibility. | D-024; no rate reason code in Appendix A.2 | Not stated | **Pending** |
| A-08 | The response top-N counts only ranked candidates. | D-021 | Top-N is stated, but the eligibility/rank interaction is not | **Pending** |
| A-09 | `component_scores` may contain an explicit null/unavailable rate component. | D-024 | Example uses numeric values only | **Pending** |
| A-10 | `lane_familiarity` and `reliability` appear as unavailable/deferred. | D-015 | Example shows numeric values, conflicting with D-015 | **Pending** |
| A-11 | The zero-ranked recommendation status is not defined. | D-024 lifecycle qualification; D-033 pending | `ready` and `no_eligible_carriers` only | **Blocked by D-033** |
| A-12 | Lane-rate writes require explicit currency. | D-026 | Example includes `currency`; explicit-requirement text not stated | **Pending** |

**Semantic rules that require no schema change:**

- A null `rank` means the candidate was not rankable; it does not mean rank zero.
- A null `composite_score` means no total was computed; it does not mean a zero score.
- A null `lane_rate_used` means no usable recorded rate was selected; it does not mean a free or zero rate.
- A missing rate never changes `eligibility` from `eligible` to `ineligible` and never adds an ineligibility code.
- An eligible-unrankable candidate must not be moved into `ineligible_candidates`.

**Deferred-component visibility:** D-015 requires both deferred components to be visible as unavailable/deferred in the score breakdown. The API contract must define the representation. It must not present them as numeric scores or omit them silently.

---

## 19. Existing conflicts

These conflicts are recorded for resolution. No source document was modified when this record was first created. Task 004-G later modified only the Node 6 description in `docs/07`; R-01 through R-04 remain unfixed.

| ID | Conflict | Affected documents | Required resolution | Status |
|---|---|---|---|---|
| **R-01** | Lane-rate GET is described as "active and historical", while historical records are deferred beyond MVP. | `docs/09 §5.8` line 532 ("active and historical") vs line 554 ("Time-series historical rate analytics are deferred to Post-MVP"); `docs/06 §3.8` line 212 ("historical rate records deferred to Post-MVP"); `docs/08` lines 143-144 ("historical & synthetic") and line 170 | By precedence (`03 §1.2`: `06` schema truth over `09` wire truth over descriptive prose), MVP selects and serves active rows only. D-022 selects active rows only. The final GET scope is D-036. Correcting the `docs/09`/`docs/08` prose requires separate documentation authorization. | Recorded; D-036 pending |
| **R-02** | The lane-format decision is supported only by a code docstring. | `backend/app/api/v1/shipments.py:33` cites "Approved Decision 3"; no such decision was found in `docs/03`, `docs/06`, `docs/09`, `docs/13`, or the Task 004-A/B/C reports. FR-026 defines derivation from first pickup/last delivery but not the string format. | The code is evidence, not approval. D-023 governs matching and uses the persisted lane fields; it does not establish the authority for the `"City, State"` derivation. The authoritative source must be identified, or the format must be formally documented, by a separate decision. Until then, no document may cite "Approved Decision 3" as approved. | Recorded; source not found |
| **R-03** | State-only rate keys may be unreachable for validated shipment lanes. | `docs/06 §3.8` lines 197-198 (examples `IL`, `TX`, `Chicago, IL`, `Dallas, TX`); `docs/09 §5.8` lines 542-543 (example `IL`, `TX`); `docs/03` FR-026 line 169; validation `REQ-ADDR`; `derive_lane_strings` | This is not a schema contradiction. Under D-023's exact normalized matching, `IL` cannot equal `City, State`. State-only rows remain valid data but cannot match validated shipments. Synthetic seed rates for scenarios expected to rank must use city-level keys. If state-level matching is intended, that requires a new matching decision, not a silent fallback. | Recorded; seed consequence |
| **R-04** | Several documents still describe `lane_familiarity` and/or `reliability` as active scoring components, and some omit `data_completeness`. | `docs/08` line 170 (rate competitiveness, lane familiarity, equipment fit, reliability, timing); `docs/13 §4 PH-4` line 92 (rate competitiveness, lane familiarity, equipment fit, reliability, capacity timing); `docs/12 §5.3` lines 69-71 and §5.4 line 74 (lane familiarity/reliability assumptions); `docs/09 §5.5` lines 369-376 (numeric `lane_familiarity: 0.90`, `reliability: 0.98`) | D-014, D-015, D-016, and D-017 govern. Those passages are pre-decision descriptive/evaluation prose or illustrative examples. They must not be used as implementation targets, seed values, or test oracles. The canonical vocabulary in Appendix A.2 still contains six names; the MVP configuration contains four. Updating the affected documents requires separate documentation authorization. | Recorded; D-014–017 govern |

**Not a conflict:** Appendix A.2's six canonical component names remain valid vocabulary. D-015 defers two from the MVP score; it does not delete them from the canonical enumeration.

**Not resolved here:** None of R-01 through R-04 is fixed by this record. The source documents remain as they were.

---

## 20. Traceability to prior working reports

The working reports used `D-004-B-0NN` identifiers. This record uses the canonical IDs assigned by Task 004-D and Task 004-G. The numeric suffix correspondence is intentional where it exists, but the **final decision content controls**.

| Canonical ID | Prior working reference | Relationship |
|---|---|---|
| D-014 | D-004-B-014 | D-014 records the approved scoring objective. It does **not** resolve D-004-B-014's component-formula question, which remains open. |
| D-015 | D-004-B-015 | D-015 resolves the reliability/lane-familiarity deferral. |
| D-016 | D-004-B-016 | D-016 records the approved weights. |
| D-017 | D-004-B-017 | D-017 records the canonical stored keys. |
| D-018 | D-004-B-018 | D-018 records the validation rules. |
| D-019 | D-004-B-019 | D-019 records the tie-break. |
| D-020 | D-004-B-020 | D-020 records precision and rounding. |
| D-021 | D-004-B-021 | D-021 records persistence scope and top-N behavior. |
| D-022 | D-004-B-022; Task 004-C D-022 | The final approval uses the pickup date. Task 004-B's working recommendation of an evaluation-date snapshot is superseded. |
| D-023 | D-004-B-023; Task 004-C D-023 | The final approval adopts normalized exact matching with duplicate guards. |
| D-024 | D-004-B-024; Task 004-C D-024 | The final approval adopts Option C. Task 004-B's renormalization recommendation is superseded. |
| D-025 | D-004-B-025; Task 004-C D-025 | The final approval adopts metadata-only treatment. |
| D-026 | D-004-B-026; Task 004-C D-026 | The final approval adopts exact currency matching. |
| D-027 | Task 004-E; Task 004-F | The final approval adopts the all-carrier candidate universe and clarifies Node 6. |
| D-028 | Task 004-E NEW-A; Task 004-F NEW-A | The ID was unrecorded; Task 004-G explicitly allocates it to inactive equipment/service-region rows. |
| D-029 | Task 004-E; Task 004-F | The final approval adopts failure-over-unknown precedence and full code accumulation. |
| D-030 | Task 004-E; Task 004-F | The final approval adopts strict shipment-requirement applicability. |
| D-031 | Task 004-E; Task 004-F | The final approval adopts inclusive any-overlap in UTC and ignores undefined optional fields. |
| D-032 | Task 004-E NEW-B; Task 004-F NEW-B | The ID was unrecorded; Task 004-G explicitly allocates it to insurance validity. |
| D-033 | Task 004-E; Task 004-F; Task 004-G | Remains unresolved; see §16A.7. |

**Numbering note:** Task 004-B line 673 says currency mismatch is "handled by D-025". That is a working-report numbering error; in this record, D-025 is `min_rate` and D-026 is currency. The canonical IDs in this record control.

**Conflict rule:** If Task 004-B or Task 004-C conflicts with this record on D-014 through D-026, this record governs. Their evidence and worked examples remain useful, but their recommendations do not override an approved decision.

---

## 21. Implementation gate

> **Historical gate (superseded for this build).** The project owner authorized end-to-end implementation on 2026-11-25. D-033 and the four component formulas are resolved in §16A.7 and §23; API implications A-01 through A-11 are authorized in `docs/09 §5.5`. The text below records the pre-implementation gate and is retained for traceability.

This record grants **no implementation authorization**.

Before any PH-4 implementation that depends on these decisions:

1. The four active component formulas and normalizations must be approved (D-014/D-016 follow-up).
2. D-027 through D-032 are approved (§16A); no further eligibility decision is required for their scope.
3. D-033 remains unresolved. Do not implement any zero-ranked recommendation outcome until it is decided.
4. Non-state service-region matching remains unresolved.
5. The API contract implications in §18 must be authorized, including `insufficient_data` and eligible-unrankable placement.
6. D-035 through D-039 must be resolved for the test harness, lane-rate API scope, and fixtures.
7. A separate implementation task must be authorized by the Lead Developer.

Until then:

- Do not write rate-selection code.
- Do not write scoring code.
- Do not seed deferred components.
- Do not implement a zero-ranked recommendation status.
- Do not modify API schemas, models, migrations, tests, or scoring formulas.
- Do not start PH-4 or PH-5 implementation.

---

## 22. Integrity and document control

| Check | Result |
|---|---|
| Document path | `docs/16-lead-developer-decision-record.md` |
| Document status | Active record; updated by Task 004-H to resolve D-033 (Option A), record the component formulas, and authorize the API representation |
| Source documents modified | Task 004-H updated `docs/03` Appendix A.2/FR-127, `docs/06` §3.13/§3.14, `docs/07` Nodes 8/10/14/§7.1, `docs/09` §5.5, and this record. |
| Approvals recorded | D-027 through D-033 approved; D-033 resolved by Option A |
| Unrecorded decision IDs | D-034 only |
| Source code, tests, models, migrations, API implementations, or schemas modified | Task 004-H: scoring engine, recommendation persistence, recommendation-status migration, and tests. API/UI wiring follows in later milestones. |
| Dependencies installed | None added by Task 004-H |
| `.gitignore` modified | No |
| Commits created or pushed | See Git history; no push performed. |
| PH-4 or PH-5 implementation started | PH-4 M1–M3 committed; M4 scoring/persistence implemented under project-owner authorization |
| `docs/14-architecture-review.md` SHA-256 | `9F61632E941B9E06E47EF7F6E2E38C56D97E63E56B7BB76687D605A710182FE4` (verified before and after) |
| Branch | `main` |
| HEAD | See Git history; Task 004-H commit is created after the full test suite passes |
| Staged changes | Milestone-scoped files only |
| Expected working-tree change | This record, the Task 004-H contract clarifications, scoring/recommendation code, migration, and tests |

**Documentation follow-ups requiring separate authorization:**

- Update `docs/README.md` to index this record. It was not modified here.
- Correct the R-01, R-02, R-03, and R-04 source passages. They were not modified here.
- Record the as-of date / rate provenance schema limitation and any future migration. Not authorized here.
- Approve or reject the API implications in §18. Not authorized here.

---

## 23. Task 004-H implementation decisions (project-owner authorized)

These decisions make the approved scoring objective implementable. They are deterministic, test-covered implementation rules adopted under the project-owner end-to-end authorization. They do not add carrier facts, reliability history, or fabrication.

### 23.1 Active component formulas

All component values are Decimal, quantized to four decimal places with `ROUND_HALF_UP`, and clamped to `[0, 1]` unless explicitly null.

| Component | Formula | Missing-data rule |
|---|---|---|
| `equipment_fit` | Mean of the applicable verified dimensions: `min(1, matched_equipment.max_weight_lbs / shipment.weight_lbs)` when both are positive, and `1` if the matched equipment's `trailer_lengths_ft` contains the shipment's numeric `requirements.trailer_length_ft`, otherwise `0`. | If no dimension applies (no cargo weight and no trailer requirement), return `1.0000`: the equipment-type hard gate already passed and is the only applicable fit evidence. Missing facts are penalized separately by `data_completeness`; they are not fabricated. A present trailer requirement with missing/empty trailer data scores `0` for that dimension. |
| `capacity_timing` | For each availability row, `overlap = max(0, min(pickup_end, available_until) - max(pickup_start, available_from)) / (pickup_end - pickup_start)`; take the maximum across rows. For a zero-duration pickup window, use inclusive containment (`1` if `available_from <= pickup_start <= available_until`, else `0`). | Missing pickup window or no usable availability row returns `0.0000`. Eligibility already requires an overlapping window; this component grades the degree of overlap, including boundary-touch (`0.0000` for a positive-duration window). |
| `rate_competitiveness` | With a usable flat quote and a non-null maximum buy rate: `(max_buy_rate - rate_quote) / max_buy_rate`, clamped to `[0, 1]`. If `max_buy_rate == 0`, return `1` only when the quote is `0`, otherwise `0`. | No usable matching rate, or no maximum buy ceiling, returns explicit `NULL` (never `0` or a neutral value). The composite is not computed, weights are not renormalized, and the candidate is unrankable (D-024). |
| `data_completeness` | Present recorded fields divided by applicable denominator. Base fields: `mc_number`, `dot_number`, `authority_status_recorded`, `insurance_expiry_date`, `primary_contact_name`, `primary_contact_email`, `primary_contact_phone` (7). Add matched `equipment.max_weight_lbs` (8). Add matched equipment `trailer_lengths_ft` only when a numeric trailer requirement applies (9). | Null or whitespace-only values are missing. This measures record completeness only, never carrier performance, reliability, or history. |

### 23.2 Composite and ranking

- The composite is `sum(weight[name] * component[name])` over the four active components, using the stored four-decimal component values, then quantized to four decimals with `ROUND_HALF_UP`.
- Weights come from the active `scoring_configs.weights`. If a key is absent, the approved default is used; weights are never renormalized because a component is null.
- Every rankable candidate receives a rank, not only the top five. Ranking is total descending, then `carrier_id` ascending (D-019). Top-N is a presentation concern.
- Ineligible and `insufficient_data` candidates are not scored. Eligible-unrankable candidates retain available component values, a null rate component, null total, and null rank.
- Deferred components `lane_familiarity` and `reliability` are explicit nulls in storage and API; they are never numeric.

### 23.3 Persistence and lifecycle

- Every evaluated carrier is persisted (D-021), including all ineligible and `insufficient_data` carriers.
- The recommendation status is `ready` when at least one candidate is rankable, `no_eligible_carriers` when no candidate is eligible, and `no_rankable_candidates` when eligible candidates exist but none is rankable (D-033 Option A).
- New terminal recommendations supersede prior terminal recommendations for the same shipment and set `superseded_by_id`; this is the minimal lifecycle needed for repeatable generation.
- The deterministic explanation template states only evaluated counts, eligibility counts, rank, carrier name/MC, computed score, and the recorded flat quote. It does not add performance or reliability claims.

### 23.4 Known limitations

- Non-state service-region rows are retained but do not prove coverage; only active `state` rows match the shipment's origin/destination states.
- Rate provenance/as-of date is not persisted in the current schema (D-022 limitation).
- Deferred components remain unavailable until genuine data sources and a revised configuration exist.
- Top-N filtering and API/UI rendering are implemented in the API milestone; persistence ranks all candidates.

---

*End of decision record. This document records decisions; implementation is authorized separately by the project owner.*

---

## 24. Milestone 5 implementation decisions (project-owner authorized)

Milestone 5 implements the bounded LangGraph orchestration with a real compiled `StateGraph`, one human interrupt, and durable PostgreSQL projections. The project owner's end-to-end authorization covers these implementation choices; they add no fabricated carrier facts.

### 24.1 Graph runtime

- The graph is a `langgraph.graph.StateGraph` whose state schema is `WorkflowState` (Pydantic, `extra="forbid"`). It has exactly the 16 canonical nodes, one `interrupt()` in `request_human_approval`, and an independent terminal failure sink `handle_failure`.
- Every non-terminal edge is conditional: a recorded `state.error` routes to `handle_failure`; otherwise the approved edge is taken. No error path flows through `finalize_execution`.
- Checkpoints use LangGraph's `MemorySaver`. It is process-local and holds only graph resume state. The authoritative operator-visible projection is `workflow_executions.state`, and the authoritative history is the append-only `audit_events` stream, both in PostgreSQL. A process restart cannot resume an interrupted graph from a checkpoint for this MVP; a durable checkpointer (and the additional tables it would require) is deliberately out of scope to preserve the 21-table schema. The approval decision is durably recorded before the resume attempt, so a resume failure is terminal and auditable rather than silently lost.
- `graph.invoke` is called with `thread_id=execution_id` and a recursion limit of 64. Attempt counts, node counts, LLM counts, cumulative compute seconds, and leases are enforced by the node wrapper and persisted on every node.

### 24.2 Execution, lease, and budget semantics

- A queued execution is started exactly once by the workflow service: the service acquires a 60-second lease, increments `attempt_count`, and invokes the graph. A resumption keeps the attempt count and is allowed only from `resumption_pending`.
- Node execution budget: 40 nodes. LLM budget: 6 calls, checked before narrating. Compute budget: 900 cumulative active seconds. The standard attempt cap is 3.
- Budget failures are terminal: `MAX_NODE_EXECUTIONS_EXCEEDED` and `MAX_LLM_CALLS_EXCEEDED` fail the execution; compute, continuous-attempt, and workflow timeout codes map to `timed_out`. The failure payload preserves the originating node.
- `workflow_executions.status` never changes after a terminal transition. Nodes called after termination return without side effects.
- Audit writes use deterministic `idempotency_key` values (`node1:`, `node3:`, `node11:`, `node13:`, `node14:`, `node16:`, `approval-decision:`), so a replayed node cannot duplicate an audit record.

### 24.3 Node responsibility split

- Node 12 (`apply_human_decision`) validates the persisted decision and routes; it does not change the shipment. The approval service's decision transaction is the sole owner of the immediate post-decision shipment status (`approved`, `sourcing`) and sets the execution to `resumption_pending` before the graph resumes.
- Node 11 creates the pending approval and pause audit, sets the shipment to `pending_approval`, releases the lease, and then calls `interrupt()`. On resume it only accepts a terminal persisted decision, and rejects a missing, pending, or mismatched decision.
- Node 13 creates the booking proposal from the approved `selected_candidate_id`, freezes the shipment, and emits the proposal audit. It never selects a different candidate than the approved one.
- Node 14 derives the business outcome and writes the completion metrics; Node 15 finalizes the execution; Node 16 is the only failure terminal.
- Node 2 refuses shipments outside `validated`/`sourcing`. Re-sourcing requires the normal lifecycle transition, not an implicit status reset inside the workflow.

### 24.4 LLM narration in demo mode

- `LLM_DEMO_MODE=true` (the default) performs no external network call. The gateway returns an error result, records an `llm_invocations` row with the reason (`LLM_OFFLINE` for the default offline provider, `LLM_DEMO_MODE` for a configured provider in demo mode), and the stored recommendation uses the deterministic template with provider label `deterministic_template`.
- The LLM never chooses tools, nodes, carriers, or scores. Narration is emitted only from verified facts already computed and persisted.
- `LLM_PROVIDER=offline` is the shipped default, so the product runs deterministically without any paid API key.

### 24.5 Tests and verification

- `backend/tests/test_workflow.py` covers the ready/pause path, approve, reject, changes requested, no eligible carriers, no rankable candidates, validation failure, invalid shipment status, idempotent start, node and compute budget exhaustion, duplicate decisions, deterministic repeatability for identical facts, snapshot retrieval, and strict state-schema rejection.
- Test fixtures clone demo shipments into fresh UUIDs so tests never mutate the fixed demo records or delete data.
- `seed_all_demo_data` resets the fixed synthetic demo shipments (not user-created shipments) to `validated` on each seed, so a repeated demo starts from a runnable state.
- Full suite: 169 passed.

### 24.6 Milestone 5 integrity

| Check | Result |
|---|---|
| Document path | `docs/16-lead-developer-decision-record.md` |
| Source documents modified | `docs/07-agent-workflow.md` Node 6 clarification (pre-existing approved edit, committed with this milestone) and this section |
| Source code added | `backend/app/workflows/{__init__,state,runtime,nodes,graph,service}.py`; `backend/app/services/approvals.py`; LLM narration gateway; workflow tests |
| Database migration | None. The existing 21-table schema supports all workflow, approval, proposal, invocation, and audit records. |
| `docs/14-architecture-review.md` SHA-256 | `9F61632E941B9E06E47EF7F6E2E38C56D97E63E56B7BB76687D605A710182FE4` (verified unchanged) |
| Tests | `169 passed` |
| Known limitation | In-process checkpoint store, so an interrupted execution cannot resume after a process restart. The decision and audit records remain durable. |

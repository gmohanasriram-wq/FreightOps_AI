"""LangGraph node implementations and the node-boundary contract.

Every node is deterministic orchestration. The only optional external call is
LLM narration in ``generate_explanation``; the deterministic template remains
authoritative and the workflow continues when no provider is available.
"""
from __future__ import annotations

import functools
import time
import uuid
from dataclasses import dataclass
from datetime import timezone
from decimal import Decimal
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

from langgraph.errors import GraphInterrupt
from langgraph.types import interrupt
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.domain.eligibility.engine import ELIGIBLE
from backend.app.domain.scoring.engine import (
    DEFAULT_WEIGHTS,
    score_and_rank,
    weights_from_config,
)
from backend.app.domain.validation.engine import RULES_VERSION, ValidationEngine
from backend.app.models.approval import Approval, BookingProposal
from backend.app.models.carrier import Carrier
from backend.app.models.recommendation import Recommendation, RecommendationCandidate
from backend.app.models.scoring import ScoringConfig
from backend.app.models.shipment import Shipment, ShipmentStop, ValidationRun
from backend.app.models.workflow import LLMInvocation, WorkflowExecution
from backend.app.services.candidate_evaluation import evaluate_all_candidates
from backend.app.services.carriers import load_all_carriers
from backend.app.services.llm_gateway import llm_gateway
from backend.app.services.recommendations import (
    NO_ELIGIBLE_CARRIERS,
    NO_RANKABLE_CANDIDATES,
    READY,
    build_explanation_template,
    get_active_scoring_config,
    persist_recommendation,
)
from backend.app.workflows.runtime import (
    emit_idempotent_audit,
    jsonable,
    mark_execution_failed,
    release_execution_lease,
    utcnow,
    verify_execution_lease,
    WorkflowExecutionNotFound,
)
from backend.app.workflows.state import NODE_NAMES, WorkflowState, is_terminal
from backend.app.db.session import SessionLocal


class WorkflowNodeError(RuntimeError):
    """A node-level business or integrity failure."""

    def __init__(self, code: str, message: str, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class NodeContext:
    db: Session
    execution: WorkflowExecution
    lease_token: Optional[str]


def _iso_utc(value) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _api_shipment_dict(shipment: Shipment) -> Dict[str, Any]:
    return {
        "customer_id": shipment.customer_id,
        "origin_facility_id": shipment.origin_facility_id,
        "destination_facility_id": shipment.destination_facility_id,
        "commodity": shipment.commodity,
        "equipment_type": shipment.equipment_type,
        "weight_lbs": shipment.weight_lbs,
        "target_sell_rate": (
            float(shipment.target_sell_rate) if shipment.target_sell_rate is not None else None
        ),
        "max_buy_rate": (
            float(shipment.max_buy_rate) if shipment.max_buy_rate is not None else None
        ),
        "requirements": shipment.requirements or {},
    }


def _api_stops(stops: Sequence[ShipmentStop]) -> List[Dict[str, Any]]:
    return [
        {
            "sequence": stop.sequence,
            "stop_type": stop.stop_type,
            "facility_id": stop.facility_id,
            "name": stop.name,
            "address_line1": stop.address_line1,
            "city": stop.city,
            "state": stop.state,
            "postal_code": stop.postal_code,
            "window_start": stop.window_start,
            "window_end": stop.window_end,
            "appointment_required": stop.appointment_required,
            "contact_phone": stop.contact_phone,
        }
        for stop in sorted(stops, key=lambda row: row.sequence)
    ]


def _load_shipment(
    db: Session,
    shipment_id: str,
) -> tuple[Shipment, List[ShipmentStop]]:
    shipment = db.get(Shipment, uuid.UUID(shipment_id))
    if shipment is None:
        raise WorkflowNodeError("SHIPMENT_NOT_FOUND", f"shipment '{shipment_id}' does not exist")
    stops = list(
        db.scalars(
            select(ShipmentStop)
            .where(ShipmentStop.shipment_id == shipment.id)
            .order_by(ShipmentStop.sequence)
        ).all()
    )
    return shipment, stops


def _number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed == parsed and parsed not in (float("inf"), float("-inf")) else None


def _positive_int(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    return None


def _money(value: Optional[Decimal]) -> Optional[str]:
    return format(value, "f") if value is not None else None


def _score_rows(
    db: Session,
    shipment: Shipment,
    stops: Sequence[ShipmentStop],
) -> Dict[str, Any]:
    """Evaluate, score, and rank every carrier deterministically."""
    evaluation = evaluate_all_candidates(db, shipment, stops)
    config = get_active_scoring_config(db)
    weights = weights_from_config(config.weights or DEFAULT_WEIGHTS)
    scored = score_and_rank(evaluation["candidates"], evaluation["context"], weights)
    eligible_count = sum(
        1 for row in scored if row["evaluation"]["eligibility"].eligibility == ELIGIBLE
    )
    rankable_count = sum(1 for row in scored if row["rank"] is not None)
    if eligible_count == 0:
        status = NO_ELIGIBLE_CARRIERS
    elif rankable_count == 0:
        status = NO_RANKABLE_CANDIDATES
    else:
        status = READY
    return {
        "evaluation": evaluation,
        "config": config,
        "scored": scored,
        "eligible_count": eligible_count,
        "rankable_count": rankable_count,
        "status": status,
    }


def _candidate_summary(scored: Sequence[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in scored:
        evaluation = row["evaluation"]
        outcome = evaluation["eligibility"]
        carrier = evaluation["carrier"]
        components = {
            name: (format(value, "f") if value is not None else None)
            for name, value in (row["components"] or {}).items()
        }
        rows.append(
            {
                "carrier_id": str(carrier["id"]),
                "legal_name": carrier["legal_name"],
                "mc_number": carrier.get("mc_number"),
                "eligibility": outcome.eligibility,
                "ineligibility_codes": list(outcome.ineligibility_codes),
                "rank": row["rank"],
                "total_score": format(row["total"], "f") if row["total"] is not None else None,
                "rate_quote": _money(evaluation.get("rate_quote")),
                "component_scores": components,
            }
        )
    rows.sort(
        key=lambda item: (
            item["rank"] is None,
            item["rank"] if item["rank"] is not None else 0,
            item["carrier_id"],
        )
    )
    return rows


def _error_payload(node: str, exc: BaseException) -> Dict[str, Any]:
    return {
        "code": getattr(exc, "code", "NODE_EXECUTION_FAILED"),
        "message": str(exc)[:2000] or exc.__class__.__name__,
        "node": node,
        "retryable": bool(getattr(exc, "retryable", False)),
    }


def _record_error(
    db: Session,
    execution: WorkflowExecution,
    model: WorkflowState,
    node: str,
    error: Dict[str, Any],
    attempts: Dict[str, int],
) -> Dict[str, Any]:
    projection = model.model_dump()
    projection.update(
        {
            "status": execution.status,
            "current_node": node,
            "error": error,
            "node_execution_count": execution.node_execution_count,
            "node_attempts": attempts,
            "llm_call_count": execution.llm_call_count,
        }
    )
    execution.current_node = node
    execution.state = jsonable(projection)
    db.commit()
    return {
        "status": execution.status,
        "current_node": node,
        "error": error,
        "node_execution_count": execution.node_execution_count,
        "node_attempts": attempts,
        "llm_call_count": execution.llm_call_count,
    }


def workflow_node(name: str) -> Callable:
    """Wrap a node with state validation, budget guards, and error capture."""
    if name not in NODE_NAMES:
        raise ValueError(f"unknown workflow node '{name}'")

    def decorator(fn: Callable[[WorkflowState, NodeContext], Optional[Dict[str, Any]]]):
        @functools.wraps(fn)
        def wrapper(state: WorkflowState, config: Optional[Dict[str, Any]] = None):
            model = WorkflowState.model_validate(state)
            configurable = (config or {}).get("configurable", {}) if isinstance(config, dict) else {}
            lease_token = configurable.get("lease_token")
            started = time.monotonic()

            with SessionLocal() as db:
                execution = db.get(WorkflowExecution, uuid.UUID(model.execution_id))
                if execution is None:
                    raise WorkflowExecutionNotFound(
                        f"workflow execution '{model.execution_id}' does not exist"
                    )
                if is_terminal(execution.status) and name != "handle_failure":
                    return {}

                execution.node_execution_count = (execution.node_execution_count or 0) + 1
                execution.current_node = name
                if execution.status == "queued":
                    execution.status = "running"
                attempts = dict(model.node_attempts or {})
                attempts[name] = attempts.get(name, 0) + 1
                model = model.model_copy(
                    update={
                        "node_execution_count": execution.node_execution_count,
                        "current_node": name,
                        "node_attempts": attempts,
                        "status": execution.status,
                        "llm_call_count": execution.llm_call_count,
                    }
                )

                if name != "handle_failure":
                    budget_error: Optional[Dict[str, Any]] = None
                    if execution.node_execution_count > settings.WORKFLOW_MAX_NODE_EXECUTIONS:
                        budget_error = {
                            "code": "MAX_NODE_EXECUTIONS_EXCEEDED",
                            "message": (
                                "Execution aborted: maximum node executions "
                                f"({settings.WORKFLOW_MAX_NODE_EXECUTIONS}) exceeded"
                            ),
                            "node": name,
                            "retryable": False,
                        }
                    elif (
                        execution.cumulative_compute_seconds
                        >= settings.WORKFLOW_MAX_COMPUTE_SECONDS
                    ):
                        budget_error = {
                            "code": "MAX_COMPUTE_BUDGET_EXCEEDED",
                            "message": "Execution aborted: cumulative active compute budget exceeded",
                            "node": name,
                            "retryable": False,
                        }
                    else:
                        try:
                            verify_execution_lease(execution, lease_token)
                        except Exception as exc:  # noqa: BLE001
                            budget_error = _error_payload(name, exc)
                    if budget_error is not None:
                        return _record_error(db, execution, model, name, budget_error, attempts)

                ctx = NodeContext(db=db, execution=execution, lease_token=lease_token)
                try:
                    update = fn(model, ctx) or {}
                except GraphInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    error = _error_payload(name, exc)
                    db.rollback()
                    execution = db.get(WorkflowExecution, uuid.UUID(model.execution_id))
                    if execution is None:
                        raise WorkflowExecutionNotFound(
                            f"workflow execution '{model.execution_id}' does not exist"
                        ) from exc
                    db.refresh(execution)
                    # The rollback discarded the increment and attempt count that
                    # produced this failure, so restore them from the model.
                    execution.node_execution_count = model.node_execution_count
                    execution.status = model.status
                    current_attempts = dict(model.node_attempts or {})
                    return _record_error(db, execution, model, name, error, current_attempts)

                elapsed = int(time.monotonic() - started)
                execution.cumulative_compute_seconds = min(
                    settings.WORKFLOW_MAX_COMPUTE_SECONDS,
                    (execution.cumulative_compute_seconds or 0) + max(0, elapsed),
                )
                merged = model.model_dump()
                merged.update(jsonable(update))
                merged["node_execution_count"] = execution.node_execution_count
                merged["current_node"] = name
                merged["node_attempts"] = attempts
                merged["llm_call_count"] = update.get(
                    "llm_call_count", execution.llm_call_count
                )
                if "status" not in update:
                    merged["status"] = execution.status
                validated = WorkflowState.model_validate(merged)
                execution.state = validated.model_dump()
                db.commit()
                return {
                    **jsonable(update),
                    "node_execution_count": execution.node_execution_count,
                    "current_node": name,
                    "node_attempts": attempts,
                    "status": validated.status,
                    "llm_call_count": validated.llm_call_count,
                }

        return wrapper

    return decorator


# ---------------------------------------------------------------------------
# Node 1
# ---------------------------------------------------------------------------
@workflow_node("start_execution")
def start_execution(state: WorkflowState, ctx: NodeContext) -> Dict[str, Any]:
    shipment = ctx.db.get(Shipment, uuid.UUID(state.shipment_id))
    if shipment is None:
        raise WorkflowNodeError(
            "SHIPMENT_NOT_FOUND", f"shipment '{state.shipment_id}' does not exist"
        )
    if shipment.status == "validated":
        shipment.status = "sourcing"
        shipment.updated_at = utcnow()

    emit_idempotent_audit(
        ctx.db,
        idempotency_key=f"node1:{state.execution_id}:workflow.started",
        event_type="workflow.started",
        actor_type="system",
        actor_id=shipment.created_by,
        shipment_id=shipment.id,
        workflow_execution_id=ctx.execution.id,
        trace_id=state.trace_id,
        payload={
            "graph_version": state.graph_version,
            "attempt_count": ctx.execution.attempt_count,
        },
    )
    idempotency = dict(state.idempotency or {})
    idempotency["workflow_started"] = f"node1:{state.execution_id}:workflow.started"
    return {
        "status": "running",
        "started_at": _iso_utc(ctx.execution.started_at),
        "attempt_started_at": _iso_utc(ctx.execution.attempt_started_at),
        "idempotency": idempotency,
    }


# ---------------------------------------------------------------------------
# Node 2
# ---------------------------------------------------------------------------
@workflow_node("load_shipment")
def load_shipment(state: WorkflowState, ctx: NodeContext) -> Dict[str, Any]:
    shipment, stops = _load_shipment(ctx.db, state.shipment_id)
    if shipment.status not in ("validated", "sourcing"):
        raise WorkflowNodeError(
            "INVALID_SHIPMENT_STATUS",
            (
                f"shipment '{shipment.id}' must be validated or sourcing before a "
                f"recommendation workflow can run (status '{shipment.status}')"
            ),
        )
    if not stops:
        # Validation will persist the authoritative failure in Node 3.
        return {"status": "running"}
    return {"status": "running"}


# ---------------------------------------------------------------------------
# Node 3
# ---------------------------------------------------------------------------
@workflow_node("validate_shipment")
def validate_shipment(state: WorkflowState, ctx: NodeContext) -> Dict[str, Any]:
    shipment, stops = _load_shipment(ctx.db, state.shipment_id)

    existing = ctx.db.scalars(
        select(ValidationRun).where(ValidationRun.workflow_execution_id == ctx.execution.id)
    ).first()
    if existing is not None:
        return {
            "validation_result": {
                "status": existing.result,
                "run_id": str(existing.id),
                "rules_version": existing.rules_version,
                "issues": list(existing.issues or []),
                "checked_at": existing.checked_at.isoformat(),
            }
        }

    result_status, issues = ValidationEngine.validate(
        _api_shipment_dict(shipment), _api_stops(stops)
    )
    issues_dicts = [issue.model_dump() for issue in issues]
    checked_at = utcnow()
    run = ValidationRun(
        shipment_id=shipment.id,
        result=result_status,
        issues=issues_dicts,
        rules_version=RULES_VERSION,
        triggered_by_user_id=shipment.created_by,
        workflow_execution_id=ctx.execution.id,
        checked_at=checked_at,
    )
    ctx.db.add(run)
    ctx.db.flush()

    if result_status == "failed":
        shipment.status = "validation_failed"
    elif shipment.status in ("draft", "intake_received", "validation_failed", "validated"):
        shipment.status = "validated"
    shipment.updated_at = checked_at

    emit_idempotent_audit(
        ctx.db,
        idempotency_key=f"node3:{state.execution_id}:validation",
        event_type="validation.failed" if result_status == "failed" else "validation.completed",
        actor_type="system",
        actor_id=shipment.created_by,
        shipment_id=shipment.id,
        workflow_execution_id=ctx.execution.id,
        trace_id=state.trace_id,
        payload={
            "validation_run_id": str(run.id),
            "result": result_status,
            "issue_count": len(issues_dicts),
            "rules_version": RULES_VERSION,
        },
    )

    return {
        "validation_result": {
            "status": result_status,
            "run_id": str(run.id),
            "rules_version": RULES_VERSION,
            "issues": issues_dicts,
            "checked_at": checked_at.isoformat(),
        }
    }


# ---------------------------------------------------------------------------
# Node 4
# ---------------------------------------------------------------------------
@workflow_node("decide_validation_outcome")
def decide_validation_outcome(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    result = (state.validation_result or {}).get("status")
    if result == "failed":
        shipment = ctx.db.get(Shipment, uuid.UUID(state.shipment_id))
        if shipment is not None:
            shipment.status = "validation_failed"
            shipment.updated_at = utcnow()
        return {
            "error": {
                "code": "VALIDATION_FAILED",
                "message": "Deterministic shipment validation failed; workflow cannot continue",
                "node": "decide_validation_outcome",
                "retryable": False,
            },
            "outcome": "failed",
        }
    if result not in ("passed", "passed_with_warnings"):
        raise WorkflowNodeError(
            "VALIDATION_RESULT_MISSING",
            "validation result is missing or not recognised",
        )
    return {"status": "running"}


# ---------------------------------------------------------------------------
# Node 5
# ---------------------------------------------------------------------------
@workflow_node("normalize_requirements")
def normalize_requirements(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    shipment, stops = _load_shipment(ctx.db, state.shipment_id)
    raw = shipment.requirements if isinstance(shipment.requirements, Mapping) else {}

    temperature_range: Optional[Dict[str, Optional[float]]] = None
    candidate_range = raw.get("temperature_range")
    if isinstance(candidate_range, Mapping):
        minimum = _number(candidate_range.get("min_f"))
        maximum = _number(candidate_range.get("max_f"))
        if minimum is not None or maximum is not None:
            temperature_range = {"min_f": minimum, "max_f": maximum}

    gaps: List[str] = []
    if not shipment.equipment_type:
        gaps.append("equipment_type")
    if not shipment.lane_origin and not any(stop.stop_type == "pickup" for stop in stops):
        gaps.append("lane_origin")
    if not shipment.lane_destination and not any(stop.stop_type == "delivery" for stop in stops):
        gaps.append("lane_destination")
    pickups = [stop for stop in stops if stop.stop_type == "pickup"]
    if not pickups or pickups[0].window_start is None or pickups[0].window_end is None:
        gaps.append("pickup_window")

    snapshot = {
        "equipment_type": shipment.equipment_type,
        "hazmat_required": raw.get("hazmat") is True,
        "temperature_required": temperature_range is not None,
        "temperature_range": temperature_range,
        "trailer_length_ft": _positive_int(raw.get("trailer_length_ft")),
        "appointment_required": bool(raw.get("appointment", False)),
        "lane_origin": shipment.lane_origin,
        "lane_destination": shipment.lane_destination,
        "currency": shipment.currency,
        "max_buy_rate": _money(shipment.max_buy_rate),
        "target_sell_rate": _money(shipment.target_sell_rate),
        "gaps": gaps,
    }
    return {"requirements_snapshot": snapshot}


# ---------------------------------------------------------------------------
# Node 6
# ---------------------------------------------------------------------------
@workflow_node("resolve_carrier_candidates")
def resolve_carrier_candidates(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    """Load the broad carrier universe (D-027). Never pre-filter here."""
    carriers = load_all_carriers(ctx.db)
    return {"candidate_carrier_ids": [str(carrier.id) for carrier in carriers]}


# ---------------------------------------------------------------------------
# Node 7
# ---------------------------------------------------------------------------
@workflow_node("filter_eligible_carriers")
def filter_eligible_carriers(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    shipment, stops = _load_shipment(ctx.db, state.shipment_id)
    evaluation = evaluate_all_candidates(ctx.db, shipment, stops)
    results: Dict[str, Dict[str, Any]] = {}
    for row in evaluation["candidates"]:
        outcome = row["eligibility"]
        results[str(row["carrier"]["id"])] = {
            "status": outcome.eligibility,
            "codes": list(outcome.ineligibility_codes),
            "failure_codes": list(outcome.failure_codes),
            "missing_data": outcome.missing_data,
            "filters": dict(outcome.filter_results),
            "rate_quote": _money(row.get("rate_quote")),
            "unrankable_reason": row.get("unrankable_reason"),
        }
    return {
        "candidate_carrier_ids": list(results.keys()),
        "eligibility_results": results,
    }


# ---------------------------------------------------------------------------
# Node 8
# ---------------------------------------------------------------------------
@workflow_node("score_candidates")
def score_candidates(state: WorkflowState, ctx: NodeContext) -> Dict[str, Any]:
    shipment, stops = _load_shipment(ctx.db, state.shipment_id)
    outcome = _score_rows(ctx.db, shipment, stops)
    return {
        "ranked_candidates": _candidate_summary(outcome["scored"]),
        "scoring_config_id": str(outcome["config"].id),
        "scoring_config_version": outcome["config"].version,
    }


# ---------------------------------------------------------------------------
# Node 9
# ---------------------------------------------------------------------------
@workflow_node("generate_explanation")
def generate_explanation(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    shipment, stops = _load_shipment(ctx.db, state.shipment_id)
    outcome = _score_rows(ctx.db, shipment, stops)
    scored = outcome["scored"]

    template = build_explanation_template(
        scored,
        outcome["evaluation"]["context"],
        outcome["status"],
        top_n=settings.TOP_N_RECOMMENDATIONS,
    )
    facts: List[str] = [
        f"Evaluated candidates: {len(scored)}.",
        f"Eligible candidates: {outcome['eligible_count']}.",
        f"Rankable candidates: {outcome['rankable_count']}.",
        (
            "Lane: "
            f"{outcome['evaluation']['context'].get('lane_origin') or 'not recorded'} -> "
            f"{outcome['evaluation']['context'].get('lane_destination') or 'not recorded'}."
        ),
        f"Scoring configuration version: {outcome['config'].version}.",
    ]
    ranked = sorted(
        (row for row in scored if row["rank"] is not None),
        key=lambda row: row["rank"],
    )[: settings.TOP_N_RECOMMENDATIONS]
    for row in ranked:
        evaluation = row["evaluation"]
        carrier = evaluation["carrier"]
        quote = evaluation.get("rate_quote")
        facts.append(
            f"Rank {row['rank']}: {carrier['legal_name']} ({carrier.get('mc_number') or 'MC not recorded'}), "
            f"total score {format(row['total'], 'f')}, recorded flat rate "
            f"{_money(quote) if quote is not None else 'unavailable'} "
            f"{outcome['evaluation']['context'].get('currency') or 'USD'}."
        )

    if (ctx.execution.llm_call_count or 0) >= settings.WORKFLOW_LLM_BUDGET:
        raise WorkflowNodeError(
            "MAX_LLM_CALLS_EXCEEDED",
            f"Execution aborted: maximum LLM calls ({settings.WORKFLOW_LLM_BUDGET}) exceeded",
        )
    ctx.execution.llm_call_count = (ctx.execution.llm_call_count or 0) + 1
    narration = llm_gateway.narrate_explanation("\n".join(facts))
    ctx.db.add(
        LLMInvocation(
            workflow_execution_id=ctx.execution.id,
            operation="narrate_explanation",
            provider=narration.provider,
            model_identifier=narration.model_identifier,
            latency_ms=narration.latency_ms,
            status=narration.status,
            error_code=narration.error_code,
        )
    )
    ctx.db.flush()

    provider = narration.provider if narration.succeeded else "deterministic_template"
    explanation = {
        "template": template,
        "narration": narration.narration,
        "provider": provider,
        "facts": facts,
    }
    return {
        "explanation": explanation,
        "llm_call_count": ctx.execution.llm_call_count,
    }


# ---------------------------------------------------------------------------
# Node 10
# ---------------------------------------------------------------------------
@workflow_node("persist_recommendation")
def persist_recommendation_node(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    existing = ctx.db.scalars(
        select(Recommendation).where(
            Recommendation.workflow_execution_id == ctx.execution.id
        )
    ).first()
    if existing is not None:
        return {
            "recommendation_id": str(existing.id),
            "recommendation_status": existing.status,
            "explanation": state.explanation
            or {
                "template": existing.explanation_template,
                "narration": existing.explanation_narration,
                "provider": existing.explanation_provider,
                "facts": [],
            },
        }

    shipment, stops = _load_shipment(ctx.db, state.shipment_id)
    config: Optional[ScoringConfig] = None
    if state.scoring_config_id:
        config = ctx.db.get(ScoringConfig, uuid.UUID(state.scoring_config_id))
    if config is None:
        config = get_active_scoring_config(ctx.db)

    explanation = state.explanation or {}
    recommendation = persist_recommendation(
        ctx.db,
        shipment,
        stops,
        scoring_config=config,
        workflow_execution_id=ctx.execution.id,
        created_by=shipment.created_by,
        explanation_template=explanation.get("template"),
        explanation_narration=explanation.get("narration"),
        explanation_provider=explanation.get("provider"),
        top_n=settings.TOP_N_RECOMMENDATIONS,
    )

    if recommendation.status == READY:
        shipment.status = "recommendation_ready"
    elif shipment.status == "recommendation_ready":
        shipment.status = "sourcing"
    shipment.updated_at = utcnow()

    return {
        "recommendation_id": str(recommendation.id),
        "recommendation_status": recommendation.status,
        "explanation": {
            "template": recommendation.explanation_template,
            "narration": recommendation.explanation_narration,
            "provider": recommendation.explanation_provider,
            "facts": explanation.get("facts", []),
        },
    }


# ---------------------------------------------------------------------------
# Node 11
# ---------------------------------------------------------------------------
@workflow_node("request_human_approval")
def request_human_approval(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    if not state.recommendation_id:
        raise WorkflowNodeError(
            "RECOMMENDATION_MISSING", "a ready recommendation is required before approval"
        )
    recommendation = ctx.db.get(
        Recommendation, uuid.UUID(state.recommendation_id)
    )
    if recommendation is None or recommendation.status != READY:
        raise WorkflowNodeError(
            "RECOMMENDATION_NOT_READY",
            "only a ready recommendation can be sent for human approval",
        )

    approval = ctx.db.scalars(
        select(Approval).where(Approval.workflow_execution_id == ctx.execution.id)
    ).first()

    if approval is None:
        approval = Approval(
            recommendation_id=recommendation.id,
            shipment_id=recommendation.shipment_id,
            workflow_execution_id=ctx.execution.id,
            status="pending",
            requested_by=recommendation.created_by,
        )
        ctx.db.add(approval)
        ctx.db.flush()

        shipment = ctx.db.get(Shipment, recommendation.shipment_id)
        if shipment is not None:
            shipment.status = "pending_approval"
            shipment.updated_at = utcnow()

        ctx.execution.status = "waiting_for_human"
        ctx.execution.current_node = "request_human_approval"
        release_execution_lease(ctx.execution)
        emit_idempotent_audit(
            ctx.db,
            idempotency_key=f"node11:{state.execution_id}:workflow.paused_for_human",
            event_type="workflow.paused_for_human",
            actor_type="system",
            actor_id=recommendation.created_by,
            shipment_id=recommendation.shipment_id,
            workflow_execution_id=ctx.execution.id,
            approval_id=approval.id,
            trace_id=state.trace_id,
            payload={
                "approval_id": str(approval.id),
                "recommendation_id": str(recommendation.id),
            },
        )
        projection = state.model_dump()
        projection.update(
            {
                "status": "waiting_for_human",
                "current_node": "request_human_approval",
                "approval_id": str(approval.id),
                "approval_status": approval.status,
                "recommendation_id": str(recommendation.id),
                "recommendation_status": recommendation.status,
                "node_execution_count": ctx.execution.node_execution_count,
            }
        )
        ctx.execution.state = jsonable(projection)
        ctx.db.commit()

    else:
        if state.approval_id and str(approval.id) != state.approval_id:
            raise WorkflowNodeError(
                "APPROVAL_ID_MISMATCH",
                "durable approval does not match the approval recorded in workflow state",
            )
        if approval.resumed_at is not None:
            raise WorkflowNodeError(
                "APPROVAL_ALREADY_RESUMED",
                "this approval has already been resumed",
            )

    decision_payload = interrupt(
        {
            "approval_id": str(approval.id),
            "recommendation_id": str(approval.recommendation_id),
            "execution_id": str(ctx.execution.id),
        }
    )

    approval = ctx.db.get(Approval, approval.id, populate_existing=True)
    if approval is None:
        raise WorkflowNodeError("APPROVAL_NOT_FOUND", "approval disappeared during resume")
    if approval.resumed_at is not None:
        raise WorkflowNodeError(
            "APPROVAL_ALREADY_RESUMED", "approval has already been resumed"
        )
    if approval.status not in ("approved", "rejected", "changes_requested"):
        raise WorkflowNodeError(
            "APPROVAL_DECISION_MISSING",
            "no persisted human decision exists for this resumption",
        )

    action = (decision_payload or {}).get("action")
    expected_status = {
        "approve": "approved",
        "reject": "rejected",
        "request_changes": "changes_requested",
    }.get(action)
    if expected_status != approval.status:
        raise WorkflowNodeError(
            "APPROVAL_ACTION_MISMATCH",
            f"resume action '{action}' does not match persisted approval status '{approval.status}'",
        )

    human_decision = {
        "decision": approval.status,
        "action": action,
        "comment": approval.decision_comment,
        "actor_id": str(approval.decided_by) if approval.decided_by else None,
        "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
        "selected_candidate_id": (
            str(approval.selected_candidate_id)
            if approval.selected_candidate_id
            else None
        ),
    }
    return {
        "status": "running",
        "approval_id": str(approval.id),
        "approval_status": approval.status,
        "selected_candidate_id": human_decision["selected_candidate_id"],
        "human_decision": human_decision,
    }


# ---------------------------------------------------------------------------
# Node 12
# ---------------------------------------------------------------------------
@workflow_node("apply_human_decision")
def apply_human_decision(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    if not state.approval_id:
        raise WorkflowNodeError("APPROVAL_MISSING", "approval id is required")
    approval = ctx.db.get(Approval, uuid.UUID(state.approval_id))
    if approval is None:
        raise WorkflowNodeError("APPROVAL_NOT_FOUND", "approval does not exist")
    if approval.status not in ("approved", "rejected", "changes_requested"):
        raise WorkflowNodeError(
            "APPROVAL_DECISION_MISSING",
            f"approval status '{approval.status}' is not a terminal human decision",
        )
    # The Approval Service transaction is the sole owner of shipment status
    # changes for decisions; this node only validates and routes.
    human_decision = dict(state.human_decision or {})
    human_decision.update(
        {
            "decision": approval.status,
            "comment": approval.decision_comment,
            "actor_id": str(approval.decided_by) if approval.decided_by else None,
            "decided_at": approval.decided_at.isoformat() if approval.decided_at else None,
            "selected_candidate_id": (
                str(approval.selected_candidate_id)
                if approval.selected_candidate_id
                else None
            ),
        }
    )
    return {
        "approval_status": approval.status,
        "selected_candidate_id": human_decision["selected_candidate_id"],
        "human_decision": human_decision,
        "status": "running",
    }


# ---------------------------------------------------------------------------
# Node 13
# ---------------------------------------------------------------------------
@workflow_node("create_booking_proposal")
def create_booking_proposal(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    if not state.approval_id:
        raise WorkflowNodeError("APPROVAL_MISSING", "approval id is required")
    approval = ctx.db.get(
        Approval, uuid.UUID(state.approval_id), with_for_update=True
    )
    if approval is None:
        raise WorkflowNodeError("APPROVAL_NOT_FOUND", "approval does not exist")
    if approval.status != "approved":
        raise WorkflowNodeError(
            "APPROVAL_NOT_APPROVED",
            "a booking proposal can only be created from an approved approval",
        )

    existing = ctx.db.scalars(
        select(BookingProposal).where(BookingProposal.approval_id == approval.id)
    ).first()
    if existing is not None:
        return {"booking_proposal_id": str(existing.id), "status": "running"}

    if approval.selected_candidate_id is None:
        raise WorkflowNodeError(
            "CANDIDATE_NOT_SELECTED", "the approved decision has no selected candidate"
        )
    candidate = ctx.db.get(
        RecommendationCandidate, approval.selected_candidate_id
    )
    if (
        candidate is None
        or candidate.recommendation_id != approval.recommendation_id
        or candidate.rank is None
        or candidate.eligibility != ELIGIBLE
    ):
        raise WorkflowNodeError(
            "CANDIDATE_NOT_RANKABLE",
            "the selected candidate is not a rankable candidate of this recommendation",
        )
    carrier = ctx.db.get(Carrier, candidate.carrier_id)
    shipment = ctx.db.get(
        Shipment, approval.shipment_id, with_for_update=True
    )
    if shipment is None:
        raise WorkflowNodeError("SHIPMENT_NOT_FOUND", "shipment does not exist")
    if shipment.status not in ("approved", "booking_proposed"):
        raise WorkflowNodeError(
            "INVALID_SHIPMENT_TRANSITION",
            f"shipment status '{shipment.status}' cannot transition to booking_proposed",
        )

    stops = list(
        ctx.db.scalars(
            select(ShipmentStop)
            .where(ShipmentStop.shipment_id == shipment.id)
            .order_by(ShipmentStop.sequence)
        ).all()
    )
    snapshot = {
        "shipment_id": str(shipment.id),
        "reference_number": shipment.reference_number,
        "recommendation_id": str(approval.recommendation_id),
        "approval_id": str(approval.id),
        "carrier": {
            "carrier_id": str(candidate.carrier_id),
            "legal_name": carrier.legal_name if carrier is not None else None,
            "mc_number": carrier.mc_number if carrier is not None else None,
        },
        "rank": candidate.rank,
        "total_score": _money(candidate.total_score),
        "rate_quote": _money(candidate.rate_quote),
        "currency": shipment.currency,
        "equipment_type": shipment.equipment_type,
        "lane_origin": shipment.lane_origin,
        "lane_destination": shipment.lane_destination,
        "stops": [
            {
                "sequence": stop.sequence,
                "stop_type": stop.stop_type,
                "city": stop.city,
                "state": stop.state,
                "window_start": stop.window_start.isoformat() if stop.window_start else None,
                "window_end": stop.window_end.isoformat() if stop.window_end else None,
            }
            for stop in stops
        ],
    }

    proposal = BookingProposal(
        shipment_id=shipment.id,
        approval_id=approval.id,
        carrier_id=candidate.carrier_id,
        proposal_number=(
            f"BP-{shipment.id.hex[:8].upper()}-{approval.id.hex[:8].upper()}"
        ),
        status="proposed",
        snapshot=jsonable(snapshot),
        idempotency_key=f"proposal:{approval.id}",
        created_by=approval.decided_by,
    )
    ctx.db.add(proposal)
    ctx.db.flush()

    shipment.status = "booking_proposed"
    shipment.frozen_at = shipment.frozen_at or utcnow()
    shipment.updated_at = utcnow()

    emit_idempotent_audit(
        ctx.db,
        idempotency_key=f"node13:{approval.id}:booking_proposal.created",
        event_type="booking_proposal.created",
        actor_type="system",
        actor_id=approval.decided_by,
        shipment_id=shipment.id,
        workflow_execution_id=ctx.execution.id,
        approval_id=approval.id,
        booking_proposal_id=proposal.id,
        trace_id=state.trace_id,
        payload={
            "booking_proposal_id": str(proposal.id),
            "proposal_number": proposal.proposal_number,
            "carrier_id": str(candidate.carrier_id),
            "rate_quote": _money(candidate.rate_quote),
        },
    )
    return {"booking_proposal_id": str(proposal.id), "status": "running"}


# ---------------------------------------------------------------------------
# Node 14
# ---------------------------------------------------------------------------
@workflow_node("record_audit_event")
def record_audit_event(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    approval_status = state.approval_status
    recommendation_status = state.recommendation_status
    if state.booking_proposal_id or approval_status == "approved":
        outcome = "approved"
    elif approval_status in ("rejected", "changes_requested"):
        outcome = approval_status
    elif recommendation_status in (NO_ELIGIBLE_CARRIERS, NO_RANKABLE_CANDIDATES):
        outcome = recommendation_status
    else:
        raise WorkflowNodeError(
            "OUTCOME_UNDETERMINED",
            "workflow reached the completion audit without a determinable business outcome",
        )

    shipment = ctx.db.get(Shipment, uuid.UUID(state.shipment_id))
    metrics = {
        "outcome": outcome,
        "final_shipment_status": shipment.status if shipment is not None else None,
        "node_execution_count": ctx.execution.node_execution_count,
        "llm_call_count": ctx.execution.llm_call_count,
        "attempt_count": ctx.execution.attempt_count,
        "cumulative_compute_seconds": ctx.execution.cumulative_compute_seconds,
        "recommendation_id": state.recommendation_id,
        "error_code": None,
    }
    emit_idempotent_audit(
        ctx.db,
        idempotency_key=f"node14:{state.execution_id}:workflow.completed",
        event_type="workflow.completed",
        actor_type="system",
        actor_id=None,
        shipment_id=uuid.UUID(state.shipment_id),
        workflow_execution_id=ctx.execution.id,
        approval_id=(
            uuid.UUID(state.approval_id) if state.approval_id else None
        ),
        booking_proposal_id=(
            uuid.UUID(state.booking_proposal_id)
            if state.booking_proposal_id
            else None
        ),
        trace_id=state.trace_id,
        payload=metrics,
    )
    return {"outcome": outcome, "status": "running"}


# ---------------------------------------------------------------------------
# Node 15
# ---------------------------------------------------------------------------
@workflow_node("finalize_execution")
def finalize_execution(
    state: WorkflowState, ctx: NodeContext
) -> Dict[str, Any]:
    if state.outcome is None:
        raise WorkflowNodeError(
            "OUTCOME_MISSING", "execution cannot finalize without a business outcome"
        )
    now = utcnow()
    ctx.execution.status = "completed"
    ctx.execution.current_node = "finalize_execution"
    ctx.execution.completed_at = now
    release_execution_lease(ctx.execution)

    if state.approval_id:
        approval = ctx.db.get(Approval, uuid.UUID(state.approval_id))
        if approval is not None and approval.resumed_at is None:
            approval.resumed_at = now

    return {
        "status": "completed",
        "outcome": state.outcome,
        "current_node": "finalize_execution",
    }


# ---------------------------------------------------------------------------
# Node 16
# ---------------------------------------------------------------------------
@workflow_node("handle_failure")
def handle_failure(state: WorkflowState, ctx: NodeContext) -> Dict[str, Any]:
    error = state.error or {
        "code": "WORKFLOW_FAILED",
        "message": "workflow terminated without a recorded error",
        "node": "handle_failure",
        "retryable": False,
    }
    projection = state.model_dump()
    return mark_execution_failed(
        ctx.db,
        ctx.execution,
        code=error.get("code", "WORKFLOW_FAILED"),
        message=error.get("message", "workflow failed"),
        state_projection=projection,
    )


# Public node table used by graph construction and tests.
NODE_FUNCTIONS: Dict[str, Callable] = {
    "start_execution": start_execution,
    "load_shipment": load_shipment,
    "validate_shipment": validate_shipment,
    "decide_validation_outcome": decide_validation_outcome,
    "normalize_requirements": normalize_requirements,
    "resolve_carrier_candidates": resolve_carrier_candidates,
    "filter_eligible_carriers": filter_eligible_carriers,
    "score_candidates": score_candidates,
    "generate_explanation": generate_explanation,
    "persist_recommendation": persist_recommendation_node,
    "request_human_approval": request_human_approval,
    "apply_human_decision": apply_human_decision,
    "create_booking_proposal": create_booking_proposal,
    "record_audit_event": record_audit_event,
    "finalize_execution": finalize_execution,
    "handle_failure": handle_failure,
}

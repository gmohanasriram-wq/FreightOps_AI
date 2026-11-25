"""Bounded LangGraph state machine (docs/07 §7).

Exactly one interrupt exists (``request_human_approval``). All error paths route
to the independent terminal ``handle_failure`` sink. Checkpoints are held in a
process-local ``MemorySaver``; the authoritative, durable operator projection is
``workflow_executions.state`` and the audit stream in PostgreSQL.
"""
from __future__ import annotations

from typing import Dict

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from backend.app.domain.eligibility.engine import ELIGIBLE
from backend.app.services.recommendations import NO_ELIGIBLE_CARRIERS, NO_RANKABLE_CANDIDATES, READY
from backend.app.workflows.nodes import NODE_FUNCTIONS
from backend.app.workflows.state import WorkflowState

_FAILURE = "handle_failure"


def _after(next_node: str):
    def route(state: WorkflowState) -> str:
        return _FAILURE if state.error else next_node

    return route


def _after_validation(state: WorkflowState) -> str:
    if state.error:
        return _FAILURE
    status = (state.validation_result or {}).get("status")
    if status in ("passed", "passed_with_warnings"):
        return "normalize_requirements"
    return _FAILURE


def _after_filter(state: WorkflowState) -> str:
    if state.error:
        return _FAILURE
    eligible = any(
        result.get("status") == ELIGIBLE
        for result in (state.eligibility_results or {}).values()
    )
    return "score_candidates" if eligible else "persist_recommendation"


def _after_score(state: WorkflowState) -> str:
    if state.error:
        return _FAILURE
    rankable = any(row.get("rank") is not None for row in state.ranked_candidates or [])
    return "generate_explanation" if rankable else "persist_recommendation"


def _after_persist(state: WorkflowState) -> str:
    if state.error:
        return _FAILURE
    if state.recommendation_status == READY:
        return "request_human_approval"
    if state.recommendation_status in (NO_ELIGIBLE_CARRIERS, NO_RANKABLE_CANDIDATES):
        return "record_audit_event"
    return _FAILURE


def _after_decision(state: WorkflowState) -> str:
    if state.error:
        return _FAILURE
    return (
        "create_booking_proposal"
        if state.approval_status == "approved"
        else "record_audit_event"
    )


def build_workflow_graph(checkpointer: MemorySaver | None = None):
    """Construct the canonical 16-node graph."""
    graph = StateGraph(WorkflowState)
    for name, fn in NODE_FUNCTIONS.items():
        graph.add_node(name, fn)

    graph.add_edge(START, "start_execution")
    graph.add_conditional_edges(
        "start_execution",
        _after("load_shipment"),
        {"load_shipment": "load_shipment", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "load_shipment",
        _after("validate_shipment"),
        {"validate_shipment": "validate_shipment", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "validate_shipment",
        _after("decide_validation_outcome"),
        {"decide_validation_outcome": "decide_validation_outcome", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "decide_validation_outcome",
        _after_validation,
        {
            "normalize_requirements": "normalize_requirements",
            _FAILURE: _FAILURE,
        },
    )
    graph.add_conditional_edges(
        "normalize_requirements",
        _after("resolve_carrier_candidates"),
        {"resolve_carrier_candidates": "resolve_carrier_candidates", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "resolve_carrier_candidates",
        _after("filter_eligible_carriers"),
        {"filter_eligible_carriers": "filter_eligible_carriers", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "filter_eligible_carriers",
        _after_filter,
        {
            "score_candidates": "score_candidates",
            "persist_recommendation": "persist_recommendation",
            _FAILURE: _FAILURE,
        },
    )
    graph.add_conditional_edges(
        "score_candidates",
        _after_score,
        {
            "generate_explanation": "generate_explanation",
            "persist_recommendation": "persist_recommendation",
            _FAILURE: _FAILURE,
        },
    )
    graph.add_conditional_edges(
        "generate_explanation",
        _after("persist_recommendation"),
        {"persist_recommendation": "persist_recommendation", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "persist_recommendation",
        _after_persist,
        {
            "request_human_approval": "request_human_approval",
            "record_audit_event": "record_audit_event",
            _FAILURE: _FAILURE,
        },
    )
    graph.add_conditional_edges(
        "request_human_approval",
        _after("apply_human_decision"),
        {"apply_human_decision": "apply_human_decision", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "apply_human_decision",
        _after_decision,
        {
            "create_booking_proposal": "create_booking_proposal",
            "record_audit_event": "record_audit_event",
            _FAILURE: _FAILURE,
        },
    )
    graph.add_conditional_edges(
        "create_booking_proposal",
        _after("record_audit_event"),
        {"record_audit_event": "record_audit_event", _FAILURE: _FAILURE},
    )
    graph.add_conditional_edges(
        "record_audit_event",
        _after("finalize_execution"),
        {"finalize_execution": "finalize_execution", _FAILURE: _FAILURE},
    )
    graph.add_edge("finalize_execution", END)
    graph.add_edge(_FAILURE, END)
    return graph.compile(checkpointer=checkpointer or MemorySaver())


_GRAPH = None


def get_workflow_graph():
    """Return the process-wide compiled graph (stable checkpoint store)."""
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_workflow_graph()
    return _GRAPH


def reset_workflow_graph() -> None:
    """Rebuild the compiled graph and its in-memory checkpoints (tests only)."""
    global _GRAPH
    _GRAPH = None


def graph_topology() -> Dict[str, str]:
    """Small introspection helper for diagnostics and tests."""
    return {name: "node" for name in NODE_FUNCTIONS}

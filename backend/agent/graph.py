"""
LangGraph Definition — The complete agent graph with all nodes and edges.
This is the core orchestration engine for the Course RAG pipeline.
"""

import logging
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

from backend.agent.state import AgentState
from backend.agent.nodes.input_handler import input_handler
from backend.agent.nodes.router import router
from backend.agent.nodes.retriever import retriever
from backend.agent.nodes.deadline_extractor import deadline_extractor
from backend.agent.nodes.deadline_verifier import deadline_verifier
from backend.agent.nodes.summary_redirector import summary_redirector
from backend.agent.nodes.general_responder import general_responder
from backend.agent.nodes.upload_handler import upload_handler
from backend.agent.nodes.location_classifier import location_classifier
from backend.agent.nodes.upload_executor import upload_executor
from backend.agent.nodes.response_output import response_output
from backend.agent.nodes.source_explainer import source_explainer

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────
# Conditional Edge Functions
# ──────────────────────────────────────────────


def route_by_query_type(state: AgentState) -> str:
    """Route to the appropriate branch based on query classification."""
    query_type = state.get("query_type", "general")
    error = state.get("error")

    if error:
        return "response_output"

    route_map = {
        "deadline": "retriever_deadline",
        "summary": "retriever_summary",
        "upload": "upload_handler",
        "general": "retriever_general",
        "source_explanation": "source_explainer",
    }

    route = route_map.get(query_type, "retriever_general")
    logger.info(f"Routing to: {route}")
    return route


def route_after_upload_handler(state: AgentState) -> str:
    """After upload handler, check if there was an error."""
    error = state.get("error")
    if error:
        return "response_output"
    return "location_classifier"


def route_after_location_classifier(state: AgentState) -> str:
    """
    After location classification, pause for human approval.
    This is where the interrupt happens.
    """
    return "human_approval_gate"


def route_after_human_approval(state: AgentState) -> str:
    """Route based on human decision about upload location."""
    decision = state.get("human_decision", "")

    if decision == "rejected":
        return "response_output"
    elif decision == "approved" or decision:
        return "upload_executor"
    else:
        # Still waiting — shouldn't reach here with interrupt
        return "response_output"


# ──────────────────────────────────────────────
# Human Approval Gate (for interrupt)
# ──────────────────────────────────────────────


async def human_approval_gate(state: AgentState) -> dict:
    """
    This node is where the graph pauses for human input.
    The interrupt_before on this node causes LangGraph to pause here.
    When resumed, the human_decision will be injected into state.
    """
    decision = state.get("human_decision", "")
    if not decision:
        # This shouldn't happen if interrupt works correctly
        return {"human_decision": "approved"}
    return {}


# ──────────────────────────────────────────────
# Graph Builder
# ──────────────────────────────────────────────


def build_graph(checkpointer=None) -> StateGraph:
    """
    Build the complete LangGraph agent graph.

    Args:
        checkpointer: Optional checkpointer for persistence
            (required for human-in-the-loop interrupts).

    Returns:
        Compiled LangGraph graph.

    Graph Structure:
        START
          → input_handler
          → router
          → [conditional routing by query_type]
            ├─ deadline → retriever → deadline_extractor → deadline_verifier → response_output
            ├─ summary  → retriever → summary_redirector → response_output
            ├─ upload   → upload_handler → location_classifier → [INTERRUPT] human_approval
            │                             → upload_executor → response_output
            └─ general  → retriever → general_responder → response_output
          → END
    """
    graph = StateGraph(AgentState)

    # ── Add Nodes ──
    graph.add_node("input_handler", input_handler)
    graph.add_node("router", router)

    # Retriever nodes (separate instances for different branches so
    # we can see which branch triggered retrieval in traces)
    graph.add_node("retriever_deadline", retriever)
    graph.add_node("retriever_summary", retriever)
    graph.add_node("retriever_general", retriever)

    # Deadline branch
    graph.add_node("deadline_extractor", deadline_extractor)
    graph.add_node("deadline_verifier", deadline_verifier)

    # Summary branch
    graph.add_node("summary_redirector", summary_redirector)

    # General branch
    graph.add_node("general_responder", general_responder)

    # Source explanation branch
    graph.add_node("source_explainer", source_explainer)

    # Upload branch
    graph.add_node("upload_handler", upload_handler)
    graph.add_node("location_classifier", location_classifier)
    graph.add_node("human_approval_gate", human_approval_gate)
    graph.add_node("upload_executor", upload_executor)

    # Shared output
    graph.add_node("response_output", response_output)

    # ── Add Edges ──

    # Entry
    graph.add_edge(START, "input_handler")
    graph.add_edge("input_handler", "router")

    # Router → conditional branches
    graph.add_conditional_edges(
        "router",
        route_by_query_type,
        {
            "retriever_deadline": "retriever_deadline",
            "retriever_summary": "retriever_summary",
            "retriever_general": "retriever_general",
            "upload_handler": "upload_handler",
            "source_explainer": "source_explainer",
            "response_output": "response_output",
        },
    )

    # Deadline branch
    graph.add_edge("retriever_deadline", "deadline_extractor")
    graph.add_edge("deadline_extractor", "deadline_verifier")
    graph.add_edge("deadline_verifier", "response_output")

    # Summary branch
    graph.add_edge("retriever_summary", "summary_redirector")
    graph.add_edge("summary_redirector", "response_output")

    # General branch
    graph.add_edge("retriever_general", "general_responder")
    graph.add_edge("general_responder", "response_output")

    # Source explanation branch
    graph.add_edge("source_explainer", "response_output")

    # Upload branch
    graph.add_conditional_edges(
        "upload_handler",
        route_after_upload_handler,
        {
            "location_classifier": "location_classifier",
            "response_output": "response_output",
        },
    )
    graph.add_edge("location_classifier", "human_approval_gate")

    # After human approval
    graph.add_conditional_edges(
        "human_approval_gate",
        route_after_human_approval,
        {
            "upload_executor": "upload_executor",
            "response_output": "response_output",
        },
    )
    graph.add_edge("upload_executor", "response_output")

    # Exit
    graph.add_edge("response_output", END)

    # ── Compile ──
    compile_kwargs = {}
    if checkpointer:
        compile_kwargs["checkpointer"] = checkpointer
        # Interrupt before human_approval_gate so user can provide decision
        compile_kwargs["interrupt_before"] = ["human_approval_gate"]

    compiled = graph.compile(**compile_kwargs)

    logger.info("LangGraph agent compiled successfully")
    return compiled


# ──────────────────────────────────────────────
# Convenience: Create graph with SQLite checkpointer
# ──────────────────────────────────────────────


async def create_agent(db_path: str = "data/checkpoints.db"):
    """
    Create the agent with an async SQLite checkpointer for human-in-the-loop.

    Args:
        db_path: Path for the SQLite checkpoint database.

    Returns:
        Compiled LangGraph graph with checkpointer.
    """
    import aiosqlite
    from pathlib import Path

    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = await aiosqlite.connect(str(path))
    checkpointer = AsyncSqliteSaver(conn)

    return build_graph(checkpointer=checkpointer)

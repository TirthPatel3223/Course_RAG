"""
Response Output Node — Saves response to session history.
Final node before returning to the user.
"""

import logging
from backend.agent.state import AgentState
from backend.services.session_service import get_session_service

logger = logging.getLogger(__name__)


async def response_output(state: AgentState) -> dict:
    """
    Save the assistant's response to session history
    and finalize the state for output.
    """
    sessions = get_session_service()
    session_id = state.get("session_id", "")
    query_type = state.get("query_type", "unknown")
    final_response = state.get("final_response", "")
    source_chunks = state.get("source_chunks_for_display", [])

    if not final_response:
        final_response = "I'm sorry, I couldn't generate a response. Please try again."

    # Save assistant message to history
    if session_id:
        sessions.add_message(
            session_id=session_id,
            role="assistant",
            content=final_response,
            query_type=query_type,
            source_chunks=source_chunks if source_chunks else None,
        )

    logger.info(
        f"Response saved: type={query_type}, length={len(final_response)}, "
        f"sources={len(source_chunks)}"
    )

    return {
        "final_response": final_response,
    }

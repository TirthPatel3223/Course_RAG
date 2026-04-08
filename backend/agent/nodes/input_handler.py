"""
Input Handler Node — Parses user input and loads conversation context.
First node in the graph — prepares the state for routing.
"""

import json
import logging
from backend.agent.state import AgentState
from backend.services.session_service import get_session_service

logger = logging.getLogger(__name__)


async def input_handler(state: AgentState) -> dict:
    """
    Parse the incoming user message and load conversation history.

    Responsibilities:
    - Ensure session exists
    - Load conversation history for multi-turn context
    - Initialize state fields with defaults
    - Detect if there's a file attachment
    """
    session_id = state.get("session_id", "")
    sessions = get_session_service()

    # Create session if needed
    if not session_id or not sessions.validate_session(session_id):
        session_id = sessions.create_session()
        logger.info(f"Created new session: {session_id}")
    else:
        sessions.touch_session(session_id)

    # Get the latest user message from the messages list
    messages = state.get("messages", [])
    user_message = ""
    if messages:
        last_msg = messages[-1]
        if hasattr(last_msg, "content"):
            user_message = last_msg.content
        elif isinstance(last_msg, dict):
            user_message = last_msg.get("content", "")

    # Save user message to history
    if user_message:
        sessions.add_message(session_id, "user", user_message)

    # Initialize state defaults
    return {
        "session_id": session_id,
        "query_type": "unknown",
        "retrieved_chunks": [],
        "retrieval_query": user_message,
        "detected_course": None,
        "detected_quarter": None,
        "extracted_deadline": None,
        "verification_result": None,
        "relevant_files": [],
        "upload_file_info": state.get("upload_file_info"),
        "proposed_location": None,
        "human_decision": None,
        "upload_result": None,
        "final_response": "",
        "source_chunks_for_display": [],
        "response_files": [],
        "llm_provider": "",
        "error": None,
    }

"""
Router Node — Classifies user query into one of 4 types.
Also detects course and quarter context for metadata filtering.
"""

import json
import logging
from backend.agent.state import AgentState
from backend.agent.prompts import ROUTER_SYSTEM, ROUTER_USER, CONTEXT_DETECTION_SYSTEM
from backend.services.llm_service import get_llm_service
from backend.services.session_service import get_session_service
from backend.config import get_settings, COURSES

logger = logging.getLogger(__name__)


async def router(state: AgentState) -> dict:
    """
    Classify the user's query and detect context (course, quarter).

    Routes to: deadline, summary, upload, or general branch.
    """
    llm = get_llm_service()
    sessions = get_session_service()
    settings = get_settings()

    # Get conversation history for context
    history = sessions.get_messages_for_llm(state["session_id"], limit=10)
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[:-1]  # exclude current
    ) or "(No previous conversation)"

    # Get user's current message
    messages = state.get("messages", [])
    current_query = ""
    if messages:
        last_msg = messages[-1]
        current_query = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    # Check if there's a file attachment — auto-route to upload
    upload_info = state.get("upload_file_info")
    if upload_info:
        logger.info("File attachment detected — routing to upload")
        return {
            "query_type": "upload",
            "retrieval_query": current_query,
        }

    # Classify query type
    file_context = ""
    if upload_info:
        file_context = f"(User has attached a file: {upload_info.get('name', 'unknown')})"

    router_prompt = ROUTER_USER.format(
        history=history_text,
        query=current_query,
        file_context=file_context,
    )

    try:
        response = await llm.chat_with_json(
            messages=[{"role": "user", "content": router_prompt}],
            system_prompt=ROUTER_SYSTEM,
            max_tokens=200,
            temperature=0.0,
        )

        result = json.loads(response["content"])
        query_type = result.get("query_type", "general")
        provider = response.get("provider", "unknown")

        # Validate query type
        valid_types = {"deadline", "summary", "upload", "general"}
        if query_type not in valid_types:
            query_type = "general"

        logger.info(
            f"Router classified query as '{query_type}' "
            f"(reason: {result.get('reasoning', 'N/A')}, provider: {provider})"
        )
    except Exception as e:
        logger.error(f"Router classification failed: {e}, defaulting to 'general'")
        query_type = "general"
        provider = "error"

    # Detect course and quarter context
    detected_course = None
    detected_quarter = None
    optimized_query = current_query

    try:
        courses_list = "\n".join(
            f"- {c.short_code}: {c.display_name} (ID: {c.full_id})"
            for c in settings.get_current_courses()
        )

        context_prompt = f"""Query: {current_query}
Conversation context: {history_text}

Extract course and quarter context:"""

        context_response = await llm.chat_with_json(
            messages=[{"role": "user", "content": context_prompt}],
            system_prompt=CONTEXT_DETECTION_SYSTEM.format(
                quarter=settings.current_quarter,
                courses_list=courses_list,
            ),
            max_tokens=200,
            temperature=0.0,
        )

        context = json.loads(context_response["content"])
        detected_course = context.get("course_id")
        detected_quarter = context.get("quarter") or settings.current_quarter
        optimized_query = context.get("optimized_query", current_query)

        logger.info(
            f"Context: course={detected_course}, quarter={detected_quarter}, "
            f"query='{optimized_query[:60]}...'"
        )
    except Exception as e:
        logger.warning(f"Context detection failed: {e}")
        detected_quarter = settings.current_quarter

    return {
        "query_type": query_type,
        "detected_course": detected_course,
        "detected_quarter": detected_quarter,
        "retrieval_query": optimized_query,
        "llm_provider": provider,
    }

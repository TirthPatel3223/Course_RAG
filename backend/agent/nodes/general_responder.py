"""
General Responder Node — Answers general course questions using retrieved context.
"""

import logging
from backend.agent.state import AgentState
from backend.agent.prompts import GENERAL_RESPONSE_SYSTEM, GENERAL_RESPONSE_USER
from backend.services.llm_service import get_llm_service
from backend.services.session_service import get_session_service

logger = logging.getLogger(__name__)


async def general_responder(state: AgentState) -> dict:
    """
    Generate a contextual answer to a general course question.
    Uses retrieved chunks as context and includes source citations.
    """
    llm = get_llm_service()
    sessions = get_session_service()
    chunks = state.get("retrieved_chunks", [])

    # Get conversation history
    history = sessions.get_messages_for_llm(state["session_id"], limit=10)
    history_text = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in history[:-1]
    ) or "(No previous conversation)"

    # Get current query
    messages = state.get("messages", [])
    query = ""
    if messages:
        last_msg = messages[-1]
        query = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    # Format chunks
    chunks_text = ""
    if chunks:
        for i, chunk in enumerate(chunks, 1):
            meta = chunk.get("metadata", {})
            chunks_text += (
                f"\n--- Source {i}: {meta.get('file_name', 'Unknown')} "
                f"(Page {meta.get('page_number', 'N/A')}) ---\n"
                f"{chunk.get('document', '')}\n"
            )
    else:
        chunks_text = "(No relevant documents found in the database)"

    prompt = GENERAL_RESPONSE_USER.format(
        history=history_text,
        query=query,
        chunks=chunks_text,
    )

    try:
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=GENERAL_RESPONSE_SYSTEM,
            max_tokens=2048,
            temperature=0.1,
        )

        final_response = response["content"]
        provider = response.get("provider", "")

        # Append source references if we have chunks
        if chunks:
            seen_files = set()
            sources = "\n\n---\n<details>\n<summary>📎 Sources (click to expand)</summary>\n\n"
            for chunk in chunks:
                meta = chunk.get("metadata", {})
                fname = meta.get("file_name", "")
                if fname and fname not in seen_files:
                    seen_files.add(fname)
                    link = meta.get("drive_link", "")
                    if link:
                        sources += f"- [{fname}]({link})\n"
                    else:
                        sources += f"- {fname}\n"
            sources += "\n</details>"
            final_response += sources

        logger.info(f"General response generated ({provider})")

        return {
            "final_response": final_response,
            "llm_provider": provider,
        }
    except Exception as e:
        logger.error(f"General responder failed: {e}")
        return {
            "final_response": (
                "❌ I encountered an error generating a response. "
                f"Please try again. Error: {str(e)}"
            ),
            "error": str(e),
        }

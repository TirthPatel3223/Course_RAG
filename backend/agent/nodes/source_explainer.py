"""
Source Explainer Node — Shows the raw document excerpts that drove a previous response.

Flow:
  First call  → inspects session history for Q&A pairs that had source chunks.
                 If one pair → shows excerpts immediately.
                 If multiple → asks user to pick by number (stores options in state).
  Second call → user replied with a number; resolves and shows excerpts.
"""

import logging
from backend.agent.state import AgentState
from backend.agent.prompts import (
    SOURCE_CLARIFICATION_TEMPLATE,
    SOURCE_EVIDENCE_HEADER,
    SOURCE_CHUNK_TEMPLATE,
    SOURCE_NO_CHUNKS_RESPONSE,
    SOURCE_MORE_CHUNKS_NOTE,
)
from backend.services.session_service import get_session_service

logger = logging.getLogger(__name__)

MAX_CHUNKS_SHOWN = 10


def _format_chunks(question: str, chunks: list[dict]) -> str:
    """Render source chunks as a readable markdown block."""
    total = len(chunks)
    display = chunks[:MAX_CHUNKS_SHOWN]

    parts = [SOURCE_EVIDENCE_HEADER.format(question=question)]
    for i, chunk in enumerate(display, 1):
        file_name = chunk.get("file_name", "Unknown")
        page = chunk.get("page_number")
        course = chunk.get("course_id", "")
        text = chunk.get("text", "").strip()

        page_info = f" (Page {page})" if page else ""
        course_info = f" [{course}]" if course else ""

        parts.append(
            SOURCE_CHUNK_TEMPLATE.format(
                n=i,
                file_name=file_name,
                page_info=page_info,
                course_info=course_info,
                text=text,
            )
        )

    if total > MAX_CHUNKS_SHOWN:
        parts.append(SOURCE_MORE_CHUNKS_NOTE.format(extra=total - MAX_CHUNKS_SHOWN))

    return "".join(parts)


async def source_explainer(state: AgentState) -> dict:
    """
    Explain which document excerpts were used in a previous response.
    """
    sessions = get_session_service()
    session_id = state.get("session_id", "")

    # Get current user message
    messages = state.get("messages", [])
    current_query = ""
    if messages:
        last_msg = messages[-1]
        current_query = (
            last_msg.content if hasattr(last_msg, "content") else str(last_msg)
        ).strip()

    pending = state.get("pending_source_clarification")

    # ── Branch A: user is responding to a clarification question ──
    if pending:
        try:
            idx = int(current_query) - 1
        except ValueError:
            # Not a number — cancel and ask them to try again
            logger.info("Source clarification cancelled: non-numeric reply")
            return {
                "final_response": (
                    "I've cancelled the source explanation. "
                    "Please ask your question again if you'd like to see source excerpts."
                ),
                "pending_source_clarification": None,
            }

        if idx < 0 or idx >= len(pending):
            max_n = len(pending)
            return {
                "final_response": (
                    f"Please enter a number between 1 and {max_n}."
                ),
                # Keep pending so the user can try again
            }

        selected = pending[idx]
        final_response = _format_chunks(selected["question"], selected["chunks"])
        logger.info(f"Source explanation resolved for question index {idx}")
        return {
            "final_response": final_response,
            "pending_source_clarification": None,
        }

    # ── Branch B: first call — scan history for Q&A pairs with source chunks ──
    history = sessions.get_history(session_id, limit=40)

    qa_with_sources = []
    for i, msg in enumerate(history):
        if msg["role"] == "user" and i + 1 < len(history):
            next_msg = history[i + 1]
            if next_msg["role"] == "assistant" and next_msg.get("source_chunks"):
                qa_with_sources.append(
                    {
                        "question": msg["content"],
                        "chunks": next_msg["source_chunks"],
                    }
                )

    if not qa_with_sources:
        logger.info("Source explainer: no source chunks found in history")
        return {
            "final_response": SOURCE_NO_CHUNKS_RESPONSE,
            "pending_source_clarification": None,
        }

    if len(qa_with_sources) == 1:
        # Only one option — show it directly without asking
        selected = qa_with_sources[0]
        final_response = _format_chunks(selected["question"], selected["chunks"])
        logger.info("Source explanation: single Q&A pair, showing directly")
        return {
            "final_response": final_response,
            "pending_source_clarification": None,
        }

    # Multiple options — ask the user to pick
    question_list = "\n".join(
        f"{i + 1}. {pair['question'][:120]}{'...' if len(pair['question']) > 120 else ''}"
        for i, pair in enumerate(qa_with_sources)
    )
    clarification = SOURCE_CLARIFICATION_TEMPLATE.format(question_list=question_list)
    logger.info(f"Source clarification requested: {len(qa_with_sources)} options")
    return {
        "final_response": clarification,
        "pending_source_clarification": qa_with_sources,
    }

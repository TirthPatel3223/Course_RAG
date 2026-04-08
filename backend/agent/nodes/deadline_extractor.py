"""
Deadline Extractor Node — Extracts deadline info from retrieved chunks.
"""

import json
import logging
from datetime import datetime
from backend.agent.state import AgentState
from backend.agent.prompts import DEADLINE_EXTRACT_SYSTEM, DEADLINE_EXTRACT_USER
from backend.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


async def deadline_extractor(state: AgentState) -> dict:
    """
    Extract deadline information from retrieved document chunks.

    Uses LLM to parse assignment name, due date/time, and any notes
    from the raw document text.
    """
    llm = get_llm_service()
    chunks = state.get("retrieved_chunks", [])

    if not chunks:
        return {
            "extracted_deadlines": []
        }

    # Format chunks for the prompt
    chunks_text = ""
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata", {})
        chunks_text += (
            f"\n--- Chunk {i} ---\n"
            f"File: {meta.get('file_name', 'Unknown')}\n"
            f"Course: {meta.get('course_id', 'Unknown')}\n"
            f"Page: {meta.get('page_number', 'N/A')}\n"
            f"Content:\n{chunk.get('document', '')}\n"
        )

    # Get user query
    messages = state.get("messages", [])
    query = ""
    if messages:
        last_msg = messages[-1]
        query = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    prompt = DEADLINE_EXTRACT_USER.format(
        query=query, 
        current_date=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        chunks=chunks_text
    )

    try:
        response = await llm.chat_with_json(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=DEADLINE_EXTRACT_SYSTEM,
            max_tokens=2048,
            temperature=0.0,
        )

        result = json.loads(response["content"])
        deadlines = result.get("deadlines", [])
        
        logger.info(f"Deadlines extracted: {len(deadlines)}")

        return {
            "extracted_deadlines": deadlines,
            "llm_provider": response.get("provider", ""),
        }
    except Exception as e:
        logger.error(f"Deadline extraction failed: {e}")
        return {
            "extracted_deadlines": []
        }

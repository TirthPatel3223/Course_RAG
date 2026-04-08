"""
Summary Redirector Node — Finds relevant files and redirects user to use their own LLM.
Does NOT generate summaries; instead points to source documents.
"""

import json
import logging
from backend.agent.state import AgentState
from backend.agent.prompts import (
    SUMMARY_REDIRECT_SYSTEM,
    SUMMARY_REDIRECT_USER,
    SUMMARY_RESPONSE_TEMPLATE,
)
from backend.services.llm_service import get_llm_service

logger = logging.getLogger(__name__)


async def summary_redirector(state: AgentState) -> dict:
    """
    Identify relevant source files for the user's summary request.
    Returns file links and guidance to use personal LLM.
    """
    llm = get_llm_service()
    chunks = state.get("retrieved_chunks", [])

    if not chunks:
        return {
            "final_response": (
                "📚 **No Relevant Documents Found**\n\n"
                "I couldn't find documents matching your summary request. "
                "Try specifying the course or lecture number."
            ),
            "relevant_files": [],
            "response_files": [],
        }

    # Format chunks for the prompt
    chunks_text = ""
    for i, chunk in enumerate(chunks, 1):
        meta = chunk.get("metadata", {})
        chunks_text += (
            f"\n--- Chunk {i} ---\n"
            f"File: {meta.get('file_name', 'Unknown')}\n"
            f"Course: {meta.get('course_id', 'Unknown')} - {meta.get('course_name', '')}\n"
            f"Type: {meta.get('file_type', 'Unknown')}\n"
            f"Page: {meta.get('page_number', 'N/A')}\n"
            f"Content preview:\n{chunk.get('document', '')[:300]}\n"
        )

    messages = state.get("messages", [])
    query = ""
    if messages:
        last_msg = messages[-1]
        query = last_msg.content if hasattr(last_msg, "content") else str(last_msg)

    prompt = SUMMARY_REDIRECT_USER.format(query=query, chunks=chunks_text)

    try:
        response = await llm.chat_with_json(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=SUMMARY_REDIRECT_SYSTEM,
            max_tokens=800,
            temperature=0.0,
        )

        result = json.loads(response["content"])
        relevant_files_raw = result.get("relevant_files", [])
        guidance = result.get("guidance", "Use these files with your personal LLM.")
    except Exception as e:
        logger.error(f"Summary redirect failed: {e}")
        guidance = "I found some relevant documents. Use them with your personal LLM to generate a summary."
        relevant_files_raw = []

    # Build file list from chunks (deduplicated)
    seen_files = {}
    for chunk in chunks:
        meta = chunk.get("metadata", {})
        fname = meta.get("file_name", "")
        if fname and fname not in seen_files:
            seen_files[fname] = {
                "file_name": fname,
                "course_id": meta.get("course_id", ""),
                "course_name": meta.get("course_name", ""),
                "file_type": meta.get("file_type", ""),
                "drive_link": meta.get("drive_link", ""),
                "drive_file_id": meta.get("drive_file_id", ""),
                "pages": [],
            }
        if fname:
            page = meta.get("page_number")
            if page and page not in seen_files[fname]["pages"]:
                seen_files[fname]["pages"].append(page)

    # Merge LLM insights with chunk data
    relevant_files = list(seen_files.values())

    # Add relevance descriptions from LLM
    for llm_file in relevant_files_raw:
        for rf in relevant_files:
            if llm_file.get("file_name", "") in rf["file_name"]:
                rf["relevance"] = llm_file.get("relevance", "")
                break

    # Format file list for response
    file_list_text = ""
    response_files = []
    for i, f in enumerate(relevant_files, 1):
        icon = "📄" if f["file_type"] == "slides" else "📋" if f["file_type"] == "homeworks" else "📝"
        name = f["file_name"]
        link = f.get("drive_link", "")
        pages = f.get("pages", [])
        relevance = f.get("relevance", "")

        if link:
            file_entry = f"{i}. {icon} [{name}]({link})"
        else:
            file_entry = f"{i}. {icon} {name}"

        if pages:
            pages_sorted = sorted(pages)
            file_entry += f" — Pages {', '.join(str(p) for p in pages_sorted)}"

        if relevance:
            file_entry += f"\n   *{relevance}*"

        file_list_text += file_entry + "\n\n"

        response_files.append({
            "name": name,
            "drive_link": link,
            "drive_file_id": f.get("drive_file_id", ""),
            "pages": pages,
            "file_type": f["file_type"],
        })

    final_response = SUMMARY_RESPONSE_TEMPLATE.format(
        guidance=guidance,
        file_list=file_list_text or "No specific files identified.",
    )

    return {
        "final_response": final_response,
        "relevant_files": relevant_files,
        "response_files": response_files,
    }

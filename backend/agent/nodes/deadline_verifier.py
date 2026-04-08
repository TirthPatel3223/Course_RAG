"""
Deadline Verifier Node — Self-check by re-querying and cross-referencing.
"""

import json
import logging
from backend.agent.state import AgentState
from backend.agent.prompts import (
    DEADLINE_VERIFY_SYSTEM,
    DEADLINE_VERIFY_USER,
    DEADLINE_RESPONSE_TEMPLATE,
)
from backend.services.llm_service import get_llm_service
from backend.services.embedding_service import get_embedding_service
from backend.services.chroma_service import get_chroma_service

logger = logging.getLogger(__name__)


async def deadline_verifier(state: AgentState) -> dict:
    """
    Self-check the extracted deadlines by re-querying ChromaDB
    and cross-referencing results.
    """
    deadlines = state.get("extracted_deadlines", [])

    if not deadlines:
        # No deadline to verify — format a "not found" response
        return {
            "verification_result": {"verified": False, "conflicts": []},
            "final_response": (
                "**No Deadline Found**\n\n"
                "I couldn't find specific deadline information for your query "
                "in the available course documents. This could mean:\n"
                "- The deadline hasn't been announced in the slides yet\n"
                "- The assignment is from a different course\n"
                "- Try being more specific (e.g., 'When is MSA408 HW3 due?')"
            ),
        }

    llm = get_llm_service()
    embedder = get_embedding_service()
    chroma = get_chroma_service()

    # Re-query combining course context if possible
    courses = {d.get("course_id") for d in deadlines if d.get("course_id") and d.get("course_id") != "Unknown"}
    course = list(courses)[0] if len(courses) == 1 else None

    # Retrieve extra chunks generically
    verify_query = "deadlines due dates assignments exams " + " ".join([d.get("assignment_name", "") for d in deadlines])
    verify_embedding = await embedder.embed_query(verify_query)

    verify_chunks = chroma.query(
        query_embedding=verify_embedding,
        top_k=5,
        where={"course_id": course} if course else None,
    )

    # Format chunks for verification prompt
    chunks_text = ""
    for i, chunk in enumerate(verify_chunks, 1):
        meta = chunk.get("metadata", {})
        chunks_text += (
            f"\n--- Chunk {i} ---\n"
            f"File: {meta.get('file_name', 'Unknown')}\n"
            f"Content:\n{chunk.get('document', '')}\n"
        )
        
    deadlines_text_block = ""
    for i, d in enumerate(deadlines, 1):
        deadlines_text_block += f"- [{i}] Assignment: {d.get('assignment_name')}, Date: {d.get('due_date')}, Time: {d.get('due_time')}, Course: {d.get('course_id')}\n"

    try:
        prompt = DEADLINE_VERIFY_USER.format(
            deadlines_text=deadlines_text_block,
            chunks=chunks_text,
        )

        response = await llm.chat_with_json(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=DEADLINE_VERIFY_SYSTEM,
            max_tokens=2048,
            temperature=0.0,
        )

        verification_data = json.loads(response["content"])
        verified_deadlines = verification_data.get("verified_deadlines", [])
        
        # Build map of verified states
        verification_map = {}
        for vd in verified_deadlines:
            verification_map[vd.get("assignment_name", "Unknown").lower()] = vd
            
    except Exception as e:
        logger.error(f"Verification failed: {e}")
        verification_map = {}

    all_conflicts = []
    deadlines_list_str = ""

    for d in deadlines:
        assignment = d.get("assignment_name", "Unknown")
        date = d.get("due_date", "Unknown")
        time = d.get("due_time", "Not specified")
        course = d.get("course_id", "Unknown")
        notes = d.get("notes", "")
        confidence = d.get("confidence", "medium")
        
        vd = verification_map.get(assignment.lower(), {})
        
        if vd.get("corrected_date"):
            date = vd["corrected_date"]
        if vd.get("corrected_time"):
            time = vd["corrected_time"]
            
        cv = vd.get("confidence")
        if cv: confidence = cv
        
        if vd.get("conflicts"):
            all_conflicts.extend(vd["conflicts"])
            
        deadlines_list_str += f"**{assignment}** — {course}\n"
        deadlines_list_str += f"- Due Date: {date}\n"
        deadlines_list_str += f"- Due Time: {time if time else 'Not specified'}\n"
        deadlines_list_str += f"- Confidence: {confidence.capitalize()}\n"
        if notes:
            deadlines_list_str += f"- Notes: {notes}\n"
        deadlines_list_str += "\n"

    # Format source documents
    all_chunks = state.get("retrieved_chunks", []) + verify_chunks
    seen_files = set()
    sources_text = ""
    for chunk in all_chunks:
        meta = chunk.get("metadata", {})
        fname = meta.get("file_name", "Unknown")
        if fname not in seen_files:
            seen_files.add(fname)
            drive_link = meta.get("drive_link", "")
            page = meta.get("page_number", "")
            link_text = f"[{fname}]({drive_link})" if drive_link else fname
            sources_text += f"- {link_text}"
            if page:
                sources_text += f" (Page {page})"
            sources_text += "\n"

    # Build verification status
    if not all_conflicts and len(verification_map) > 0:
        verification_status = "**Verified** — Cross-checked against multiple sources."
    elif all_conflicts:
        conflict_text = "\n".join(f"- {c}" for c in all_conflicts)
        verification_status = (
            f"**Potential Conflicts Found:**\n{conflict_text}\n\n"
            "Please verify with your instructor."
        )
    else:
        verification_status = "Verification inconclusive — limited source data."

    # Format final response
    final_response = DEADLINE_RESPONSE_TEMPLATE.format(
        deadlines_list=deadlines_list_str.strip(),
        verification_status=verification_status,
        sources=sources_text or "No source documents available.",
    )

    return {
        "verification_result": {
            "verified": len(all_conflicts) == 0,
            "conflicts": all_conflicts,
        },
        "final_response": final_response,
    }

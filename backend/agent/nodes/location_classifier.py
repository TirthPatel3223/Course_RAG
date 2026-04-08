"""
Location Classifier Node — LLM proposes where to store uploaded file.
"""

import json
import logging
from backend.agent.state import AgentState
from backend.agent.prompts import (
    UPLOAD_CLASSIFY_SYSTEM,
    UPLOAD_CLASSIFY_USER,
    UPLOAD_APPROVAL_TEMPLATE,
)
from backend.services.llm_service import get_llm_service
from backend.config import get_settings

logger = logging.getLogger(__name__)


async def location_classifier(state: AgentState) -> dict:
    """
    Classify the uploaded file and propose a storage location.
    Prepares the human-in-the-loop approval request.
    """
    llm = get_llm_service()
    settings = get_settings()
    upload_info = state.get("upload_file_info", {})

    if not upload_info:
        return {"error": "No upload info available for classification"}

    filename = upload_info.get("name", "unknown")
    content_preview = upload_info.get("content_preview", "")

    # Build folder structure description
    structure = settings.get_drive_structure()
    structure_text = ""
    for quarter, courses in structure.items():
        structure_text += f"\n{quarter}/\n"
        for course_folder, subfolders in courses.items():
            for sub in subfolders:
                structure_text += f"  {course_folder}/{sub}/\n"

    prompt = UPLOAD_CLASSIFY_USER.format(
        filename=filename,
        content_preview=content_preview,
    )

    try:
        response = await llm.chat_with_json(
            messages=[{"role": "user", "content": prompt}],
            system_prompt=UPLOAD_CLASSIFY_SYSTEM.format(
                folder_structure=structure_text,
            ),
            max_tokens=500,
            temperature=0.0,
        )

        proposal = json.loads(response["content"])

        # Validate proposal has required fields
        required = ["quarter", "course_id", "file_type", "full_path"]
        for field in required:
            if field not in proposal:
                proposal[field] = "Unknown"

        # Build the full path if not provided
        if proposal.get("full_path") == "Unknown":
            course_name = proposal.get("course_name", "Unknown")
            proposal["full_path"] = (
                f"{proposal['quarter']}/"
                f"{proposal['course_id']}:{course_name}/"
                f"{proposal['file_type']}/"
                f"{proposal.get('suggested_filename', filename)}"
            )

        logger.info(
            f"Classification: {filename} → {proposal['full_path']} "
            f"(confidence: {proposal.get('confidence', 'unknown')})"
        )

        # Format approval request for the user
        approval_message = UPLOAD_APPROVAL_TEMPLATE.format(
            path=proposal["full_path"],
            reasoning=proposal.get("reasoning", "Based on file content analysis."),
        )

        return {
            "proposed_location": proposal,
            "final_response": approval_message,
        }

    except Exception as e:
        logger.error(f"Location classification failed: {e}")
        # Provide a default proposal
        return {
            "proposed_location": {
                "quarter": settings.current_quarter,
                "course_id": "Unknown",
                "file_type": "slides",
                "full_path": f"{settings.current_quarter}/Unknown/{filename}",
                "reasoning": f"Auto-classification failed: {str(e)}",
            },
            "final_response": (
                f"⚠️ I couldn't automatically classify this file.\n\n"
                f"**File:** {filename}\n\n"
                f"Please tell me:\n"
                f"1. Which course is this for?\n"
                f"2. Is this slides or a transcript?"
            ),
        }

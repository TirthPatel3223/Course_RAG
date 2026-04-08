"""
Upload Handler Node — Processes uploaded files for classification.
Handles both drag-and-drop and Drive link uploads.
"""

import logging
from backend.agent.state import AgentState
from backend.services.pdf_processor import get_pdf_processor
from backend.services.drive_service import get_drive_service

logger = logging.getLogger(__name__)


async def upload_handler(state: AgentState) -> dict:
    """
    Process the uploaded file — extract preview content for classification.

    Handles two upload sources:
    - Direct file upload (bytes in state)
    - Google Drive link (download from Drive)
    """
    upload_info = state.get("upload_file_info")

    if not upload_info:
        return {
            "final_response": (
                "📤 **No File Detected**\n\n"
                "Please either:\n"
                "- Drag and drop a file into the chat\n"
                "- Paste a Google Drive link"
            ),
            "error": "No file to upload",
        }

    source = upload_info.get("source", "unknown")
    filename = upload_info.get("name", "unknown")

    logger.info(f"Processing upload: {filename} (source: {source})")

    try:
        content_bytes = None
        content_preview = ""

        if source == "drive_link":
            # Download from Drive
            drive_link = upload_info.get("drive_link", "")
            drive = get_drive_service()
            file_id = drive.get_file_id_from_link(drive_link)

            if not file_id:
                return {
                    "final_response": "❌ Could not parse the Google Drive link. Please check the URL.",
                    "error": "Invalid Drive link",
                }

            # Get file info
            file_info = drive.get_file_info(file_id)
            filename = file_info.get("name", filename)
            content_bytes = drive.download_file(file_id)

        elif source == "direct_upload":
            content_bytes = upload_info.get("bytes")
            if not content_bytes:
                return {
                    "final_response": "❌ File upload was empty.",
                    "error": "Empty file",
                }

        # Extract text preview for classification
        if filename.lower().endswith(".pdf") and content_bytes:
            pdf_proc = get_pdf_processor()
            text = pdf_proc.extract_full_text_from_bytes(content_bytes, filename)
            content_preview = text[:2000]
        elif filename.lower().endswith(".txt") and content_bytes:
            content_preview = content_bytes.decode("utf-8", errors="replace")[:2000]
        else:
            content_preview = f"(Binary file: {filename}, {len(content_bytes or b'')} bytes)"

        # Update upload info with extracted data
        updated_info = {
            **upload_info,
            "name": filename,
            "content_preview": content_preview,
            "bytes": content_bytes,
            "size": len(content_bytes or b""),
        }

        logger.info(
            f"Upload processed: {filename}, "
            f"size={len(content_bytes or b'')} bytes, "
            f"preview={len(content_preview)} chars"
        )

        return {
            "upload_file_info": updated_info,
        }

    except Exception as e:
        logger.error(f"Upload handling failed: {e}")
        return {
            "final_response": f"❌ Failed to process the file: {str(e)}",
            "error": str(e),
        }

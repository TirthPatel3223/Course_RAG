"""
Upload Executor Node — Executes the approved file upload.
Uploads to Google Drive and embeds in ChromaDB.
"""

import logging
from backend.agent.state import AgentState
from backend.agent.prompts import UPLOAD_COMPLETE_TEMPLATE
from backend.services.drive_service import get_drive_service
from backend.services.pdf_processor import get_pdf_processor
from backend.services.text_processor import get_text_processor
from backend.services.embedding_service import get_embedding_service
from backend.services.chroma_service import get_chroma_service

logger = logging.getLogger(__name__)


async def upload_executor(state: AgentState) -> dict:
    """
    Execute the file upload after human approval.

    Steps:
    1. Upload file to Google Drive at the approved location
    2. Extract text from the file
    3. Chunk the text
    4. Generate embeddings
    5. Store in ChromaDB
    """
    upload_info = state.get("upload_file_info", {})
    proposal = state.get("proposed_location", {})
    decision = state.get("human_decision", "")

    if decision == "rejected":
        return {
            "final_response": "❌ Upload cancelled.",
            "upload_result": {"success": False, "message": "Rejected by user"},
        }

    # Use modified path if the user provided one
    if decision and decision not in ("approved", "rejected"):
        # User provided a modified path
        proposal["full_path"] = decision

    filename = upload_info.get("name", "unknown")
    content_bytes = upload_info.get("bytes")

    if not content_bytes:
        return {
            "final_response": "❌ No file content available for upload.",
            "upload_result": {"success": False, "message": "No file content"},
        }

    try:
        drive = get_drive_service()
        pdf_proc = get_pdf_processor()
        text_proc = get_text_processor()
        embedder = get_embedding_service()
        chroma = get_chroma_service()

        full_path = proposal.get("full_path", "")
        # Split path into folder and filename
        path_parts = full_path.rsplit("/", 1)
        if len(path_parts) == 2:
            folder_path, upload_filename = path_parts
        else:
            folder_path = full_path
            upload_filename = filename

        # Step 1: Upload to Drive
        logger.info(f"Uploading {upload_filename} to Drive: {folder_path}")
        drive_result = drive.upload_file_from_bytes(
            content=content_bytes,
            filename=upload_filename,
            drive_folder_path=folder_path,
        )

        drive_file_id = drive_result.get("id", "")
        drive_link = drive_result.get("webViewLink", "")

        # Step 2: Extract text (with OCR fallback for scanned PDFs)
        if upload_filename.lower().endswith(".pdf"):
            pages = await pdf_proc.extract_pages_with_ocr(content_bytes, upload_filename)
            file_metadata = text_proc.build_file_metadata(
                file_name=upload_filename,
                file_type=proposal.get("file_type", "slides"),
                quarter=proposal.get("quarter", ""),
                course_id=proposal.get("course_id", ""),
                course_name=proposal.get("course_name", ""),
                drive_file_id=drive_file_id,
                drive_link=drive_link,
            )
            chunks = text_proc.chunk_slides(pages, file_metadata)
        elif upload_filename.lower().endswith(".txt"):
            text = content_bytes.decode("utf-8", errors="replace")
            file_metadata = text_proc.build_file_metadata(
                file_name=upload_filename,
                file_type=proposal.get("file_type", "transcripts"),
                quarter=proposal.get("quarter", ""),
                course_id=proposal.get("course_id", ""),
                course_name=proposal.get("course_name", ""),
                drive_file_id=drive_file_id,
                drive_link=drive_link,
            )
            chunks = text_proc.chunk_transcript(text, file_metadata)
        else:
            chunks = []
            logger.warning(f"Unsupported file type for embedding: {upload_filename}")

        # Step 3 & 4: Embed and store
        chunks_embedded = 0
        if chunks:
            chunk_texts = [c.text for c in chunks]
            embeddings = await embedder.embed_batch(chunk_texts)

            chunk_ids = [c.chunk_id for c in chunks]
            chunk_metadatas = [c.metadata for c in chunks]

            chroma.add_documents(
                ids=chunk_ids,
                embeddings=embeddings,
                documents=chunk_texts,
                metadatas=chunk_metadatas,
            )
            chunks_embedded = len(chunks)

        logger.info(
            f"Upload complete: {upload_filename} → {folder_path}, "
            f"{chunks_embedded} chunks embedded"
        )

        # Format response
        final_response = UPLOAD_COMPLETE_TEMPLATE.format(
            filename=upload_filename,
            location=folder_path,
            drive_link=drive_link,
            chunks=chunks_embedded,
        )

        return {
            "final_response": final_response,
            "upload_result": {
                "success": True,
                "drive_link": drive_link,
                "drive_file_id": drive_file_id,
                "chunks_embedded": chunks_embedded,
                "location": folder_path,
            },
        }

    except Exception as e:
        logger.error(f"Upload execution failed: {e}")
        return {
            "final_response": f"❌ Upload failed: {str(e)}",
            "upload_result": {"success": False, "message": str(e)},
            "error": str(e),
        }

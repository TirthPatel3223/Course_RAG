"""
Admin Routes — System management endpoints.
Re-embedding, stats, session cleanup.
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from backend.api.auth import get_current_user
from backend.config import get_settings
from backend.services.chroma_service import get_chroma_service
from backend.services.session_service import get_session_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])

# Track re-embedding status
_reembed_status = {
    "status": "idle",
    "progress": 0.0,
    "message": "",
    "files_processed": 0,
    "total_files": 0,
    "chunks_created": 0,
}


class ReembedRequest(BaseModel):
    quarter: Optional[str] = None
    course_id: Optional[str] = None
    clear_existing: bool = True


@router.get("/stats")
async def get_system_stats(_: bool = Depends(get_current_user)):
    """Get system health and statistics."""
    chroma = get_chroma_service()
    sessions = get_session_service()
    settings = get_settings()

    chroma_stats = chroma.get_stats()

    return {
        "chroma": chroma_stats,
        "sessions": {
            "active_count": sessions.get_session_count(),
        },
        "config": {
            "current_quarter": settings.current_quarter,
            "claude_model": settings.claude_model,
            "openai_model": settings.openai_chat_model,
            "embedding_model": settings.openai_embedding_model,
            "courses": [
                {
                    "code": c.short_code,
                    "name": c.display_name,
                    "full_id": c.full_id,
                }
                for c in settings.get_current_courses()
            ],
        },
    }


@router.post("/reembed")
async def trigger_reembed(
    request: ReembedRequest,
    background_tasks: BackgroundTasks,
    _: bool = Depends(get_current_user),
):
    """Trigger re-embedding of documents from Google Drive."""
    global _reembed_status

    if _reembed_status["status"] == "running":
        raise HTTPException(
            status_code=409,
            detail="Re-embedding is already in progress",
        )

    _reembed_status = {
        "status": "running",
        "progress": 0.0,
        "message": "Starting re-embedding...",
        "files_processed": 0,
        "total_files": 0,
        "chunks_created": 0,
    }

    background_tasks.add_task(
        _run_reembed,
        quarter=request.quarter,
        course_id=request.course_id,
        clear_existing=request.clear_existing,
    )

    return {"status": "started", "message": "Re-embedding started in background"}


@router.get("/reembed/status")
async def get_reembed_status(_: bool = Depends(get_current_user)):
    """Get the current re-embedding status."""
    return _reembed_status


@router.post("/sessions/cleanup")
async def cleanup_sessions(_: bool = Depends(get_current_user)):
    """Remove expired sessions."""
    sessions = get_session_service()
    deleted = sessions.cleanup_expired_sessions()
    return {"deleted": deleted, "message": f"Cleaned up {deleted} expired sessions"}


@router.get("/drive/tree")
async def get_drive_tree(_: bool = Depends(get_current_user)):
    """Get the Google Drive folder tree."""
    try:
        from backend.services.drive_service import get_drive_service
        drive = get_drive_service()
        drive.authenticate()
        tree = drive.get_folder_tree(max_depth=3)
        return tree
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drive error: {str(e)}")


@router.get("/drive/files")
async def list_drive_files(
    quarter: Optional[str] = None,
    _: bool = Depends(get_current_user),
):
    """List all files on Drive."""
    try:
        from backend.services.drive_service import get_drive_service
        drive = get_drive_service()
        drive.authenticate()
        files = drive.list_all_course_files(quarter=quarter)
        return {"files": files, "count": len(files)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Drive error: {str(e)}")


async def _run_reembed(
    quarter: Optional[str] = None,
    course_id: Optional[str] = None,
    clear_existing: bool = True,
):
    """Background task: re-embed documents from Drive."""
    global _reembed_status

    try:
        from backend.services.drive_service import DriveService
        from backend.services.pdf_processor import PDFProcessor
        from backend.services.text_processor import TextProcessor
        from backend.services.embedding_service import EmbeddingService
        from backend.services.chroma_service import ChromaService

        drive = DriveService()
        drive.authenticate()
        pdf_proc = PDFProcessor()
        text_proc = TextProcessor()
        embedder = EmbeddingService()
        chroma = ChromaService()

        # Clear existing if requested
        if clear_existing:
            if quarter:
                chroma.delete_by_quarter(quarter)
            else:
                chroma.delete_all()
            _reembed_status["message"] = "Cleared existing embeddings"

        # List all files
        all_files = await asyncio.to_thread(drive.list_all_course_files, quarter=quarter)
        if course_id:
            all_files = [f for f in all_files if f.get("course_id") == course_id]

        _reembed_status["total_files"] = len(all_files)
        _reembed_status["message"] = f"Found {len(all_files)} files to process"

        # Process each file
        for i, file_info in enumerate(all_files):
            filename = file_info.get("name", "unknown")
            _reembed_status["message"] = f"Processing: {filename}"
            _reembed_status["progress"] = i / max(len(all_files), 1)

            try:
                # Download
                content = await asyncio.to_thread(drive.download_file, file_info["id"])

                # Build metadata
                drive_link = file_info.get("webViewLink", "")
                metadata = text_proc.build_file_metadata(
                    file_name=filename,
                    file_type=file_info.get("file_type", "slides"),
                    quarter=file_info.get("quarter", ""),
                    course_id=file_info.get("course_id", ""),
                    course_name=file_info.get("course_name", ""),
                    drive_file_id=file_info["id"],
                    drive_link=drive_link,
                )

                # Extract and chunk
                if filename.lower().endswith(".pdf"):
                    pages = await pdf_proc.extract_pages_from_bytes_async(
                        content, filename, use_vision_fallback=True
                    )
                    chunks = text_proc.chunk_slides(pages, metadata)
                elif filename.lower().endswith(".txt"):
                    text = content.decode("utf-8", errors="replace")
                    chunks = text_proc.chunk_transcript(text, metadata)
                else:
                    continue

                if chunks:
                    # Embed
                    chunk_texts = [c.text for c in chunks]
                    embeddings = await embedder.embed_batch(chunk_texts)

                    # Store
                    await asyncio.to_thread(
                        chroma.add_documents,
                        ids=[c.chunk_id for c in chunks],
                        embeddings=embeddings,
                        documents=chunk_texts,
                        metadatas=[c.metadata for c in chunks],
                    )
                    _reembed_status["chunks_created"] += len(chunks)

                _reembed_status["files_processed"] += 1

            except Exception as e:
                logger.error(f"Failed to process {filename}: {e}")

        _reembed_status["status"] = "completed"
        _reembed_status["progress"] = 1.0
        _reembed_status["message"] = (
            f"Completed: {_reembed_status['files_processed']} files, "
            f"{_reembed_status['chunks_created']} chunks"
        )
        logger.info(_reembed_status["message"])

    except Exception as e:
        _reembed_status["status"] = "failed"
        _reembed_status["message"] = f"Failed: {str(e)}"
        logger.error(f"Re-embedding failed: {e}", exc_info=True)

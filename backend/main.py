"""
FastAPI Main Application — Entry point for the Course RAG backend.
Serves the API, WebSocket, and static frontend files.
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse

from backend.config import get_settings
from backend.api.auth import verify_password, get_current_user
from backend.api.routes_chat import router as chat_router
from backend.api.routes_admin import router as admin_router
from backend.models.schemas import LoginRequest, LoginResponse

# ──────────────────────────────────────────────
# Logging
# ──────────────────────────────────────────────

settings = get_settings()
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────
# App Setup
# ──────────────────────────────────────────────

app = FastAPI(
    title="Course RAG API",
    description="UCLA MSBA Course Document RAG Pipeline",
    version="1.0.0",
)

# CORS — allow frontend access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Will be restricted in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────
# Include Routers
# ──────────────────────────────────────────────

app.include_router(chat_router)
app.include_router(admin_router)

# ──────────────────────────────────────────────
# Auth Endpoints
# ──────────────────────────────────────────────


@app.post("/api/login", response_model=LoginResponse)
async def login(request: LoginRequest):
    """Authenticate with password and receive a token."""
    token = verify_password(request.password)
    if token:
        return LoginResponse(
            success=True,
            message="Authentication successful",
            token=token,
        )
    return LoginResponse(
        success=False,
        message="Invalid password",
        token=None,
    )


@app.get("/api/verify")
async def verify_token(_: bool = Depends(get_current_user)):
    """Verify that the current token is still valid."""
    return {"valid": True}


# ──────────────────────────────────────────────
# Health Check
# ──────────────────────────────────────────────


@app.get("/api/health")
async def health_check():
    """Health check endpoint (no auth required)."""
    return {
        "status": "ok",
        "version": "1.0.0",
        "quarter": settings.current_quarter,
    }


# ──────────────────────────────────────────────
# Chat History (REST fallback)
# ──────────────────────────────────────────────


@app.get("/api/chat/history/{session_id}")
async def get_chat_history(
    session_id: str,
    _: bool = Depends(get_current_user),
):
    """Get chat history for a session (REST endpoint)."""
    from backend.services.session_service import get_session_service
    sessions = get_session_service()

    if not sessions.validate_session(session_id):
        raise HTTPException(status_code=404, detail="Session not found or expired")

    history = sessions.get_history(session_id)
    return {"session_id": session_id, "messages": history}


# ──────────────────────────────────────────────
# Static Frontend Files
# ──────────────────────────────────────────────

FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.get("/")
async def serve_index():
    """Serve the main frontend page."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse(
        {"message": "Course RAG API is running. Frontend not yet deployed."},
        status_code=200,
    )


# Mount static files (CSS, JS, assets) if frontend dir exists
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


# ──────────────────────────────────────────────
# Startup / Shutdown Events
# ──────────────────────────────────────────────


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    logger.info("=" * 50)
    logger.info("Course RAG API starting up...")
    logger.info(f"Quarter: {settings.current_quarter}")
    logger.info(f"Claude model: {settings.claude_model}")
    logger.info(f"OpenAI model: {settings.openai_chat_model}")
    logger.info(f"Embedding model: {settings.openai_embedding_model}")
    logger.info("=" * 50)

    # Pre-initialize services
    try:
        from backend.services.chroma_service import get_chroma_service
        chroma = get_chroma_service()
        logger.info(f"ChromaDB: {chroma.count} documents loaded")
    except Exception as e:
        logger.warning(f"ChromaDB init deferred: {e}")

    try:
        from backend.services.session_service import get_session_service
        sessions = get_session_service()
        cleaned = sessions.cleanup_expired_sessions()
        if cleaned:
            logger.info(f"Cleaned up {cleaned} expired sessions")
    except Exception as e:
        logger.warning(f"Session service init deferred: {e}")


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    logger.info("Course RAG API shutting down...")

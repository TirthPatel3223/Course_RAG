"""
Pydantic models for API requests, responses, and internal data structures.
"""

from datetime import datetime
from typing import Optional, Literal
from pydantic import BaseModel, Field


# ──────────────────────────────────────────────
# Authentication
# ──────────────────────────────────────────────


class LoginRequest(BaseModel):
    password: str


class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[str] = None


# ──────────────────────────────────────────────
# Chat
# ──────────────────────────────────────────────


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    query_type: Optional[str] = None
    source_chunks: Optional[list[dict]] = None
    timestamp: Optional[str] = None


class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    message: str
    query_type: str
    source_chunks: list[dict] = Field(default_factory=list)
    relevant_files: list[dict] = Field(default_factory=list)
    session_id: str
    provider: str = ""  # "claude" or "openai"


# ──────────────────────────────────────────────
# Upload
# ──────────────────────────────────────────────


class UploadLocationProposal(BaseModel):
    """LLM's proposed location for an uploaded file."""

    quarter: str
    course_id: str
    course_name: str
    file_type: Literal["slides", "transcripts", "homeworks"]
    suggested_filename: str
    full_path: str
    reasoning: str


class UploadApproval(BaseModel):
    """User's response to a location proposal."""

    approved: bool
    modified_path: Optional[str] = None  # If user wants a different path


class UploadResult(BaseModel):
    """Result of a completed upload."""

    success: bool
    message: str
    drive_link: Optional[str] = None
    file_name: str = ""
    location: str = ""
    chunks_embedded: int = 0


# ──────────────────────────────────────────────
# Deadline
# ──────────────────────────────────────────────


class DeadlineInfo(BaseModel):
    """Extracted deadline information."""

    assignment_name: str
    course_id: str
    due_date: str
    due_time: Optional[str] = None
    notes: Optional[str] = None
    confidence: Literal["high", "medium", "low"] = "medium"


class DeadlineVerification(BaseModel):
    """Result of deadline self-check."""

    verified: bool
    original: DeadlineInfo
    conflicts: list[str] = Field(default_factory=list)
    source_chunks: list[dict] = Field(default_factory=list)


# ──────────────────────────────────────────────
# Admin
# ──────────────────────────────────────────────


class ReembedRequest(BaseModel):
    quarter: Optional[str] = None  # None = re-embed all quarters
    course_id: Optional[str] = None  # None = all courses in quarter


class ReembedStatus(BaseModel):
    status: Literal["idle", "running", "completed", "failed"]
    progress: float = 0.0  # 0.0 to 1.0
    message: str = ""
    files_processed: int = 0
    total_files: int = 0
    chunks_created: int = 0


class SystemStats(BaseModel):
    """System health and statistics."""

    total_chunks: int = 0
    quarters: list[str] = Field(default_factory=list)
    courses: list[str] = Field(default_factory=list)
    unique_files: int = 0
    llm_providers: list[str] = Field(default_factory=list)
    embedding_model: str = ""
    chroma_collection: str = ""


# ──────────────────────────────────────────────
# WebSocket Messages
# ──────────────────────────────────────────────


class WSMessage(BaseModel):
    """WebSocket message envelope."""

    type: Literal[
        "chat",
        "upload_file",
        "upload_link",
        "upload_approval",
        "reembed",
        "status",
        "error",
        "response",
        "approval_request",
        "progress",
    ]
    data: dict = Field(default_factory=dict)
    session_id: Optional[str] = None

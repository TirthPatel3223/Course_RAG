"""
Application configuration — loaded from .env file.
Defines all settings, course mappings, and constants.
"""

import os
from pathlib import Path
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional


# Project root directory
PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class CourseInfo:
    """Represents a single course with its identifiers."""

    def __init__(self, short_code: str, full_id: str, name: str):
        self.short_code = short_code  # e.g., "MSA408"
        self.full_id = full_id  # e.g., "26S-MGMTMSA-408-LEC-2"
        self.name = name  # e.g., "Operations_Analytics"
        self.display_name = name.replace("_", " ")  # e.g., "Operations Analytics"

    @property
    def folder_name(self) -> str:
        """Drive folder name: 'MSA408:Operations_Analytics'"""
        return f"{self.short_code}:{self.name}"

    def __repr__(self) -> str:
        return f"CourseInfo({self.short_code}: {self.display_name})"


# ──────────────────────────────────────────────
# Course Registry — Spring 2026
# ──────────────────────────────────────────────
COURSES = {
    "Spring2026": [
        CourseInfo("MSA408", "26S-MGMTMSA-408-LEC-2", "Operations_Analytics"),
        CourseInfo("MSA409", "26S-MGMTMSA-409-01/02", "Competitive_Analytics"),
        CourseInfo("MSA410", "26S-MGMTMSA-410-LEC-2", "Customer_Analytics"),
        CourseInfo("MSA413", "26S-MGMTMSA-413-SEM-1", "Industry_Seminar_II"),
    ],
}

# Quick lookup: short_code -> CourseInfo (across all quarters)
COURSE_LOOKUP: dict[str, CourseInfo] = {}
for quarter, courses in COURSES.items():
    for course in courses:
        COURSE_LOOKUP[course.short_code] = course
        # Also index by full_id for upload classification
        COURSE_LOOKUP[course.full_id] = course

# All known quarter names
KNOWN_QUARTERS = list(COURSES.keys())

# ──────────────────────────────────────────────
# Application Settings
# ──────────────────────────────────────────────


class Settings(BaseSettings):
    """Application settings loaded from .env file."""

    # --- LLM API Keys ---
    anthropic_api_key: str = Field(default="", description="Anthropic API key for Claude")
    openai_api_key: str = Field(default="", description="OpenAI API key")

    # --- Authentication ---
    app_password: str = Field(default="changeme", description="Legacy single-password (unused)")
    admin_username: str = Field(default="admin", description="Admin username")
    admin_password: str = Field(default="changeme", description="Admin password")
    viewer_username: str = Field(default="viewer", description="Viewer username")
    viewer_password: str = Field(default="changeme", description="Viewer password")

    # --- Google Drive ---
    google_credentials_path: str = Field(
        default="credentials/oauth_credentials.json",
        description="Path to Google OAuth credentials JSON",
    )
    google_token_path: str = Field(
        default="credentials/token.pickle",
        description="Path to store OAuth token",
    )
    drive_root_folder: str = Field(
        default="Course_RAG_Data",
        description="Root folder name on Google Drive",
    )

    # --- ChromaDB ---
    chroma_persist_dir: str = Field(
        default="data/chroma_db",
        description="ChromaDB persistent storage directory",
    )
    chroma_collection_name: str = Field(
        default="course_documents",
        description="ChromaDB collection name",
    )

    # --- Application ---
    current_quarter: str = Field(
        default="Spring2026",
        description="Currently active academic quarter",
    )
    host: str = Field(default="0.0.0.0", description="Server host")
    port: int = Field(default=8000, description="Server port")
    log_level: str = Field(default="INFO", description="Logging level")

    # --- LLM Model Settings ---
    claude_model: str = Field(
        default="claude-3-5-haiku-20241022",
        description="Claude model to use",
    )
    openai_chat_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI chat model (fallback)",
    )
    openai_embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="Embedding vector dimensions",
    )

    # --- OCR Settings ---
    ocr_dpi: int = Field(
        default=200,
        description="DPI for rendering PDF pages to images for OCR",
    )
    ocr_fallback_threshold: int = Field(
        default=30,
        description="Minimum characters of extracted text below which OCR is triggered",
    )

    # --- Chunking Settings ---
    slide_overlap_lines: int = Field(
        default=2,
        description="Number of lines from previous page to include as overlap for slides",
    )
    transcript_chunk_size: int = Field(
        default=1500,
        description="Character count per transcript chunk",
    )
    transcript_chunk_overlap: int = Field(
        default=200,
        description="Character overlap between transcript chunks",
    )

    # --- Retrieval Settings ---
    deadline_top_k: int = Field(default=5, description="Top-k for deadline queries")
    summary_top_k: int = Field(default=10, description="Top-k for summary queries")
    general_top_k: int = Field(default=7, description="Top-k for general queries")

    # --- Session Settings ---
    session_db_path: str = Field(
        default="data/sessions.db",
        description="SQLite database path for sessions",
    )
    session_timeout_hours: int = Field(
        default=24,
        description="Session timeout in hours",
    )

    model_config = {
        "env_file": str(PROJECT_ROOT / ".env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
    }

    def get_chroma_persist_path(self) -> Path:
        """Get absolute path for ChromaDB storage."""
        path = Path(self.chroma_persist_dir)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.mkdir(parents=True, exist_ok=True)
        return path

    def get_session_db_path(self) -> Path:
        """Get absolute path for sessions database."""
        path = Path(self.session_db_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def get_credentials_path(self) -> Path:
        """Get absolute path for Google credentials."""
        path = Path(self.google_credentials_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def get_token_path(self) -> Path:
        """Get absolute path for Google OAuth token."""
        path = Path(self.google_token_path)
        if not path.is_absolute():
            path = PROJECT_ROOT / path
        return path

    def get_current_courses(self) -> list[CourseInfo]:
        """Get courses for the current quarter."""
        return COURSES.get(self.current_quarter, [])

    def get_drive_structure(self) -> dict:
        """Generate the expected Drive folder structure."""
        structure = {}
        for quarter, courses in COURSES.items():
            structure[quarter] = {}
            for course in courses:
                structure[quarter][course.folder_name] = ["slides", "transcripts", "homeworks"]
        return structure


# Singleton settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get or create the singleton Settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


# ──────────────────────────────────────────────
# Deadline Keywords for metadata tagging
# ──────────────────────────────────────────────
DEADLINE_KEYWORDS = [
    "due",
    "deadline",
    "submit",
    "submission",
    "assignment",
    "homework",
    "hw",
    "exam",
    "midterm",
    "final",
    "quiz",
    "project",
    "deliverable",
    "turn in",
    "handed in",
    "due date",
    "due by",
]

"""
Agent State — Defines the shared state for the LangGraph agent.
All nodes read from and write to this state.
"""

from typing import Annotated, Optional, Literal
from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """
    Extended state for the Course RAG agent.
    Inherits from MessagesState which provides the 'messages' key
    with automatic message accumulation.
    """

    # ── Query Classification ──
    query_type: Literal["deadline", "summary", "upload", "general", "unknown"]
    """The classified type of the user's query."""

    # ── Retrieval Results ──
    retrieved_chunks: list[dict]
    """Chunks retrieved from ChromaDB with their metadata."""

    retrieval_query: str
    """The optimized query used for retrieval (may differ from raw user input)."""

    # ── Metadata Filters ──
    detected_course: Optional[str]
    """Course ID detected from the user's query (e.g., 'MSA408')."""

    detected_quarter: Optional[str]
    """Quarter detected from the user's query (e.g., 'Spring2026')."""

    # ── Deadline Branch ──
    extracted_deadlines: list[dict]
    """Extracted deadlines info: list of {assignment, course_id, due_date, due_time, notes, confidence, source_quote}."""

    verification_result: Optional[dict]
    """Self-check result: {verified, conflicts, source_chunks}."""

    # ── Summary Branch ──
    relevant_files: list[dict]
    """Files relevant to the summary query: [{name, drive_link, pages}]."""

    # ── Upload Branch ──
    upload_file_info: Optional[dict]
    """Info about the file being uploaded: {name, content_preview, source, bytes}."""

    proposed_location: Optional[dict]
    """LLM-proposed upload location: {quarter, course_id, file_type, path, reasoning}."""

    human_decision: Optional[str]
    """Human response to upload proposal: 'approved', 'rejected', or modified path."""

    upload_result: Optional[dict]
    """Result of the upload: {success, drive_link, chunks_embedded}."""

    # ── Response ──
    final_response: str
    """The formatted response to send to the user."""

    source_chunks_for_display: list[dict]
    """Source chunks to show in the UI (expandable)."""

    response_files: list[dict]
    """Files to offer for download/viewing in the UI."""

    # ── Session ──
    session_id: str
    """Active session ID for conversation continuity."""

    llm_provider: str
    """Which LLM was used: 'claude' or 'openai'."""

    error: Optional[str]
    """Error message if something went wrong."""

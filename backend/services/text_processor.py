"""
Text Processor — Chunking logic for slides and transcripts.
Converts raw text into chunks ready for embedding with appropriate metadata.
"""

import hashlib
import logging
import re
from typing import Optional

from backend.config import get_settings, DEADLINE_KEYWORDS
from backend.services.pdf_processor import PDFPage

logger = logging.getLogger(__name__)


class DocumentChunk:
    """A single chunk of text with its metadata, ready for embedding."""

    def __init__(
        self,
        chunk_id: str,
        text: str,
        metadata: dict,
    ):
        self.chunk_id = chunk_id
        self.text = text
        self.metadata = metadata

    def __repr__(self) -> str:
        preview = self.text[:60].replace("\n", " ") + "..."
        return f"DocumentChunk(id={self.chunk_id}, text='{preview}')"


class TextProcessor:
    """
    Processes extracted text into chunks suitable for embedding and retrieval.

    Two strategies:
    - Slide PDFs: Page-level chunking with overlap
    - Transcripts: Recursive character splitting with overlap

    Usage:
        processor = TextProcessor()
        chunks = processor.chunk_slides(pages, file_metadata)
        chunks = processor.chunk_transcript(text, file_metadata)
    """

    def __init__(self):
        settings = get_settings()
        self._slide_overlap_lines = settings.slide_overlap_lines
        self._transcript_chunk_size = settings.transcript_chunk_size
        self._transcript_chunk_overlap = settings.transcript_chunk_overlap

    def chunk_slides(
        self,
        pages: list[PDFPage],
        file_metadata: dict,
    ) -> list[DocumentChunk]:
        """
        Create chunks from slide PDF pages. Each page = one chunk,
        with overlap from the previous page's last N lines.

        Args:
            pages: List of PDFPage objects from PDFProcessor.
            file_metadata: Base metadata dict with keys like
                quarter, course_id, course_name, file_name, file_type,
                drive_file_id, drive_link.

        Returns:
            List of DocumentChunk objects.
        """
        chunks = []
        prev_page_lines: list[str] = []

        for page in pages:
            if page.is_empty:
                # Keep track of lines for overlap even on empty pages
                prev_page_lines = []
                continue

            # Build chunk text with overlap from previous page
            text_parts = []
            if prev_page_lines and self._slide_overlap_lines > 0:
                overlap_lines = prev_page_lines[-self._slide_overlap_lines :]
                overlap_text = "\n".join(overlap_lines)
                text_parts.append(f"[Previous slide context]\n{overlap_text}\n")

            text_parts.append(page.text)
            chunk_text = "\n".join(text_parts)

            # Check for deadline keywords
            contains_deadline = self._check_deadline_keywords(page.text)

            # Build chunk metadata
            chunk_meta = {
                **file_metadata,
                "page_number": page.page_number,
                "total_pages": page.total_pages,
                "chunk_index": len(chunks),
                "has_images": page.has_images,
                "image_count": page.image_count,
                "contains_deadline": contains_deadline,
            }

            # Generate unique chunk ID
            chunk_id = self._generate_chunk_id(
                file_metadata.get("file_name", "unknown"),
                page.page_number,
            )

            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    metadata=chunk_meta,
                )
            )

            # Store current page lines for next page's overlap
            prev_page_lines = page.text.split("\n")

        # Set total_chunks on all chunk metadata
        for chunk in chunks:
            chunk.metadata["total_chunks"] = len(chunks)

        logger.info(
            f"Chunked slides '{file_metadata.get('file_name')}': "
            f"{len(chunks)} chunks from {len(pages)} pages"
        )
        return chunks

    def chunk_transcript(
        self,
        text: str,
        file_metadata: dict,
    ) -> list[DocumentChunk]:
        """
        Create chunks from a transcript text file using recursive
        character splitting with overlap.

        Args:
            text: Full transcript text content.
            file_metadata: Base metadata dict.

        Returns:
            List of DocumentChunk objects.
        """
        if not text.strip():
            logger.warning(
                f"Empty transcript: {file_metadata.get('file_name', 'unknown')}"
            )
            return []

        chunks = []
        chunk_size = self._transcript_chunk_size
        overlap = self._transcript_chunk_overlap

        # Split into chunks with overlap
        start = 0
        text_length = len(text)

        while start < text_length:
            end = start + chunk_size

            # If not at the end of text, try to break at a sentence boundary
            if end < text_length:
                # Look for sentence-ending punctuation near the chunk boundary
                boundary = self._find_sentence_boundary(text, end, chunk_size)
                if boundary > start:
                    end = boundary

            chunk_text = text[start:end].strip()

            if chunk_text:
                # Check for deadline keywords
                contains_deadline = self._check_deadline_keywords(chunk_text)

                chunk_meta = {
                    **file_metadata,
                    "chunk_index": len(chunks),
                    "char_offset_start": start,
                    "char_offset_end": min(end, text_length),
                    "contains_deadline": contains_deadline,
                }

                chunk_id = self._generate_chunk_id(
                    file_metadata.get("file_name", "unknown"),
                    len(chunks),
                )

                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        text=chunk_text,
                        metadata=chunk_meta,
                    )
                )

            # Move start forward, accounting for overlap
            start = end - overlap
            if start <= 0 and end >= text_length:
                break
            # Prevent infinite loop
            if end >= text_length:
                break

        # Set total_chunks on all chunk metadata
        for chunk in chunks:
            chunk.metadata["total_chunks"] = len(chunks)

        logger.info(
            f"Chunked transcript '{file_metadata.get('file_name')}': "
            f"{len(chunks)} chunks from {text_length} chars"
        )
        return chunks

    def _find_sentence_boundary(
        self, text: str, position: int, chunk_size: int
    ) -> int:
        """
        Find the nearest sentence boundary near the given position.
        Looks backward from position within a reasonable range.
        """
        # Look backward up to 200 chars for a sentence-ending punctuation
        search_start = max(position - 200, 0)
        search_text = text[search_start:position]

        # Find the last sentence-ending punctuation
        for marker in [". ", ".\n", "? ", "?\n", "! ", "!\n"]:
            last_idx = search_text.rfind(marker)
            if last_idx != -1:
                return search_start + last_idx + len(marker)

        # If no sentence boundary found, try newlines
        last_newline = search_text.rfind("\n")
        if last_newline != -1:
            return search_start + last_newline + 1

        # No good boundary found, use original position
        return position

    def _check_deadline_keywords(self, text: str) -> bool:
        """Check if text contains any deadline-related keywords."""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in DEADLINE_KEYWORDS)

    def _generate_chunk_id(self, file_name: str, index: int) -> str:
        """Generate a unique, deterministic chunk ID."""
        raw = f"{file_name}::{index}"
        hash_suffix = hashlib.md5(raw.encode()).hexdigest()[:8]
        # Clean filename for use in ID
        clean_name = re.sub(r"[^a-zA-Z0-9_]", "_", file_name)
        return f"{clean_name}__{index}__{hash_suffix}"

    def build_file_metadata(
        self,
        file_name: str,
        file_type: str,
        quarter: str,
        course_id: str,
        course_name: str,
        drive_file_id: str = "",
        drive_link: str = "",
    ) -> dict:
        """
        Build the base metadata dict for a file.
        This metadata is shared across all chunks from the same file.
        """
        return {
            "quarter": quarter,
            "course_id": course_id,
            "course_name": course_name,
            "file_type": file_type,
            "file_name": file_name,
            "drive_file_id": drive_file_id,
            "drive_link": drive_link,
        }


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_text_processor: Optional[TextProcessor] = None


def get_text_processor() -> TextProcessor:
    """Get or create the singleton TextProcessor instance."""
    global _text_processor
    if _text_processor is None:
        _text_processor = TextProcessor()
    return _text_processor

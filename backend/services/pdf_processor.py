"""
PDF Processor — Extract text from PDF files.
Handles both text-based PDFs and presentation slides.
Uses PyMuPDF (fitz) for extraction.
"""

import base64
import logging
from pathlib import Path
from typing import Optional
import io

import fitz  # PyMuPDF
from openai import AsyncOpenAI

from backend.config import get_settings

logger = logging.getLogger(__name__)

# Minimum characters of extracted text below which we consider a page "empty"
# and trigger the vision fallback.
VISION_FALLBACK_THRESHOLD = 30

# Render DPI for vision fallback (higher = clearer text, more tokens)
VISION_RENDER_DPI = 150

VISION_TRANSCRIBE_PROMPT = (
    "You are transcribing a page from a UCLA course PDF (lecture slide or syllabus). "
    "Transcribe ALL visible text exactly as it appears, preserving structure where useful "
    "(headings, bullets, dates, deadlines, assignment names). Do not summarize. "
    "Do not add commentary. If the page is purely decorative or blank, respond with the "
    "single word: EMPTY"
)


class PDFPage:
    """Represents extracted content from a single PDF page."""

    def __init__(
        self,
        page_number: int,
        text: str,
        total_pages: int,
        has_images: bool = False,
        image_count: int = 0,
    ):
        self.page_number = page_number  # 1-indexed
        self.text = text
        self.total_pages = total_pages
        self.has_images = has_images
        self.image_count = image_count

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def __repr__(self) -> str:
        preview = self.text[:50].replace("\n", " ") + "..." if self.text else "(empty)"
        return f"PDFPage(page={self.page_number}/{self.total_pages}, text='{preview}')"


class PDFProcessor:
    """
    Extracts text content from PDF files page by page.

    Handles two types of PDFs:
    - Text-based PDFs: Direct text extraction
    - Presentation slides (converted to PDF): Text + image detection

    Usage:
        processor = PDFProcessor()
        pages = processor.extract_pages("path/to/file.pdf")
        pages = processor.extract_pages_from_bytes(pdf_bytes, "filename.pdf")
    """

    def extract_pages(self, file_path: str | Path) -> list[PDFPage]:
        """
        Extract text from each page of a local PDF file.

        Args:
            file_path: Path to the PDF file.

        Returns:
            List of PDFPage objects, one per page.
        """
        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"PDF file not found: {file_path}")

        logger.info(f"Processing PDF: {file_path.name}")

        try:
            doc = fitz.open(str(file_path))
            return self._process_document(doc, file_path.name)
        except Exception as e:
            logger.error(f"Failed to process PDF {file_path.name}: {e}")
            raise

    def extract_pages_from_bytes(
        self, pdf_bytes: bytes, filename: str = "document.pdf"
    ) -> list[PDFPage]:
        """
        Extract text from each page of a PDF provided as bytes.
        Used when processing files from Google Drive or uploads.

        Args:
            pdf_bytes: Raw PDF file content.
            filename: Name for logging purposes.

        Returns:
            List of PDFPage objects, one per page.
        """
        logger.info(f"Processing PDF from bytes: {filename}")

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            return self._process_document(doc, filename)
        except Exception as e:
            logger.error(f"Failed to process PDF bytes ({filename}): {e}")
            raise

    def _process_document(self, doc: fitz.Document, filename: str) -> list[PDFPage]:
        """Process a fitz Document and extract pages."""
        total_pages = len(doc)
        pages = []

        for page_idx in range(total_pages):
            page = doc[page_idx]

            # Extract text
            text = page.get_text("text")

            # Clean up extracted text
            text = self._clean_text(text)

            # Check for images
            image_list = page.get_images(full=True)
            has_images = len(image_list) > 0

            pages.append(
                PDFPage(
                    page_number=page_idx + 1,  # 1-indexed
                    text=text,
                    total_pages=total_pages,
                    has_images=has_images,
                    image_count=len(image_list),
                )
            )

        doc.close()

        # Log summary
        non_empty = sum(1 for p in pages if not p.is_empty)
        total_images = sum(p.image_count for p in pages)
        logger.info(
            f"Extracted {filename}: {total_pages} pages, "
            f"{non_empty} with text, {total_images} images detected"
        )

        return pages

    def _clean_text(self, text: str) -> str:
        """Clean extracted text: normalize whitespace, remove artifacts."""
        if not text:
            return ""

        # Replace multiple consecutive newlines with double newline
        lines = text.split("\n")
        cleaned_lines = []
        prev_empty = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if not prev_empty:
                    cleaned_lines.append("")
                prev_empty = True
            else:
                cleaned_lines.append(stripped)
                prev_empty = False

        result = "\n".join(cleaned_lines).strip()
        return result

    # ──────────────────────────────────────────────
    # Async extraction with Claude vision fallback
    # ──────────────────────────────────────────────

    async def extract_pages_from_bytes_async(
        self,
        pdf_bytes: bytes,
        filename: str = "document.pdf",
        use_vision_fallback: bool = True,
    ) -> list[PDFPage]:
        """
        Extract text from PDF bytes; for any page where PyMuPDF returns
        little-to-no text, optionally fall back to Claude vision to OCR
        the page image. This handles slides exported with vectorized fonts
        or unusual encodings that defeat normal extraction.
        """
        logger.info(f"Processing PDF (async, vision_fallback={use_vision_fallback}): {filename}")

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.error(f"Failed to open PDF bytes ({filename}): {e}")
            raise

        total_pages = len(doc)
        pages: list[PDFPage] = []
        vision_used = 0

        try:
            client: Optional[AsyncOpenAI] = None
            model: Optional[str] = None
            if use_vision_fallback:
                settings = get_settings()
                if settings.openai_api_key:
                    client = AsyncOpenAI(api_key=settings.openai_api_key)
                    model = settings.openai_chat_model
                else:
                    logger.warning(
                        f"{filename}: vision fallback requested but no OpenAI key set"
                    )

            # Pre-extract texts and images
            extracted_texts = []
            page_infos = []
            for page_idx in range(total_pages):
                page = doc[page_idx]
                text = self._clean_text(page.get_text("text"))
                image_list = page.get_images(full=True)
                extracted_texts.append(text)
                page_infos.append(image_list)

            import asyncio

            # Limit concurrency to 2 and track consecutive failures to bail early
            sem = asyncio.Semaphore(2)
            vision_failures = 0
            MAX_CONSECUTIVE_FAILURES = 5
            VISION_TIMEOUT_SECS = 25

            async def process_page(page_idx):
                nonlocal vision_failures
                text = extracted_texts[page_idx]
                image_list = page_infos[page_idx]
                vision_used_here = False

                needs_vision = client is not None and len(text) < VISION_FALLBACK_THRESHOLD
                too_many_failures = vision_failures >= MAX_CONSECUTIVE_FAILURES

                if needs_vision and not too_many_failures:
                    async with sem:
                        try:
                            page = doc[page_idx]
                            png_b64 = self._render_page_png_b64(page)
                            vision_text = await asyncio.wait_for(
                                self._vision_transcribe(client, model, png_b64),
                                timeout=VISION_TIMEOUT_SECS,
                            )
                            if vision_text and vision_text.strip().upper() != "EMPTY":
                                text = self._clean_text(vision_text)
                                vision_used_here = True
                                vision_failures = 0
                                logger.info(
                                    f"{filename} p{page_idx + 1}: vision recovered "
                                    f"{len(text)} chars"
                                )
                        except Exception as e:
                            vision_failures += 1
                            logger.warning(
                                f"{filename} p{page_idx + 1}: vision fallback failed "
                                f"(failures={vision_failures}): {e}"
                            )
                            if vision_failures >= MAX_CONSECUTIVE_FAILURES:
                                logger.warning(
                                    f"{filename}: too many vision failures, "
                                    "skipping vision for remaining pages"
                                )

                return PDFPage(
                    page_number=page_idx + 1,
                    text=text,
                    total_pages=total_pages,
                    has_images=len(image_list) > 0,
                    image_count=len(image_list),
                ), vision_used_here

            results = await asyncio.gather(*(process_page(i) for i in range(total_pages)))
            
            for page_obj, v_used in results:
                pages.append(page_obj)
                if v_used:
                    vision_used += 1
                    
        finally:
            doc.close()

        non_empty = sum(1 for p in pages if not p.is_empty)
        logger.info(
            f"Extracted {filename}: {total_pages} pages, {non_empty} with text "
            f"({vision_used} recovered via vision)"
        )
        return pages

    def _render_page_png_b64(self, page: fitz.Page) -> str:
        """Render a fitz page to a base64-encoded PNG."""
        zoom = VISION_RENDER_DPI / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        png_bytes = pix.tobytes("png")
        return base64.standard_b64encode(png_bytes).decode("ascii")

    async def _vision_transcribe(
        self,
        client: AsyncOpenAI,
        model: str,
        png_b64: str,
    ) -> str:
        """Send a single page image to OpenAI and return the transcription."""
        response = await client.chat.completions.create(
            model=model,
            max_tokens=2048,
            temperature=0.0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": VISION_TRANSCRIBE_PROMPT,
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{png_b64}"
                            },
                        },
                    ],
                }
            ],
        )
        return response.choices[0].message.content or ""

    def extract_full_text(self, file_path: str | Path) -> str:
        """
        Extract all text from a PDF as a single string.
        Useful for quick content analysis (e.g., upload classification).

        Args:
            file_path: Path to the PDF file.

        Returns:
            Full text content of the PDF.
        """
        pages = self.extract_pages(file_path)
        return "\n\n".join(p.text for p in pages if not p.is_empty)

    def extract_full_text_from_bytes(
        self, pdf_bytes: bytes, filename: str = "document.pdf"
    ) -> str:
        """Extract all text from PDF bytes as a single string."""
        pages = self.extract_pages_from_bytes(pdf_bytes, filename)
        return "\n\n".join(p.text for p in pages if not p.is_empty)


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_pdf_processor: Optional[PDFProcessor] = None


def get_pdf_processor() -> PDFProcessor:
    """Get or create the singleton PDFProcessor instance."""
    global _pdf_processor
    if _pdf_processor is None:
        _pdf_processor = PDFProcessor()
    return _pdf_processor

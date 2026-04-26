"""
PDF Processor — Extract text from PDF files.
Handles both text-based PDFs and scanned documents/slides.
Uses PyMuPDF (fitz) for extraction with Tesseract OCR fallback
for pages where text extraction yields little to no content.
"""

import logging
from pathlib import Path
from typing import Optional

import fitz  # PyMuPDF

from backend.config import get_settings

logger = logging.getLogger(__name__)


class PDFPage:
    """Represents extracted content from a single PDF page."""

    def __init__(
        self,
        page_number: int,
        text: str,
        total_pages: int,
        has_images: bool = False,
        image_count: int = 0,
        ocr_used: bool = False,
    ):
        self.page_number = page_number  # 1-indexed
        self.text = text
        self.total_pages = total_pages
        self.has_images = has_images
        self.image_count = image_count
        self.ocr_used = ocr_used

    @property
    def is_empty(self) -> bool:
        return not self.text.strip()

    def __repr__(self) -> str:
        preview = self.text[:50].replace("\n", " ") + "..." if self.text else "(empty)"
        ocr_tag = " [OCR]" if self.ocr_used else ""
        return f"PDFPage(page={self.page_number}/{self.total_pages}{ocr_tag}, text='{preview}')"


class PDFProcessor:
    """
    Extracts text content from PDF files page by page.

    Handles two types of PDFs:
    - Text-based PDFs: Direct text extraction via PyMuPDF
    - Scanned documents / slides: OCR via Tesseract (through PyMuPDF's
      built-in OCR integration) for pages with little or no extractable text

    Usage:
        processor = PDFProcessor()
        pages = processor.extract_pages("path/to/file.pdf")
        pages = processor.extract_pages_from_bytes(pdf_bytes, "filename.pdf")
        pages = await processor.extract_pages_with_ocr(pdf_bytes, "filename.pdf")
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
    # OCR-enabled extraction (replaces vision fallback)
    # ──────────────────────────────────────────────

    async def extract_pages_with_ocr(
        self,
        pdf_bytes: bytes,
        filename: str = "document.pdf",
    ) -> list[PDFPage]:
        """
        Extract text from PDF bytes; for any page where PyMuPDF returns
        little-to-no text, fall back to Tesseract OCR (via PyMuPDF's
        built-in OCR integration) to extract text from the page image.

        This handles scanned documents and slides exported as image-based
        PDFs without requiring any external API calls.

        Pages are processed sequentially to keep memory bounded on
        resource-constrained servers (e.g., Oracle Free Tier 6GB RAM).
        """
        settings = get_settings()
        ocr_threshold = settings.ocr_fallback_threshold
        ocr_dpi = settings.ocr_dpi

        logger.info(
            f"Processing PDF (OCR-enabled, threshold={ocr_threshold}, "
            f"dpi={ocr_dpi}): {filename}"
        )

        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        except Exception as e:
            logger.error(f"Failed to open PDF bytes ({filename}): {e}")
            raise

        total_pages = len(doc)
        pages: list[PDFPage] = []
        ocr_used_count = 0
        ocr_failed_count = 0

        try:
            for page_idx in range(total_pages):
                page = doc[page_idx]

                # First try: standard text extraction
                text = self._clean_text(page.get_text("text"))
                image_list = page.get_images(full=True)
                ocr_used = False

                # If text is below threshold, attempt OCR
                if len(text) < ocr_threshold:
                    try:
                        ocr_text = self._ocr_page(page, ocr_dpi)
                        if ocr_text and len(ocr_text.strip()) > len(text):
                            text = ocr_text
                            ocr_used = True
                            ocr_used_count += 1
                            logger.info(
                                f"{filename} p{page_idx + 1}: OCR recovered "
                                f"{len(text)} chars"
                            )
                    except Exception as e:
                        ocr_failed_count += 1
                        logger.warning(
                            f"{filename} p{page_idx + 1}: OCR failed: {e}"
                        )

                pages.append(
                    PDFPage(
                        page_number=page_idx + 1,
                        text=text,
                        total_pages=total_pages,
                        has_images=len(image_list) > 0,
                        image_count=len(image_list),
                        ocr_used=ocr_used,
                    )
                )

        finally:
            doc.close()

        non_empty = sum(1 for p in pages if not p.is_empty)
        logger.info(
            f"Extracted {filename}: {total_pages} pages, {non_empty} with text "
            f"({ocr_used_count} via OCR, {ocr_failed_count} OCR failures)"
        )
        return pages

    def _ocr_page(self, page: fitz.Page, dpi: int = 200) -> str:
        """
        Run Tesseract OCR on a single PDF page using PyMuPDF's built-in
        OCR integration.

        Args:
            page: A fitz.Page object.
            dpi: Resolution to render the page at before OCR.

        Returns:
            Extracted text from OCR.
        """
        tp = page.get_textpage_ocr(flags=0, language="eng", dpi=dpi)
        text = page.get_text("text", textpage=tp)
        return self._clean_text(text)

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

"""
Tests for Phase 1 foundation services.
Run with: python -m pytest tests/ -v
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add project root to sys.path for imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Set minimal env vars for testing (won't make real API calls)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("APP_PASSWORD", "testpass")


# ──────────────────────────────────────────────
# Config Tests
# ──────────────────────────────────────────────


class TestConfig:
    def test_settings_load(self):
        """Settings should load with defaults."""
        from backend.config import Settings

        settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
            chroma_persist_dir=tempfile.mkdtemp(),
            session_db_path=os.path.join(tempfile.mkdtemp(), "test.db"),
        )
        assert settings.current_quarter == "Spring2026"
        assert settings.claude_model == "claude-3-5-haiku-20241022"
        assert settings.openai_embedding_model == "text-embedding-3-small"

    def test_course_registry(self):
        """Course registry should contain Spring 2026 courses."""
        from backend.config import COURSES, COURSE_LOOKUP

        spring_courses = COURSES["Spring2026"]
        assert len(spring_courses) == 4

        # Check MSA408
        msa408 = COURSE_LOOKUP["MSA408"]
        assert msa408.name == "Operations_Analytics"
        assert msa408.display_name == "Operations Analytics"
        assert msa408.folder_name == "MSA408:Operations_Analytics"
        assert msa408.full_id == "26S-MGMTMSA-408-LEC-2"

    def test_all_courses_present(self):
        """All 4 courses should be registered."""
        from backend.config import COURSE_LOOKUP

        expected = ["MSA408", "MSA409", "MSA410", "MSA413"]
        for code in expected:
            assert code in COURSE_LOOKUP, f"Missing course: {code}"

    def test_drive_structure(self):
        """Drive structure should include all quarters and courses."""
        from backend.config import Settings

        settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
        )
        structure = settings.get_drive_structure()
        assert "Spring2026" in structure
        assert "MSA408:Operations_Analytics" in structure["Spring2026"]
        assert structure["Spring2026"]["MSA408:Operations_Analytics"] == [
            "slides",
            "transcripts",
            "homeworks",
        ]

    def test_deadline_keywords(self):
        """Deadline keywords list should be populated."""
        from backend.config import DEADLINE_KEYWORDS

        assert len(DEADLINE_KEYWORDS) > 0
        assert "deadline" in DEADLINE_KEYWORDS
        assert "due" in DEADLINE_KEYWORDS


# ──────────────────────────────────────────────
# Text Processor Tests
# ──────────────────────────────────────────────


class TestTextProcessor:
    def setup_method(self):
        """Reset singleton before each test."""
        from backend.services import text_processor

        text_processor._text_processor = None

    def test_chunk_transcript_basic(self):
        """Transcript text should be chunked correctly."""
        from backend.services.text_processor import TextProcessor

        processor = TextProcessor()
        # Create a text that's longer than chunk size
        text = "This is a test sentence. " * 200  # ~5000 chars
        metadata = {
            "quarter": "Spring2026",
            "course_id": "MSA408",
            "course_name": "Operations_Analytics",
            "file_type": "transcripts",
            "file_name": "MSA408_Lecture1_Transcript.txt",
            "drive_file_id": "test123",
            "drive_link": "https://drive.google.com/test",
        }

        chunks = processor.chunk_transcript(text, metadata)
        assert len(chunks) > 1
        # Each chunk should have metadata
        for chunk in chunks:
            assert chunk.metadata["quarter"] == "Spring2026"
            assert chunk.metadata["course_id"] == "MSA408"
            assert chunk.metadata["total_chunks"] == len(chunks)
            assert chunk.chunk_id  # ID should not be empty

    def test_chunk_transcript_empty(self):
        """Empty text should produce no chunks."""
        from backend.services.text_processor import TextProcessor

        processor = TextProcessor()
        chunks = processor.chunk_transcript("", {"file_name": "test.txt"})
        assert len(chunks) == 0

    def test_chunk_slides(self):
        """Slide pages should be chunked page by page."""
        from backend.services.text_processor import TextProcessor
        from backend.services.pdf_processor import PDFPage

        processor = TextProcessor()
        pages = [
            PDFPage(page_number=1, text="Lecture 1: Introduction\nKey concepts", total_pages=3),
            PDFPage(page_number=2, text="Assignment 1 is due on April 15, 2026", total_pages=3),
            PDFPage(page_number=3, text="Summary and next steps", total_pages=3),
        ]
        metadata = {
            "quarter": "Spring2026",
            "course_id": "MSA408",
            "course_name": "Operations_Analytics",
            "file_type": "slides",
            "file_name": "MSA408_Lecture1_Slides.pdf",
            "drive_file_id": "test123",
            "drive_link": "https://drive.google.com/test",
        }

        chunks = processor.chunk_slides(pages, metadata)
        assert len(chunks) == 3

        # Page 2 should have contains_deadline = True
        assert chunks[1].metadata["contains_deadline"] is True
        # Page 3 should not
        assert chunks[2].metadata["contains_deadline"] is False

    def test_deadline_keyword_detection(self):
        """Deadline keywords should be detected in text."""
        from backend.services.text_processor import TextProcessor

        processor = TextProcessor()
        assert processor._check_deadline_keywords("Homework 3 is due on Friday") is True
        assert processor._check_deadline_keywords("The deadline is next week") is True
        assert processor._check_deadline_keywords("Submit your assignment by 5pm") is True
        assert processor._check_deadline_keywords("Today we learn about regression") is False

    def test_chunk_id_deterministic(self):
        """Same inputs should produce same chunk IDs."""
        from backend.services.text_processor import TextProcessor

        processor = TextProcessor()
        id1 = processor._generate_chunk_id("test.pdf", 5)
        id2 = processor._generate_chunk_id("test.pdf", 5)
        id3 = processor._generate_chunk_id("test.pdf", 6)
        assert id1 == id2
        assert id1 != id3

    def test_build_file_metadata(self):
        """File metadata builder should create correct dict."""
        from backend.services.text_processor import TextProcessor

        processor = TextProcessor()
        meta = processor.build_file_metadata(
            file_name="MSA408_Lecture1_Slides.pdf",
            file_type="slides",
            quarter="Spring2026",
            course_id="MSA408",
            course_name="Operations_Analytics",
            drive_file_id="abc123",
            drive_link="https://drive.google.com/abc123",
        )
        assert meta["quarter"] == "Spring2026"
        assert meta["course_id"] == "MSA408"
        assert meta["file_type"] == "slides"
        assert meta["file_name"] == "MSA408_Lecture1_Slides.pdf"


# ──────────────────────────────────────────────
# PDF Processor Tests
# ──────────────────────────────────────────────


class TestPDFProcessor:
    def test_file_not_found(self):
        """Should raise FileNotFoundError for missing files."""
        from backend.services.pdf_processor import PDFProcessor

        processor = PDFProcessor()
        with pytest.raises(FileNotFoundError):
            processor.extract_pages("nonexistent.pdf")

    def test_clean_text(self):
        """Text cleaning should normalize whitespace."""
        from backend.services.pdf_processor import PDFProcessor

        processor = PDFProcessor()
        dirty = "  Line 1  \n\n\n\n  Line 2  \n  Line 3  \n\n\n"
        cleaned = processor._clean_text(dirty)
        assert "Line 1" in cleaned
        assert "Line 2" in cleaned
        assert "\n\n\n" not in cleaned  # Multiple newlines collapsed


# ──────────────────────────────────────────────
# ChromaDB Service Tests
# ──────────────────────────────────────────────


class TestChromaService:
    def setup_method(self):
        """Create a temp directory for ChromaDB."""
        self._temp_dir = tempfile.mkdtemp()
        # Override settings for test
        os.environ["CHROMA_PERSIST_DIR"] = self._temp_dir

        # Reset singleton
        from backend.services import chroma_service
        chroma_service._chroma_service = None

    def test_add_and_query(self):
        """Should add documents and retrieve them via query."""
        from backend.config import Settings
        from backend.services.chroma_service import ChromaService

        # Override settings
        import backend.config
        original = backend.config._settings
        backend.config._settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
            chroma_persist_dir=self._temp_dir,
        )

        try:
            chroma = ChromaService()

            # Add test documents
            ids = ["test_1", "test_2"]
            # Simple fake embeddings (just need to be same dimension)
            embeddings = [[0.1] * 10, [0.9] * 10]
            documents = [
                "Homework 3 is due on April 15, 2026 at 11:59 PM",
                "Today we covered linear regression and its applications",
            ]
            metadatas = [
                {
                    "quarter": "Spring2026",
                    "course_id": "MSA408",
                    "course_name": "Operations_Analytics",
                    "file_type": "slides",
                    "file_name": "test.pdf",
                    "contains_deadline": True,
                },
                {
                    "quarter": "Spring2026",
                    "course_id": "MSA408",
                    "course_name": "Operations_Analytics",
                    "file_type": "slides",
                    "file_name": "test.pdf",
                    "contains_deadline": False,
                },
            ]

            added = chroma.add_documents(ids, embeddings, documents, metadatas)
            assert added == 2
            assert chroma.count == 2

            # Query
            results = chroma.query(
                query_embedding=[0.1] * 10,
                top_k=2,
            )
            assert len(results) == 2
            assert results[0]["id"] in ["test_1", "test_2"]

            # Query with metadata filter
            results_filtered = chroma.query(
                query_embedding=[0.1] * 10,
                top_k=2,
                where={"course_id": "MSA408"},
            )
            assert len(results_filtered) == 2

            # Stats
            stats = chroma.get_stats()
            assert stats["total_chunks"] == 2
            assert "MSA408" in stats["courses"]

        finally:
            backend.config._settings = original

    def test_delete_by_file(self):
        """Should delete chunks by filename."""
        from backend.config import Settings
        from backend.services.chroma_service import ChromaService

        import backend.config
        original = backend.config._settings
        backend.config._settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
            chroma_persist_dir=self._temp_dir,
            chroma_collection_name="test_delete",
        )

        try:
            chroma = ChromaService()
            chroma.add_documents(
                ids=["del_1", "del_2"],
                embeddings=[[0.1] * 10, [0.2] * 10],
                documents=["doc1", "doc2"],
                metadatas=[
                    {"file_name": "file_a.pdf"},
                    {"file_name": "file_b.pdf"},
                ],
            )
            assert chroma.count == 2

            deleted = chroma.delete_by_file("file_a.pdf")
            assert deleted == 1
            assert chroma.count == 1

        finally:
            backend.config._settings = original


# ──────────────────────────────────────────────
# Session Service Tests
# ──────────────────────────────────────────────


class TestSessionService:
    def setup_method(self):
        """Create temp DB for sessions."""
        self._temp_dir = tempfile.mkdtemp()
        self._db_path = os.path.join(self._temp_dir, "test_sessions.db")
        os.environ["SESSION_DB_PATH"] = self._db_path

        from backend.services import session_service
        session_service._session_service = None

    def test_create_and_validate_session(self):
        """Should create a session and validate it."""
        from backend.config import Settings
        from backend.services.session_service import SessionService

        import backend.config
        original = backend.config._settings
        backend.config._settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
            session_db_path=self._db_path,
        )

        try:
            service = SessionService()
            session_id = service.create_session()
            assert session_id
            assert service.validate_session(session_id) is True
            assert service.validate_session("nonexistent") is False
            assert service.get_session_count() == 1
        finally:
            backend.config._settings = original

    def test_message_history(self):
        """Should store and retrieve messages."""
        from backend.config import Settings
        from backend.services.session_service import SessionService

        import backend.config
        original = backend.config._settings
        backend.config._settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
            session_db_path=self._db_path,
        )

        try:
            service = SessionService()
            session_id = service.create_session()

            service.add_message(session_id, "user", "When is HW3 due?", "deadline")
            service.add_message(
                session_id,
                "assistant",
                "HW3 is due April 15.",
                "deadline",
                source_chunks=[{"text": "source chunk"}],
            )

            history = service.get_history(session_id)
            assert len(history) == 2
            assert history[0]["role"] == "user"
            assert history[1]["role"] == "assistant"
            assert history[1]["source_chunks"] == [{"text": "source chunk"}]

            # LLM-formatted messages
            llm_messages = service.get_messages_for_llm(session_id)
            assert len(llm_messages) == 2
            assert "source_chunks" not in llm_messages[0]  # Only role + content
        finally:
            backend.config._settings = original


# ──────────────────────────────────────────────
# Schemas Tests
# ──────────────────────────────────────────────


class TestSchemas:
    def test_chat_request(self):
        """ChatRequest should validate."""
        from backend.models.schemas import ChatRequest

        req = ChatRequest(message="When is HW3 due?")
        assert req.message == "When is HW3 due?"
        assert req.session_id is None

    def test_upload_location_proposal(self):
        """UploadLocationProposal should validate."""
        from backend.models.schemas import UploadLocationProposal

        proposal = UploadLocationProposal(
            quarter="Spring2026",
            course_id="MSA408",
            course_name="Operations_Analytics",
            file_type="slides",
            suggested_filename="MSA408_Lecture6.pdf",
            full_path="Spring2026/MSA408:Operations_Analytics/slides/MSA408_Lecture6.pdf",
            reasoning="Content matches Operations Analytics lecture slides",
        )
        assert proposal.file_type == "slides"

    def test_deadline_info(self):
        """DeadlineInfo should validate."""
        from backend.models.schemas import DeadlineInfo

        info = DeadlineInfo(
            assignment_name="Homework 3",
            course_id="MSA408",
            due_date="2026-04-15",
            due_time="11:59 PM",
            confidence="high",
        )
        assert info.confidence == "high"

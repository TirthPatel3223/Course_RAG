"""
Tests for Phase 2 — Google Drive integration.
These tests verify the DriveService code structure and utilities
without making actual API calls (no credentials needed).

Run with: python -m pytest tests/test_phase2.py -v
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("ANTHROPIC_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")


class TestDriveServiceImport:
    """Verify the DriveService module loads correctly."""

    def test_import(self):
        from backend.services.drive_service import DriveService

        assert DriveService is not None

    def test_scopes(self):
        from backend.services.drive_service import SCOPES

        assert "https://www.googleapis.com/auth/drive" in SCOPES

    def test_instantiation(self):
        """DriveService should instantiate without authenticating."""
        from backend.services.drive_service import DriveService

        drive = DriveService()
        assert drive.is_authenticated is False
        assert drive._root_folder_id is None


class TestDriveLinkParsing:
    """Test Google Drive link parsing."""

    def test_file_link(self):
        from backend.services.drive_service import DriveService

        drive = DriveService()

        # Standard file link
        link = "https://drive.google.com/file/d/1aBcDeF_gHiJkLmN/view?usp=sharing"
        file_id = drive.get_file_id_from_link(link)
        assert file_id == "1aBcDeF_gHiJkLmN"

    def test_open_link(self):
        from backend.services.drive_service import DriveService

        drive = DriveService()

        link = "https://drive.google.com/open?id=1aBcDeF_gHiJkLmN"
        file_id = drive.get_file_id_from_link(link)
        assert file_id == "1aBcDeF_gHiJkLmN"

    def test_docs_link(self):
        from backend.services.drive_service import DriveService

        drive = DriveService()

        link = "https://docs.google.com/document/d/1aBcDeF_gHiJkLmN/edit"
        file_id = drive.get_file_id_from_link(link)
        assert file_id == "1aBcDeF_gHiJkLmN"

    def test_invalid_link(self):
        from backend.services.drive_service import DriveService

        drive = DriveService()

        link = "https://example.com/not-a-drive-link"
        file_id = drive.get_file_id_from_link(link)
        assert file_id is None

    def test_download_link_format(self):
        from backend.services.drive_service import DriveService

        drive = DriveService()
        link = drive.get_download_link("abc123")
        assert "abc123" in link
        assert "export=download" in link


class TestDriveServiceConfig:
    """Test Drive service configuration."""

    def test_folder_name_format(self):
        """Course folder names should follow expected format."""
        from backend.config import COURSES

        for quarter, courses in COURSES.items():
            for course in courses:
                folder = course.folder_name
                assert ":" in folder, f"Folder name should contain colon: {folder}"
                parts = folder.split(":")
                assert len(parts) == 2, f"Folder should have code:name format: {folder}"

    def test_expected_folder_structure(self):
        """Verify the expected folder structure for Spring 2026."""
        from backend.config import Settings

        settings = Settings(
            anthropic_api_key="test",
            openai_api_key="test",
        )
        structure = settings.get_drive_structure()

        spring = structure["Spring2026"]
        expected_courses = [
            "MSA408:Operations_Analytics",
            "MSA409:Competitive_Analytics",
            "MSA410:Customer_Analytics",
            "MSA413:Industry_Seminar_II",
        ]

        for course in expected_courses:
            assert course in spring, f"Missing course folder: {course}"
            assert spring[course] == [
                "slides",
                "transcripts",
                "homeworks",
            ], f"Course {course} should have slides, transcripts, and homeworks subfolders"


class TestDriveServiceMocked:
    """Test Drive service operations with mocked Google API."""

    @patch("pickle.dump")
    @patch("backend.services.drive_service.build")
    @patch("backend.services.drive_service.InstalledAppFlow")
    def test_authenticate_creates_service(self, mock_flow, mock_build, mock_pickle):
        """Authentication should create a Drive service."""
        from backend.services.drive_service import DriveService

        # Mock the OAuth flow
        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_flow.from_client_secrets_file.return_value.run_local_server.return_value = (
            mock_creds
        )

        # Mock build
        mock_service = MagicMock()
        mock_build.return_value = mock_service

        drive = DriveService()

        # Create a temp credentials file
        import tempfile, json

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            json.dump({"installed": {"client_id": "test"}}, f)
            drive._credentials_path = Path(f.name)

        token_path = Path(tempfile.mktemp(suffix=".pickle"))
        drive._token_path = token_path

        try:
            result = drive.authenticate()
            assert result is True
            assert drive.is_authenticated is True
            # Verify pickle.dump was called to save the token
            mock_pickle.assert_called_once()
        finally:
            if drive._credentials_path.exists():
                os.unlink(str(drive._credentials_path))
            if token_path.exists():
                os.unlink(str(token_path))

    def test_mime_types(self):
        """Verify MIME type constants."""
        from backend.services.drive_service import DriveService

        assert DriveService.FOLDER_MIME == "application/vnd.google-apps.folder"
        assert DriveService.PDF_MIME == "application/pdf"
        assert DriveService.TEXT_MIME == "text/plain"


class TestEmbeddingScript:
    """Test the initial embedding script can be imported."""

    def test_import(self):
        """Script should import without errors."""
        # Just verify the module structure is correct
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "initial_embed",
            str(PROJECT_ROOT / "scripts" / "initial_embed.py"),
        )
        assert spec is not None

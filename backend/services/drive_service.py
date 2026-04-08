"""
Google Drive Service — File storage operations.
Handles authentication, file listing, upload, download, and folder management
for the Course RAG document storage on Google Drive (g.ucla.edu).
"""

import io
import logging
import pickle
import mimetypes
from pathlib import Path
from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload, MediaIoBaseDownload

from backend.config import get_settings, COURSES, CourseInfo

logger = logging.getLogger(__name__)

# Full Drive access needed to read existing course files and upload new ones
SCOPES = ["https://www.googleapis.com/auth/drive"]


class DriveService:
    """
    Google Drive API wrapper for the Course RAG pipeline.

    Handles:
    - OAuth 2.0 authentication with g.ucla.edu account
    - Folder structure creation and navigation
    - File upload, download, and listing
    - Shareable link generation

    Usage:
        drive = DriveService()
        files = drive.list_files_in_folder("Spring2026/MSA408:Operations_Analytics/slides")
        content = drive.download_file(file_id)
        drive.upload_file(local_path, "Spring2026/MSA408:Operations_Analytics/slides")
    """

    # MIME types
    FOLDER_MIME = "application/vnd.google-apps.folder"
    PDF_MIME = "application/pdf"
    TEXT_MIME = "text/plain"

    def __init__(self):
        settings = get_settings()
        self._credentials_path = settings.get_credentials_path()
        self._token_path = settings.get_token_path()
        self._root_folder_name = settings.drive_root_folder
        self._service = None
        self._root_folder_id: Optional[str] = None

        # Cache for folder IDs to avoid repeated API calls
        self._folder_cache: dict[str, str] = {}

    def authenticate(self) -> bool:
        """
        Authenticate with Google Drive using OAuth 2.0.
        Uses saved token if available, otherwise initiates OAuth flow.

        Returns:
            True if authentication succeeded.
        """
        creds = None

        # Load saved token if it exists
        if self._token_path.exists():
            try:
                with open(self._token_path, "rb") as f:
                    creds = pickle.load(f)
                logger.info("Loaded saved Google credentials")
            except Exception as e:
                logger.warning(f"Failed to load saved token: {e}")

        # If no valid credentials, refresh or re-authenticate
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    logger.info("Refreshed Google credentials")
                except Exception as e:
                    logger.warning(f"Token refresh failed: {e}")
                    creds = None

            if not creds:
                if not self._credentials_path.exists():
                    raise FileNotFoundError(
                        f"Google OAuth credentials not found at: {self._credentials_path}\n"
                        "Please download your OAuth client credentials from Google Cloud Console\n"
                        "and save them to this path. Run 'python scripts/setup_drive.py' for help."
                    )

                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._credentials_path), SCOPES
                )
                creds = flow.run_local_server(port=0)
                logger.info("Completed OAuth flow — new credentials obtained")

            # Save the token for future use
            self._token_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._token_path, "wb") as f:
                pickle.dump(creds, f)
            logger.info(f"Saved credentials to {self._token_path}")

        # Build the Drive API service
        self._service = build("drive", "v3", credentials=creds)
        logger.info("Google Drive service initialized successfully")
        return True

    def _ensure_service(self):
        """Ensure the Drive service is authenticated."""
        if self._service is None:
            self.authenticate()

    # ──────────────────────────────────────────────
    # Folder Operations
    # ──────────────────────────────────────────────

    def get_or_create_root_folder(self) -> str:
        """
        Get or create the root 'Course_RAG_Data' folder on Drive.
        Returns the folder ID.
        """
        self._ensure_service()

        if self._root_folder_id:
            return self._root_folder_id

        # Search for existing root folder
        query = (
            f"name = '{self._root_folder_name}' "
            f"and mimeType = '{self.FOLDER_MIME}' "
            f"and trashed = false"
        )
        results = (
            self._service.files()
            .list(q=query, spaces="drive", fields="files(id, name)")
            .execute()
        )
        files = results.get("files", [])

        if files:
            self._root_folder_id = files[0]["id"]
            logger.info(
                f"Found root folder '{self._root_folder_name}': {self._root_folder_id}"
            )
        else:
            # Create root folder
            metadata = {
                "name": self._root_folder_name,
                "mimeType": self.FOLDER_MIME,
            }
            folder = (
                self._service.files()
                .create(body=metadata, fields="id")
                .execute()
            )
            self._root_folder_id = folder["id"]
            logger.info(
                f"Created root folder '{self._root_folder_name}': {self._root_folder_id}"
            )

        return self._root_folder_id

    def get_or_create_folder(self, path: str) -> str:
        """
        Get or create a folder at the given path relative to root.
        Creates intermediate folders as needed.

        Args:
            path: Folder path like 'Spring2026/MSA408:Operations_Analytics/slides'

        Returns:
            Google Drive folder ID.
        """
        self._ensure_service()

        # Check cache first
        if path in self._folder_cache:
            return self._folder_cache[path]

        # Navigate/create path from root
        parent_id = self.get_or_create_root_folder()
        parts = [p for p in path.split("/") if p]

        current_path = ""
        for part in parts:
            current_path = f"{current_path}/{part}" if current_path else part

            # Check cache for intermediate paths
            if current_path in self._folder_cache:
                parent_id = self._folder_cache[current_path]
                continue

            # Search for existing folder
            query = (
                f"name = '{part}' "
                f"and mimeType = '{self.FOLDER_MIME}' "
                f"and '{parent_id}' in parents "
                f"and trashed = false"
            )
            results = (
                self._service.files()
                .list(q=query, spaces="drive", fields="files(id, name)")
                .execute()
            )
            files = results.get("files", [])

            if files:
                parent_id = files[0]["id"]
            else:
                # Create folder
                metadata = {
                    "name": part,
                    "mimeType": self.FOLDER_MIME,
                    "parents": [parent_id],
                }
                folder = (
                    self._service.files()
                    .create(body=metadata, fields="id")
                    .execute()
                )
                parent_id = folder["id"]
                logger.info(f"Created folder: {current_path}")

            self._folder_cache[current_path] = parent_id

        return parent_id

    def initialize_folder_structure(self) -> dict[str, str]:
        """
        Create the full expected folder structure on Drive.
        Returns a dict mapping paths to folder IDs.

        Structure:
            Course_RAG_Data/
            ├── Spring2026/
            │   ├── MSA408:Operations_Analytics/
            │   │   ├── slides/
            │   │   └── transcripts/
            │   ├── ...
        """
        self._ensure_service()
        created = {}

        settings = get_settings()
        structure = settings.get_drive_structure()

        for quarter, courses in structure.items():
            for course_folder, subfolders in courses.items():
                for subfolder in subfolders:
                    path = f"{quarter}/{course_folder}/{subfolder}"
                    folder_id = self.get_or_create_folder(path)
                    created[path] = folder_id
                    logger.info(f"Ensured folder exists: {path}")

        logger.info(f"Folder structure initialized: {len(created)} folders")
        return created

    # ──────────────────────────────────────────────
    # File Listing
    # ──────────────────────────────────────────────

    def list_files_in_folder(
        self,
        folder_path: str,
        file_types: Optional[list[str]] = None,
    ) -> list[dict]:
        """
        List files in a folder path relative to root.

        Args:
            folder_path: Path like 'Spring2026/MSA408:Operations_Analytics/slides'
            file_types: Optional list of MIME types to filter by.

        Returns:
            List of dicts with keys: id, name, mimeType, size, modifiedTime, webViewLink
        """
        self._ensure_service()

        folder_id = self.get_or_create_folder(folder_path)

        query = f"'{folder_id}' in parents and trashed = false"
        if file_types:
            type_conditions = " or ".join(
                f"mimeType = '{t}'" for t in file_types
            )
            query += f" and ({type_conditions})"

        all_files = []
        page_token = None

        while True:
            results = (
                self._service.files()
                .list(
                    q=query,
                    spaces="drive",
                    fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, webViewLink)",
                    pageToken=page_token,
                    orderBy="name",
                )
                .execute()
            )

            all_files.extend(results.get("files", []))
            page_token = results.get("nextPageToken")
            if not page_token:
                break

        logger.debug(f"Listed {len(all_files)} files in {folder_path}")
        return all_files

    def list_all_course_files(
        self, quarter: Optional[str] = None
    ) -> list[dict]:
        """
        List all files across all courses for a quarter (or all quarters).

        Returns:
            List of dicts with additional keys: quarter, course_id, course_name, file_type
        """
        self._ensure_service()

        settings = get_settings()
        quarters_to_scan = (
            [quarter] if quarter else list(COURSES.keys())
        )

        all_files = []
        for q in quarters_to_scan:
            courses = COURSES.get(q, [])
            for course in courses:
                for file_type in ["slides", "transcripts", "homeworks"]:
                    path = f"{q}/{course.folder_name}/{file_type}"
                    try:
                        files = self.list_files_in_folder(path)
                        for f in files:
                            f["quarter"] = q
                            f["course_id"] = course.short_code
                            f["course_name"] = course.name
                            f["file_type"] = file_type
                            f["folder_path"] = path
                        all_files.extend(files)
                    except Exception as e:
                        logger.warning(f"Could not list files in {path}: {e}")

        logger.info(
            f"Found {len(all_files)} total files across "
            f"{len(quarters_to_scan)} quarter(s)"
        )
        return all_files

    # ──────────────────────────────────────────────
    # File Download
    # ──────────────────────────────────────────────

    def download_file(self, file_id: str) -> bytes:
        """
        Download a file's content by its Google Drive file ID.

        Args:
            file_id: Google Drive file ID.

        Returns:
            File content as bytes.
        """
        self._ensure_service()

        request = self._service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)

        done = False
        while not done:
            _, done = downloader.next_chunk()

        content = buffer.getvalue()
        logger.debug(f"Downloaded file {file_id}: {len(content)} bytes")
        return content

    def download_file_to_path(self, file_id: str, local_path: str | Path) -> Path:
        """Download a file and save it locally."""
        local_path = Path(local_path)
        content = self.download_file(file_id)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(content)
        logger.info(f"Downloaded file to {local_path}")
        return local_path

    # ──────────────────────────────────────────────
    # File Upload
    # ──────────────────────────────────────────────

    def upload_file(
        self,
        file_path: str | Path,
        drive_folder_path: str,
        filename: Optional[str] = None,
    ) -> dict:
        """
        Upload a local file to a specific Drive folder.

        Args:
            file_path: Local file path.
            drive_folder_path: Drive folder path relative to root
                (e.g., 'Spring2026/MSA408:Operations_Analytics/slides').
            filename: Optional override for the filename on Drive.

        Returns:
            Dict with keys: id, name, webViewLink
        """
        self._ensure_service()

        file_path = Path(file_path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {file_path}")

        folder_id = self.get_or_create_folder(drive_folder_path)
        upload_name = filename or file_path.name

        # Detect MIME type
        mime_type, _ = mimetypes.guess_type(str(file_path))
        if mime_type is None:
            mime_type = "application/octet-stream"

        metadata = {
            "name": upload_name,
            "parents": [folder_id],
        }

        media = MediaFileUpload(str(file_path), mimetype=mime_type, resumable=True)

        file = (
            self._service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
            )
            .execute()
        )

        logger.info(
            f"Uploaded '{upload_name}' to {drive_folder_path} "
            f"(ID: {file['id']})"
        )
        return file

    def upload_file_from_bytes(
        self,
        content: bytes,
        filename: str,
        drive_folder_path: str,
        mime_type: Optional[str] = None,
    ) -> dict:
        """
        Upload file content (bytes) to a specific Drive folder.
        Used for files received via web upload.

        Args:
            content: File content as bytes.
            filename: Name for the file on Drive.
            drive_folder_path: Drive folder path relative to root.
            mime_type: Optional MIME type.

        Returns:
            Dict with keys: id, name, webViewLink
        """
        self._ensure_service()

        folder_id = self.get_or_create_folder(drive_folder_path)

        if mime_type is None:
            mime_type, _ = mimetypes.guess_type(filename)
            if mime_type is None:
                mime_type = "application/octet-stream"

        metadata = {
            "name": filename,
            "parents": [folder_id],
        }

        media = MediaIoBaseUpload(
            io.BytesIO(content), mimetype=mime_type, resumable=True
        )

        file = (
            self._service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id, name, webViewLink",
            )
            .execute()
        )

        logger.info(
            f"Uploaded '{filename}' ({len(content)} bytes) to {drive_folder_path}"
        )
        return file

    # ──────────────────────────────────────────────
    # Sharing & Links
    # ──────────────────────────────────────────────

    def get_shareable_link(self, file_id: str) -> str:
        """
        Get or create a shareable link for a file.
        Makes the file viewable by anyone with the link.

        Args:
            file_id: Google Drive file ID.

        Returns:
            Shareable web view link.
        """
        self._ensure_service()

        # First try to get existing webViewLink
        file = (
            self._service.files()
            .get(fileId=file_id, fields="webViewLink")
            .execute()
        )

        link = file.get("webViewLink")
        if link:
            return link

        # If no link, create sharing permission
        try:
            self._service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
            ).execute()

            # Get the updated link
            file = (
                self._service.files()
                .get(fileId=file_id, fields="webViewLink")
                .execute()
            )
            return file.get("webViewLink", f"https://drive.google.com/file/d/{file_id}/view")
        except Exception as e:
            logger.warning(f"Could not create shareable link for {file_id}: {e}")
            return f"https://drive.google.com/file/d/{file_id}/view"

    def get_download_link(self, file_id: str) -> str:
        """Get a direct download link for a file."""
        return f"https://drive.google.com/uc?export=download&id={file_id}"

    # ──────────────────────────────────────────────
    # File Info & Search
    # ──────────────────────────────────────────────

    def get_file_info(self, file_id: str) -> dict:
        """Get metadata for a specific file."""
        self._ensure_service()

        file = (
            self._service.files()
            .get(
                fileId=file_id,
                fields="id, name, mimeType, size, modifiedTime, webViewLink, parents",
            )
            .execute()
        )
        return file

    def search_files(self, query: str, max_results: int = 20) -> list[dict]:
        """
        Search for files by name within the root folder structure.

        Args:
            query: Search query (will be matched against file names).
            max_results: Maximum number of results.

        Returns:
            List of file dicts.
        """
        self._ensure_service()

        root_id = self.get_or_create_root_folder()

        # Search query: name contains the query text, within our root (or descendants)
        search_q = (
            f"name contains '{query}' "
            f"and trashed = false "
            f"and mimeType != '{self.FOLDER_MIME}'"
        )

        results = (
            self._service.files()
            .list(
                q=search_q,
                spaces="drive",
                fields="files(id, name, mimeType, size, modifiedTime, webViewLink, parents)",
                pageSize=max_results,
            )
            .execute()
        )

        return results.get("files", [])

    def get_file_id_from_link(self, drive_link: str) -> Optional[str]:
        """
        Extract the file ID from a Google Drive sharing link.

        Supports formats:
        - https://drive.google.com/file/d/FILE_ID/view
        - https://drive.google.com/open?id=FILE_ID
        - https://docs.google.com/document/d/FILE_ID/edit
        """
        import re

        patterns = [
            r"/d/([a-zA-Z0-9_-]+)",
            r"id=([a-zA-Z0-9_-]+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, drive_link)
            if match:
                return match.group(1)

        logger.warning(f"Could not extract file ID from link: {drive_link}")
        return None

    # ──────────────────────────────────────────────
    # Utility
    # ──────────────────────────────────────────────

    def get_folder_tree(self, max_depth: int = 3) -> dict:
        """
        Get the folder tree structure under root.
        Returns a nested dict representation for display.
        """
        self._ensure_service()
        root_id = self.get_or_create_root_folder()
        return self._build_tree(root_id, self._root_folder_name, max_depth)

    def _build_tree(self, folder_id: str, name: str, depth: int) -> dict:
        """Recursively build folder tree."""
        if depth <= 0:
            return {"name": name, "id": folder_id, "type": "folder"}

        query = f"'{folder_id}' in parents and trashed = false"
        results = (
            self._service.files()
            .list(
                q=query,
                spaces="drive",
                fields="files(id, name, mimeType, size)",
                orderBy="name",
            )
            .execute()
        )

        children = []
        for item in results.get("files", []):
            if item["mimeType"] == self.FOLDER_MIME:
                children.append(
                    self._build_tree(item["id"], item["name"], depth - 1)
                )
            else:
                children.append(
                    {
                        "name": item["name"],
                        "id": item["id"],
                        "type": "file",
                        "size": item.get("size", "0"),
                    }
                )

        return {
            "name": name,
            "id": folder_id,
            "type": "folder",
            "children": children,
        }

    @property
    def is_authenticated(self) -> bool:
        """Check if the Drive service is authenticated."""
        return self._service is not None


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_drive_service: Optional[DriveService] = None


def get_drive_service() -> DriveService:
    """Get or create the singleton DriveService instance."""
    global _drive_service
    if _drive_service is None:
        _drive_service = DriveService()
    return _drive_service

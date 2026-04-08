"""
Initial Embedding Script — Process and embed all documents from Google Drive.

Scans all course folders on Drive, downloads files, extracts text,
chunks them, generates embeddings, and stores in ChromaDB.

Run: python scripts/initial_embed.py [--quarter Spring2026] [--course MSA408]
"""

import argparse
import asyncio
import logging
import sys
import time
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import get_settings, COURSES
from backend.services.drive_service import DriveService
from backend.services.pdf_processor import PDFProcessor
from backend.services.text_processor import TextProcessor
from backend.services.embedding_service import EmbeddingService
from backend.services.chroma_service import ChromaService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def embed_file(
    file_info: dict,
    drive: DriveService,
    pdf_proc: PDFProcessor,
    text_proc: TextProcessor,
    embedder: EmbeddingService,
    chroma: ChromaService,
) -> int:
    """
    Process and embed a single file.

    Returns:
        Number of chunks created.
    """
    file_name = file_info["name"]
    file_id = file_info["id"]
    file_type = file_info["file_type"]
    quarter = file_info["quarter"]
    course_id = file_info["course_id"]
    course_name = file_info["course_name"]

    logger.info(f"Processing: {file_name} ({file_type})")

    # Build base metadata
    drive_link = file_info.get("webViewLink", "")
    if not drive_link:
        drive_link = drive.get_shareable_link(file_id)

    metadata = text_proc.build_file_metadata(
        file_name=file_name,
        file_type=file_type,
        quarter=quarter,
        course_id=course_id,
        course_name=course_name,
        drive_file_id=file_id,
        drive_link=drive_link,
    )

    # Download file content
    content = drive.download_file(file_id)

    # Extract and chunk based on file type
    if file_name.lower().endswith(".pdf"):
        # PDF processing
        pages = pdf_proc.extract_pages_from_bytes(content, file_name)
        chunks = text_proc.chunk_slides(pages, metadata)
    elif file_name.lower().endswith(".txt"):
        # Transcript processing
        text = content.decode("utf-8", errors="replace")
        chunks = text_proc.chunk_transcript(text, metadata)
    else:
        logger.warning(f"Unsupported file type: {file_name}, skipping")
        return 0

    if not chunks:
        logger.warning(f"No chunks produced for {file_name}")
        return 0

    # Generate embeddings
    chunk_texts = [c.text for c in chunks]
    embeddings = await embedder.embed_batch(chunk_texts)

    # Store in ChromaDB
    chunk_ids = [c.chunk_id for c in chunks]
    chunk_metadatas = [c.metadata for c in chunks]

    chroma.add_documents(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=chunk_texts,
        metadatas=chunk_metadatas,
    )

    logger.info(f"  ✅ {file_name}: {len(chunks)} chunks embedded")
    return len(chunks)


async def run_embedding(
    quarter: str = None,
    course_id: str = None,
    clear_existing: bool = False,
):
    """Run the full embedding pipeline."""
    settings = get_settings()

    print(f"\n{'='*60}")
    print(f"  Course RAG — Document Embedding Pipeline")
    print(f"{'='*60}\n")

    # Initialize services
    print("Initializing services...")
    drive = DriveService()
    drive.authenticate()

    pdf_proc = PDFProcessor()
    text_proc = TextProcessor()
    embedder = EmbeddingService()
    chroma = ChromaService()

    # Optionally clear existing embeddings
    if clear_existing:
        if quarter:
            deleted = chroma.delete_by_quarter(quarter)
            print(f"Cleared {deleted} existing chunks for {quarter}")
        else:
            deleted = chroma.delete_all()
            print(f"Cleared all {deleted} existing chunks")

    # List all files to process
    print(f"\nScanning Google Drive for files...")
    all_files = drive.list_all_course_files(quarter=quarter)

    # Filter by course if specified
    if course_id:
        all_files = [f for f in all_files if f["course_id"] == course_id]

    if not all_files:
        print("No files found to process!")
        return

    print(f"Found {len(all_files)} files to process\n")

    # Process each file
    total_chunks = 0
    processed = 0
    failed = 0
    start_time = time.time()

    for i, file_info in enumerate(all_files, 1):
        print(f"[{i}/{len(all_files)}] {file_info['name']}")
        try:
            chunks = await embed_file(
                file_info, drive, pdf_proc, text_proc, embedder, chroma
            )
            total_chunks += chunks
            processed += 1
        except Exception as e:
            logger.error(f"  ❌ Failed to process {file_info['name']}: {e}")
            failed += 1

    elapsed = time.time() - start_time

    # Summary
    print(f"\n{'='*60}")
    print(f"  Embedding Complete!")
    print(f"{'='*60}")
    print(f"  Files processed: {processed}")
    print(f"  Files failed:    {failed}")
    print(f"  Total chunks:    {total_chunks}")
    print(f"  Time elapsed:    {elapsed:.1f}s")
    print(f"{'='*60}\n")

    # Show ChromaDB stats
    stats = chroma.get_stats()
    print(f"ChromaDB Stats:")
    print(f"  Collection:    {stats['collection_name']}")
    print(f"  Total chunks:  {stats['total_chunks']}")
    print(f"  Quarters:      {', '.join(stats['quarters'])}")
    print(f"  Courses:       {', '.join(stats['courses'])}")
    print(f"  Unique files:  {stats['unique_files']}")


def main():
    parser = argparse.ArgumentParser(
        description="Embed course documents from Google Drive into ChromaDB"
    )
    parser.add_argument(
        "--quarter",
        type=str,
        default=None,
        help="Specific quarter to process (e.g., Spring2026). Default: all quarters.",
    )
    parser.add_argument(
        "--course",
        type=str,
        default=None,
        help="Specific course to process (e.g., MSA408). Default: all courses.",
    )
    parser.add_argument(
        "--clear",
        action="store_true",
        help="Clear existing embeddings before re-embedding.",
    )
    args = parser.parse_args()

    asyncio.run(
        run_embedding(
            quarter=args.quarter,
            course_id=args.course,
            clear_existing=args.clear,
        )
    )


if __name__ == "__main__":
    main()

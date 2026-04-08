"""
ChromaDB Service — Vector store operations.
Handles storing, querying, and managing document embeddings.
"""

import logging
from datetime import datetime, timezone
from typing import Optional
from pathlib import Path

import chromadb
from chromadb.config import Settings as ChromaSettings

from backend.config import get_settings

logger = logging.getLogger(__name__)


class ChromaService:
    """
    ChromaDB wrapper for storing and querying course document embeddings.

    Manages a single collection with rich metadata for filtering by
    quarter, course, file type, etc.

    Usage:
        chroma = ChromaService()
        await chroma.add_documents(ids, embeddings, texts, metadatas)
        results = await chroma.query(embedding, top_k=5, where={"course_id": "MSA408"})
    """

    def __init__(self):
        settings = get_settings()
        persist_path = settings.get_chroma_persist_path()

        self._client = chromadb.PersistentClient(
            path=str(persist_path),
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )

        self._collection_name = settings.chroma_collection_name
        self._collection = self._client.get_or_create_collection(
            name=self._collection_name,
            metadata={"description": "UCLA Course RAG document embeddings"},
        )

        doc_count = self._collection.count()
        logger.info(
            f"ChromaDB initialized: collection='{self._collection_name}', "
            f"documents={doc_count}, path={persist_path}"
        )

    def add_documents(
        self,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> int:
        """
        Add documents with embeddings and metadata to the collection.

        Args:
            ids: Unique identifiers for each document chunk.
            embeddings: Pre-computed embedding vectors.
            documents: The text content of each chunk.
            metadatas: Metadata dicts for each chunk.

        Returns:
            Number of documents added.
        """
        if not ids:
            logger.warning("No documents to add")
            return 0

        # Add embedded_at timestamp to all metadatas
        now = datetime.now(timezone.utc).isoformat()
        for meta in metadatas:
            meta["embedded_at"] = now

        # ChromaDB has a batch limit; process in chunks of 500
        batch_size = 500
        total_added = 0

        for i in range(0, len(ids), batch_size):
            batch_ids = ids[i : i + batch_size]
            batch_embeddings = embeddings[i : i + batch_size]
            batch_documents = documents[i : i + batch_size]
            batch_metadatas = metadatas[i : i + batch_size]

            self._collection.upsert(
                ids=batch_ids,
                embeddings=batch_embeddings,
                documents=batch_documents,
                metadatas=batch_metadatas,
            )
            total_added += len(batch_ids)
            logger.info(f"Added batch: {total_added}/{len(ids)} documents")

        logger.info(f"Total documents in collection: {self._collection.count()}")
        return total_added

    def query(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: Optional[dict] = None,
        where_document: Optional[dict] = None,
    ) -> list[dict]:
        """
        Query the collection for similar documents.

        Args:
            query_embedding: The query embedding vector.
            top_k: Number of results to return.
            where: Metadata filter (e.g., {"course_id": "MSA408"}).
            where_document: Document content filter.

        Returns:
            List of result dicts with keys: id, document, metadata, distance
        """
        kwargs = {
            "query_embeddings": [query_embedding],
            "n_results": min(top_k, self._collection.count() or 1),
            "include": ["documents", "metadatas", "distances"],
        }
        if where:
            kwargs["where"] = where
        if where_document:
            kwargs["where_document"] = where_document

        try:
            results = self._collection.query(**kwargs)
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []

        # Flatten results into a list of dicts
        documents = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]
        ids = results.get("ids", [[]])[0]

        output = []
        for idx in range(len(ids)):
            output.append(
                {
                    "id": ids[idx],
                    "document": documents[idx] if idx < len(documents) else "",
                    "metadata": metadatas[idx] if idx < len(metadatas) else {},
                    "distance": distances[idx] if idx < len(distances) else 1.0,
                }
            )

        logger.debug(f"Query returned {len(output)} results")
        return output

    def query_with_deadline_boost(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        where: Optional[dict] = None,
    ) -> list[dict]:
        """
        Query with priority given to chunks tagged as containing deadlines.
        Fetches both deadline-tagged and regular results, then merges.
        """
        # First, try to get deadline-tagged chunks
        deadline_where = {"contains_deadline": True}
        if where:
            deadline_where = {"$and": [where, {"contains_deadline": True}]}

        deadline_results = self.query(
            query_embedding=query_embedding,
            top_k=top_k,
            where=deadline_where,
        )

        # Also get general results
        general_results = self.query(
            query_embedding=query_embedding,
            top_k=top_k,
            where=where,
        )

        # Merge: deadline results first, then general (deduplicated)
        seen_ids = set()
        merged = []
        for result in deadline_results + general_results:
            if result["id"] not in seen_ids:
                seen_ids.add(result["id"])
                merged.append(result)
                if len(merged) >= top_k:
                    break

        return merged

    def delete_by_file(self, file_name: str) -> int:
        """Delete all chunks for a specific file. Returns count deleted."""
        # Get all IDs for this file
        results = self._collection.get(
            where={"file_name": file_name},
            include=[],
        )
        ids_to_delete = results.get("ids", [])

        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
            logger.info(f"Deleted {len(ids_to_delete)} chunks for file: {file_name}")

        return len(ids_to_delete)

    def delete_by_quarter(self, quarter: str) -> int:
        """Delete all chunks for a specific quarter. Returns count deleted."""
        results = self._collection.get(
            where={"quarter": quarter},
            include=[],
        )
        ids_to_delete = results.get("ids", [])

        if ids_to_delete:
            self._collection.delete(ids=ids_to_delete)
            logger.info(
                f"Deleted {len(ids_to_delete)} chunks for quarter: {quarter}"
            )

        return len(ids_to_delete)

    def delete_all(self) -> int:
        """Delete all documents. Used for full re-embedding."""
        count = self._collection.count()
        if count > 0:
            # Reset collection
            self._client.delete_collection(self._collection_name)
            self._collection = self._client.get_or_create_collection(
                name=self._collection_name,
                metadata={"description": "UCLA Course RAG document embeddings"},
            )
            logger.info(f"Deleted all {count} documents from collection")
        return count

    def get_stats(self) -> dict:
        """Get collection statistics."""
        count = self._collection.count()

        # Get unique values for key metadata fields
        all_meta = self._collection.get(include=["metadatas"])
        metadatas = all_meta.get("metadatas", [])

        quarters = set()
        courses = set()
        file_types = set()
        files = set()

        for meta in metadatas:
            if meta.get("quarter"):
                quarters.add(meta["quarter"])
            if meta.get("course_id"):
                courses.add(meta["course_id"])
            if meta.get("file_type"):
                file_types.add(meta["file_type"])
            if meta.get("file_name"):
                files.add(meta["file_name"])

        return {
            "total_chunks": count,
            "quarters": sorted(quarters),
            "courses": sorted(courses),
            "file_types": sorted(file_types),
            "unique_files": len(files),
            "collection_name": self._collection_name,
        }

    @property
    def count(self) -> int:
        """Total number of documents in the collection."""
        return self._collection.count()


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_chroma_service: Optional[ChromaService] = None


def get_chroma_service() -> ChromaService:
    """Get or create the singleton ChromaService instance."""
    global _chroma_service
    if _chroma_service is None:
        _chroma_service = ChromaService()
    return _chroma_service

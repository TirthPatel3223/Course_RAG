"""
Embedding Service — OpenAI text-embedding-3-small.
Handles generating embeddings for document chunks and queries.
"""

import logging
from typing import Optional

from openai import AsyncOpenAI

from backend.config import get_settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """
    Generates embeddings using OpenAI's text-embedding-3-small model.

    Usage:
        embedder = EmbeddingService()
        vector = await embedder.embed_text("Some text")
        vectors = await embedder.embed_batch(["Text 1", "Text 2", ...])
    """

    # OpenAI recommends max 2048 items per batch request
    MAX_BATCH_SIZE = 2048

    def __init__(self):
        settings = get_settings()
        if not settings.openai_api_key:
            raise RuntimeError(
                "OpenAI API key is required for embeddings. Set OPENAI_API_KEY in .env"
            )
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_embedding_model
        self._dimensions = settings.embedding_dimensions
        logger.info(
            f"Embedding service initialized: model={self._model}, dims={self._dimensions}"
        )

    async def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text string.

        Args:
            text: The text to embed.

        Returns:
            List of floats representing the embedding vector.
        """
        if not text.strip():
            logger.warning("Attempted to embed empty text, returning zero vector")
            return [0.0] * self._dimensions

        response = await self._client.embeddings.create(
            model=self._model,
            input=text,
            dimensions=self._dimensions,
        )

        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for a batch of texts.
        Automatically handles batching for large inputs.

        Args:
            texts: List of text strings to embed.

        Returns:
            List of embedding vectors (same order as input).
        """
        if not texts:
            return []

        all_embeddings = []

        # Process in batches of MAX_BATCH_SIZE
        for i in range(0, len(texts), self.MAX_BATCH_SIZE):
            batch = texts[i : i + self.MAX_BATCH_SIZE]

            # Replace empty strings with a placeholder to avoid API errors
            processed_batch = [t if t.strip() else " " for t in batch]

            logger.info(
                f"Embedding batch {i // self.MAX_BATCH_SIZE + 1}: "
                f"{len(processed_batch)} texts"
            )

            response = await self._client.embeddings.create(
                model=self._model,
                input=processed_batch,
                dimensions=self._dimensions,
            )

            # Sort by index to maintain order (API may return out of order)
            sorted_data = sorted(response.data, key=lambda x: x.index)
            batch_embeddings = [item.embedding for item in sorted_data]
            all_embeddings.extend(batch_embeddings)

        logger.info(f"Generated {len(all_embeddings)} embeddings total")
        return all_embeddings

    async def embed_query(self, query: str) -> list[float]:
        """
        Generate embedding for a search query.
        Alias for embed_text — in case we want different handling later.
        """
        return await self.embed_text(query)

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def dimensions(self) -> int:
        return self._dimensions


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_embedding_service: Optional[EmbeddingService] = None


def get_embedding_service() -> EmbeddingService:
    """Get or create the singleton EmbeddingService instance."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service

from __future__ import annotations

import asyncio
from functools import lru_cache

from sentence_transformers import SentenceTransformer

from agent.core.telemetry import get_logger

logger = get_logger(__name__)

_MODEL_NAME = "all-MiniLM-L6-v2"
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _load_model() -> SentenceTransformer:
    logger.info("loading_embedding_model", model=_MODEL_NAME)
    return SentenceTransformer(_MODEL_NAME)


class Embedder:
    """Wraps sentence-transformers to produce 384-dim embeddings asynchronously."""

    @property
    def dim(self) -> int:
        return _EMBEDDING_DIM

    async def embed(self, text: str) -> list[float]:
        model = _load_model()
        vector = await asyncio.to_thread(model.encode, text, normalize_embeddings=True)
        return vector.tolist()  # type: ignore[no-any-return]

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = _load_model()
        vectors = await asyncio.to_thread(model.encode, texts, normalize_embeddings=True)
        return vectors.tolist()  # type: ignore[no-any-return]

from __future__ import annotations

import asyncio
from functools import lru_cache

from fastembed import TextEmbedding

from agent.core.telemetry import get_logger

logger = get_logger(__name__)

_MODEL_NAME = "BAAI/bge-small-en-v1.5"  # all-MiniLM-L6-v2 equivalent, 384 dims
_EMBEDDING_DIM = 384


@lru_cache(maxsize=1)
def _load_model() -> TextEmbedding:
    logger.info("loading_embedding_model", model=_MODEL_NAME)
    return TextEmbedding(_MODEL_NAME)


class Embedder:
    """Wraps fastembed to produce 384-dim embeddings asynchronously.

    fastembed uses ONNX runtime — no PyTorch/CUDA required, ~100 MB in Docker.
    """

    @property
    def dim(self) -> int:
        return _EMBEDDING_DIM

    async def embed(self, text: str) -> list[float]:
        model = _load_model()
        vectors = await asyncio.to_thread(
            lambda: list(model.embed([text]))
        )
        return vectors[0].tolist()

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        model = _load_model()
        vectors = await asyncio.to_thread(
            lambda: list(model.embed(texts))
        )
        return [v.tolist() for v in vectors]

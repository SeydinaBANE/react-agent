from __future__ import annotations

from uuid import uuid4

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    PointStruct,
    ScoredPoint,
    VectorParams,
)

from agent.core.exceptions import MemoryError
from agent.core.telemetry import MEMORY_OPS, get_logger
from agent.memory.embedder import Embedder

logger = get_logger(__name__)


class EpisodicMemory:
    """Persists observations as embeddings in Qdrant for long-term recall."""

    def __init__(
        self,
        client: AsyncQdrantClient,
        embedder: Embedder,
        collection_name: str = "agent_memory",
    ) -> None:
        self._client = client
        self._embedder = embedder
        self._collection = collection_name

    async def ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not exist."""
        existing = await self._client.get_collections()
        names = {c.name for c in existing.collections}
        if self._collection not in names:
            await self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=self._embedder.dim,
                    distance=Distance.COSINE,
                ),
            )
            logger.info("episodic_collection_created", collection=self._collection)

    async def store(self, observation: str, metadata: dict[str, str] | None = None) -> str:
        """Embed and store an observation. Returns the point ID."""
        try:
            vector = await self._embedder.embed(observation)
            point_id = str(uuid4())
            payload = {"text": observation, **(metadata or {})}
            await self._client.upsert(
                collection_name=self._collection,
                points=[PointStruct(id=point_id, vector=vector, payload=payload)],
            )
        except Exception as exc:
            raise MemoryError(f"Failed to store observation: {exc}") from exc

        MEMORY_OPS.labels(operation="store").inc()
        return point_id

    async def search(
        self,
        query: str,
        top_k: int = 5,
        score_threshold: float = 0.5,
    ) -> list[str]:
        """Return top-k most similar observations as plain text."""
        try:
            vector = await self._embedder.embed(query)
            results: list[ScoredPoint] = await self._client.search(
                collection_name=self._collection,
                query_vector=vector,
                limit=top_k,
                score_threshold=score_threshold,
                with_payload=True,
            )
        except Exception as exc:
            raise MemoryError(f"Search failed: {exc}") from exc

        MEMORY_OPS.labels(operation="search").inc()
        observations = []
        for point in results:
            if point.payload:
                observations.append(str(point.payload.get("text", "")))
        return observations

    async def delete(self, point_id: str) -> None:
        """Remove a specific memory point."""
        try:
            await self._client.delete(
                collection_name=self._collection,
                points_selector=[point_id],
            )
        except Exception as exc:
            raise MemoryError(f"Delete failed: {exc}") from exc
        MEMORY_OPS.labels(operation="delete").inc()

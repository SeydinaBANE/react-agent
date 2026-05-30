"""Integration tests for episodic memory with a real Qdrant instance.

Requires Docker. The Qdrant container is started automatically by Testcontainers.
Run with: pytest tests/integration/ -v
"""
from __future__ import annotations

import pytest

pytest.importorskip("testcontainers", reason="testcontainers not installed")

from testcontainers.qdrant import QdrantContainer  # type: ignore[import-untyped]


@pytest.fixture(scope="module")
def qdrant_url() -> str:
    with QdrantContainer() as qdrant:
        yield qdrant.get_client()._client._rest_uri  # type: ignore[union-attr]


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_and_search(qdrant_url: str) -> None:
    from qdrant_client import AsyncQdrantClient

    from agent.memory.embedder import Embedder
    from agent.memory.episodic import EpisodicMemory

    host, port_str = qdrant_url.replace("http://", "").split(":")
    client = AsyncQdrantClient(host=host, port=int(port_str))
    embedder = Embedder()
    memory = EpisodicMemory(client, embedder, collection_name="test_collection")

    await memory.ensure_collection()

    # Store several observations
    await memory.store("RAG systems improve LLM accuracy by grounding responses in facts.")
    await memory.store("Python is a popular programming language for data science.")
    await memory.store("Qdrant is a vector database optimized for similarity search.")

    # Search for a relevant query
    results = await memory.search("vector similarity search database", top_k=2)

    assert len(results) >= 1
    assert any("Qdrant" in r or "vector" in r.lower() for r in results)

    await client.close()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_store_then_delete(qdrant_url: str) -> None:
    from qdrant_client import AsyncQdrantClient

    from agent.memory.embedder import Embedder
    from agent.memory.episodic import EpisodicMemory

    host, port_str = qdrant_url.replace("http://", "").split(":")
    client = AsyncQdrantClient(host=host, port=int(port_str))
    embedder = Embedder()
    memory = EpisodicMemory(client, embedder, collection_name="test_delete_col")

    await memory.ensure_collection()
    point_id = await memory.store("Temporary observation to delete.")

    # Delete it — should not raise
    await memory.delete(point_id)
    await client.close()

from __future__ import annotations

from typing import TYPE_CHECKING

from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from agent.rag.indexer import COLLECTION

if TYPE_CHECKING:
    from agent.ai.llm_client import LLMClient


class RAGRetriever:
    """Retrieves relevant context chunks for a given doc_group.

    Uses vector search (Qdrant) when available; falls back to keyword overlap
    scoring against the in-memory keyword index, which is always present.
    """

    def __init__(
        self,
        keyword_index: dict[str, list[str]],
        qdrant: QdrantClient | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._keyword_index = keyword_index
        self._qdrant = qdrant
        self._llm = llm_client

    def query(self, text: str, doc_group: str, top_k: int = 4) -> list[str]:
        """Return up to *top_k* relevant chunks scoped to *doc_group*."""
        if self._qdrant and self._llm:
            vectors = self._llm.embed([text])
            if vectors:
                results = self._qdrant.search(
                    collection_name=COLLECTION,
                    query_vector=vectors[0],
                    query_filter=Filter(
                        must=[FieldCondition(key="doc_group", match=MatchValue(value=doc_group))]
                    ),
                    limit=top_k,
                )
                hits = [r.payload.get("text", "") for r in results]
                if hits:
                    return hits

        return self._keyword_search(text, doc_group, top_k)

    def _keyword_search(self, text: str, doc_group: str, top_k: int) -> list[str]:
        candidates = self._keyword_index.get(doc_group, [])
        if not candidates:
            return []
        query_words = set(text.lower().split())
        scored = sorted(
            ((len(query_words & set(c.lower().split())), c) for c in candidates),
            reverse=True,
        )
        return [c for score, c in scored[:top_k] if score > 0]

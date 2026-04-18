from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.rag.retriever import RAGRetriever


class BaseLLMClient(ABC):
    """Common interface for all LLM client implementations."""

    @property
    @abstractmethod
    def provider(self) -> str: ...

    @property
    @abstractmethod
    def model(self) -> str: ...

    @property
    @abstractmethod
    def embedding_model(self) -> str | None: ...

    @property
    def supports_rag(self) -> bool:
        """Whether this client uses RAG retrieval during generation."""
        return True

    @abstractmethod
    def set_retriever(self, retriever: RAGRetriever | None) -> None: ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]] | None: ...

    @abstractmethod
    def section_purpose(self, name: str, content: str, doc_group: str = "") -> str: ...

    @abstractmethod
    def section_flow(self, name: str, content: str, doc_group: str = "") -> str: ...

    @abstractmethod
    def section_business_goal(self, name: str, content: str, doc_group: str = "") -> str: ...

    @abstractmethod
    def section_data_quality(self, name: str, content: str, doc_group: str = "") -> str: ...

    @abstractmethod
    def section_column_lineage(self, name: str, content: str, doc_group: str = "") -> str: ...

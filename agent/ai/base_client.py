from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import agent.prompts as prompts

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

    # ------------------------------------------------------------------
    # LLM call primitives — implemented by each provider
    # ------------------------------------------------------------------

    @abstractmethod
    def _call(self, user_message: str, max_tokens: int = 1024) -> str: ...

    @abstractmethod
    def _call_flow(self, user_message: str) -> str: ...

    @abstractmethod
    def _call_lineage(self, user_message: str) -> str: ...

    # ------------------------------------------------------------------
    # RAG context hook — override in providers that support retrieval
    # ------------------------------------------------------------------

    def _get_rag_context(self, query: str, doc_group: str) -> str:
        return ""

    # ------------------------------------------------------------------
    # Document section methods — shared across all providers
    # ------------------------------------------------------------------

    def section_purpose(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"purpose goal {name}", doc_group)
        parts = []
        for template in prompts.get_sub_prompts("purpose"):
            prompt = prompts.render(template, name=name, content=content[:2500], rag_context=bg)
            parts.append(self._call(prompt, max_tokens=300))
        return "\n\n".join(parts)

    def section_flow(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"dependencies connections sources outputs {name}", doc_group)
        parts = []
        for template in prompts.get_sub_prompts("flow"):
            prompt = prompts.render(template, name=name, content=content[:2500], rag_context=bg)
            if "```mermaid" in template:
                parts.append(self._call_flow(prompt))
            else:
                parts.append(self._call(prompt, max_tokens=600))
        return "\n\n".join(parts)

    def section_business_goal(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"business outcome value {name}", doc_group)
        parts = []
        for template in prompts.get_sub_prompts("business_goal"):
            prompt = prompts.render(template, name=name, content=content[:2500], rag_context=bg)
            parts.append(self._call(prompt, max_tokens=300))
        return "\n\n".join(parts)

    def section_data_quality(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"validation error handling alerts quality {name}", doc_group)
        parts = []
        for template in prompts.get_sub_prompts("data_quality"):
            prompt = prompts.render(template, name=name, content=content[:3000], rag_context=bg)
            parts.append(self._call(prompt, max_tokens=350))
        return "\n\n".join(parts)

    def section_column_lineage(self, name: str, content: str, doc_group: str = "") -> str:
        parts = []
        for template in prompts.get_sub_prompts("column_lineage"):
            prompt = prompts.render(template, name=name, content=content[:6000], rag_context="")
            parts.append(self._call_lineage(prompt))
        return "\n\n".join(parts)

"""
Multi-provider LLM client for generating business-friendly documentation.

Supported providers — set LLM_PROVIDER in .env:
  anthropic  Claude models. Prompt caching applied to reduce cost on batch runs.
  openai     OpenAI GPT models. gpt-4o-mini is the cheapest capable option.
  ollama     Local models via Ollama (free, no API key, must be running locally).
  local      Claude CLI invoked via subprocess (no API key, no embeddings).
             Use create_client() from agent.ai.client_factory instead of
             instantiating LLMClient directly when LLM_PROVIDER=local.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import agent.prompts as prompts
from agent.ai.base_client import BaseLLMClient
from agent.ai.utils import (
    _clean_flow_output,
    _clean_lineage_output,
    _clean_output,
    _summarise_props,
    build_system_prompt,
)
from agent.config import EMBEDDING_MODEL, LLM_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL

if TYPE_CHECKING:
    from agent.rag.retriever import RAGRetriever

# Backward-compat alias used by tests
SYSTEM_PROMPT = prompts.DEFAULT_PROMPTS["system_prompt"]

# ---------------------------------------------------------------------------
# Default models per provider
# ---------------------------------------------------------------------------

DEFAULT_MODELS = {
    "anthropic": "claude-sonnet-4-6",
    "openai":    "gpt-4o-mini",
    "ollama":    "llama3.2",
}

DEFAULT_EMBEDDING_MODELS = {
    "openai": "text-embedding-3-small",
    "ollama": "nomic-embed-text",
}


class LLMClient(BaseLLMClient):
    def __init__(self) -> None:
        self._retriever: RAGRetriever | None = None
        self._provider = LLM_PROVIDER.lower()
        self._system_prompt = build_system_prompt()

        if self._provider not in DEFAULT_MODELS:
            raise ValueError(
                f"Unknown LLM_PROVIDER '{self._provider}'. "
                f"Choose one of: {', '.join(DEFAULT_MODELS)} (or 'local' for the Claude CLI client)"
            )

        self._model = LLM_MODEL or DEFAULT_MODELS[self._provider]
        self._setup_client()

    def _setup_client(self) -> None:
        if self._provider == "anthropic":
            import anthropic as _anthropic
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "ANTHROPIC_API_KEY is not set. "
                    "Add it to your .env file or as a system environment variable."
                )
            self._client = _anthropic.Anthropic(api_key=api_key)

        elif self._provider == "openai":
            from openai import OpenAI
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                raise ValueError(
                    "OPENAI_API_KEY is not set. "
                    "Add it to your .env file or as a system environment variable."
                )
            self._client = OpenAI(api_key=api_key)

        elif self._provider == "ollama":
            from openai import OpenAI
            self._client = OpenAI(
                base_url=f"{OLLAMA_BASE_URL}/v1",
                api_key="ollama",  # required by the SDK but unused by Ollama
            )

    def set_retriever(self, retriever: RAGRetriever | None) -> None:
        self._retriever = retriever

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    @property
    def embedding_model(self) -> str | None:
        if self._provider == "anthropic":
            return None
        return EMBEDDING_MODEL or DEFAULT_EMBEDDING_MODELS.get(self._provider)

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        """Return embeddings for *texts* using the provider's API.

        Returns None when the provider (Anthropic) has no embeddings endpoint.
        """
        if self._provider == "anthropic":
            return None
        try:
            response = self._client.embeddings.create(
                model=self.embedding_model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # LLM call primitives
    # ------------------------------------------------------------------

    def _call(self, user_message: str, max_tokens: int = 1024) -> str:
        if self._provider == "anthropic":
            raw = self._call_anthropic(user_message, max_tokens)
        else:
            raw = self._call_openai_compatible(user_message, max_tokens)
        return _clean_output(raw)

    def _call_flow(self, user_message: str) -> str:
        """Like _call but preserves the mermaid diagram block in the output."""
        if self._provider == "anthropic":
            raw = self._call_anthropic(user_message, max_tokens=900)
        else:
            raw = self._call_openai_compatible(user_message, max_tokens=900)
        return _clean_flow_output(raw)

    def _call_lineage(self, user_message: str) -> str:
        """Like _call but uses the lineage system prompt and preserves table output."""
        lineage_sys = prompts.get("lineage_system_prompt")
        if self._provider == "anthropic":
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1800,
                system=[{"type": "text", "text": lineage_sys, "cache_control": {"type": "ephemeral"}}],
                messages=[{"role": "user", "content": user_message}],
            )
            raw = response.content[0].text.strip()
        else:
            response = self._client.chat.completions.create(
                model=self._model,
                max_tokens=1800,
                messages=[
                    {"role": "system", "content": lineage_sys},
                    {"role": "user", "content": user_message},
                ],
            )
            raw = response.choices[0].message.content.strip()
        return _clean_lineage_output(raw)

    def _call_anthropic(self, user_message: str, max_tokens: int) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=[
                {
                    "type": "text",
                    "text": self._system_prompt,
                    "cache_control": {"type": "ephemeral"},  # prompt caching
                }
            ],
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text.strip()

    def _call_openai_compatible(self, user_message: str, max_tokens: int) -> str:
        response = self._client.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content.strip()

    # ------------------------------------------------------------------
    # RAG context
    # ------------------------------------------------------------------

    def _get_rag_context(self, query: str, doc_group: str) -> str:
        if not self._retriever or not doc_group:
            return ""
        chunks = self._retriever.query(query, doc_group, top_k=3)
        if not chunks:
            return ""
        clean_lines: list[str] = []
        skip_prefixes = ("return", "write", "document", "describe", "do not", "note:", "%%")
        for chunk in chunks:
            for line in chunk.splitlines():
                stripped = line.strip()
                if stripped and not stripped.lower().startswith(skip_prefixes) and len(stripped) > 10:
                    clean_lines.append(stripped)
        if not clean_lines:
            return ""
        joined = "\n".join(f"- {l}" for l in clean_lines[:12])
        return f"Relevant background about this process:\n{joined}\n\n"

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

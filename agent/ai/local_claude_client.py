"""
Local Claude client — invokes the Claude CLI via subprocess.

No API key or embedding service required. Set LLM_PROVIDER=local in .env.
RAG is skipped; the full content summary is passed directly to Claude.
"""

from __future__ import annotations

import subprocess

import agent.prompts as prompts
from agent.ai.base_client import BaseLLMClient
from agent.ai.utils import _clean_flow_output, _clean_lineage_output, _clean_output, build_system_prompt


class LocalClaudeClient(BaseLLMClient):
    """Calls `claude -p <prompt>` in a subprocess — no credentials needed."""

    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout
        self._system_prompt = build_system_prompt()

    @property
    def provider(self) -> str:
        return "local"

    @property
    def model(self) -> str:
        return "claude (local CLI)"

    @property
    def embedding_model(self) -> str | None:
        return None

    @property
    def supports_rag(self) -> bool:
        return False

    def set_retriever(self, retriever) -> None:
        pass

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None

    # ------------------------------------------------------------------
    # LLM call primitives
    # ------------------------------------------------------------------

    def _call(self, user_message: str, max_tokens: int = 1024) -> str:
        full_prompt = f"{self._system_prompt}\n\n{user_message}"
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI exited with code {result.returncode}: {result.stderr.strip()}")
        return _clean_output(result.stdout.strip())

    def _call_flow(self, user_message: str) -> str:
        """Like _call but preserves the mermaid diagram block in the output."""
        full_prompt = f"{self._system_prompt}\n\n{user_message}"
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI exited with code {result.returncode}: {result.stderr.strip()}")
        return _clean_flow_output(result.stdout.strip())

    def _call_lineage(self, user_message: str) -> str:
        """Uses the lineage system prompt and preserves table output."""
        full_prompt = f"{prompts.get('lineage_system_prompt')}\n\n{user_message}"
        result = subprocess.run(
            ["claude", "-p", full_prompt],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        if result.returncode != 0:
            raise RuntimeError(f"claude CLI exited with code {result.returncode}: {result.stderr.strip()}")
        return _clean_lineage_output(result.stdout.strip())

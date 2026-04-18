"""
Local Claude client — invokes the Claude CLI via subprocess.

No API key or embedding service required. Set LLM_PROVIDER=local in .env.
RAG is skipped; the full content summary is passed directly to Claude.
"""

from __future__ import annotations

import subprocess

import agent.prompts as prompts
from agent.ai.base_client import BaseLLMClient
from agent.ai.llm_client import _clean_flow_output, _clean_lineage_output, _clean_output, build_system_prompt


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
    # Internal
    # ------------------------------------------------------------------

    def _call(self, user_message: str) -> str:
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

    # ------------------------------------------------------------------
    # Section methods — same prompts as LLMClient, no RAG context
    # ------------------------------------------------------------------

    def section_purpose(self, name: str, content: str, doc_group: str = "") -> str:
        parts = []
        for template in prompts.get_sub_prompts("purpose"):
            parts.append(self._call(prompts.render(template, name=name, content=content[:2500], rag_context="")))
        return "\n\n".join(parts)

    def section_flow(self, name: str, content: str, doc_group: str = "") -> str:
        parts = []
        for template in prompts.get_sub_prompts("flow"):
            prompt = prompts.render(template, name=name, content=content[:2500], rag_context="")
            if "```mermaid" in template:
                parts.append(self._call_flow(prompt))
            else:
                parts.append(self._call(prompt))
        return "\n\n".join(parts)

    def section_business_goal(self, name: str, content: str, doc_group: str = "") -> str:
        parts = []
        for template in prompts.get_sub_prompts("business_goal"):
            parts.append(self._call(prompts.render(template, name=name, content=content[:2500], rag_context="")))
        return "\n\n".join(parts)

    def section_data_quality(self, name: str, content: str, doc_group: str = "") -> str:
        parts = []
        for template in prompts.get_sub_prompts("data_quality"):
            parts.append(self._call(prompts.render(template, name=name, content=content[:3000], rag_context="")))
        return "\n\n".join(parts)

    def section_column_lineage(self, name: str, content: str, doc_group: str = "") -> str:
        parts = []
        for template in prompts.get_sub_prompts("column_lineage"):
            parts.append(self._call_lineage(prompts.render(template, name=name, content=content[:6000], rag_context="")))
        return "\n\n".join(parts)

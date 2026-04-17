"""
Local Claude client — invokes the Claude CLI via subprocess.

No API key or embedding service required. Set LLM_PROVIDER=local in .env.
RAG is skipped; the full content summary is passed directly to Claude.
"""

from __future__ import annotations

import subprocess

from agent.ai.base_client import BaseLLMClient
from agent.ai.llm_client import _clean_flow_output, _clean_output, build_system_prompt


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

    # ------------------------------------------------------------------
    # Section methods — same prompts as LLMClient, no RAG context
    # ------------------------------------------------------------------

    def section_purpose(self, name: str, content: str, doc_group: str = "") -> str:
        return self._call(
            f'Explain in plain English why "{name}" exists.\n\n'
            f"What business problem does it solve? What would be missing if it did not run?\n\n"
            f"Information:\n{content[:2500]}"
        )

    def section_what_it_does(self, name: str, content: str, doc_group: str = "") -> str:
        return self._call(
            f'Describe in plain English what "{name}" does from start to finish.\n\n'
            f"Explain where the data comes from, what happens to it, and what the output is. "
            f"Focus on the business activity, not the technology.\n\n"
            f"Information:\n{content[:3000]}"
        )

    def section_flow(self, name: str, content: str, doc_group: str = "") -> str:
        return self._call_flow(
            f'Describe the data flow for "{name}": where data comes from, what this process does '
            f"to it, and where the output goes.\n\n"
            f"Write at most two short paragraphs in plain business language.\n\n"
            f"Then produce a Mermaid diagram. Follow this format exactly — no extra text after the diagram:\n\n"
            f"```mermaid\n"
            f"flowchart LR\n"
            f"    SourceSystem[External Source] --> ThisProcess[{name}] --> OutputReport[Downstream Consumer]\n"
            f"```\n\n"
            f"Rules for the diagram:\n"
            f"- Use flowchart LR\n"
            f"- Label every node in plain English using square brackets: NodeId[Plain English Label]\n"
            f"- Put real source systems and inputs on the left\n"
            f"- Put this process in the middle\n"
            f"- Put real downstream consumers or outputs on the right\n"
            f"- Use --> for all arrows\n\n"
            f"Information:\n{content[:2500]}"
        )

    def section_business_goal(self, name: str, content: str, doc_group: str = "") -> str:
        return self._call(
            f'Describe the business goal and value delivered by "{name}".\n\n'
            f"What business outcome does it enable? Which teams or decisions depend on it?\n\n"
            f"Information:\n{content[:2500]}"
        )

    def section_data_quality(self, name: str, content: str, doc_group: str = "") -> str:
        return self._call(
            f'Describe the data quality controls and error handling in "{name}".\n\n'
            f"What checks ensure the data is accurate and complete? "
            f"What happens when something goes wrong — does the process stop, send an alert, "
            f"skip bad records, or flag issues for review?\n\n"
            f"Information:\n{content[:3000]}"
        )

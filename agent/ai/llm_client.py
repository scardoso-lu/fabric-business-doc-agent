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

from agent.ai.base_client import BaseLLMClient
from agent.config import EMBEDDING_MODEL, LLM_MODEL, LLM_PROVIDER, OLLAMA_BASE_URL

if TYPE_CHECKING:
    from agent.rag.retriever import RAGRetriever

# ---------------------------------------------------------------------------
# System prompt — shared across all providers
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a business analyst writing internal documentation for non-technical readers (managers, project owners, operations staff).

Goal:
Explain what the data process does, why it matters, and how it behaves in practical terms.

Style:
- Use plain English.
- Write short, clear sentences.
- Use active voice and present tense.
- Be specific. Avoid vague phrases like "the process" when a clearer description is possible.

Terminology:
- Avoid technical or engineering terms.
- When needed, replace them with simple, concrete language:
  - "data set" or "data records" instead of technical storage terms
  - "calculation" or "step" instead of code or system components
  - "external service" or "data feed" instead of system interfaces
- If a technical term is necessary for clarity, use it once and briefly explain it.

Structure:
- Organize the explanation into short paragraphs.
- Use bullet points only for rules, conditions, or checks.
- Do not use headings or code blocks unless explicitly requested.
"""

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


def build_system_prompt() -> str:
    """Return the system prompt, appending company/project context if CONTEXT_FILE is set."""
    from agent.config import CONTEXT_TEXT
    if not CONTEXT_TEXT:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n"
        f"Organisation and project context — use this to make the documentation more specific "
        f"and relevant:\n{CONTEXT_TEXT}\n"
    )


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
    # Internal helpers
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

    def _call_anthropic(self, user_message: str, max_tokens: int) -> str:
        import anthropic as _anthropic
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
    # RAG context helper
    # ------------------------------------------------------------------

    def _get_rag_context(self, query: str, doc_group: str) -> str:
        if not self._retriever or not doc_group:
            return ""
        chunks = self._retriever.query(query, doc_group, top_k=3)
        if not chunks:
            return ""
        # Keep only short, clean lines — skip anything that looks like an instruction
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

    # ------------------------------------------------------------------
    # Public API — one method per document section
    # ------------------------------------------------------------------

    def section_purpose(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"purpose goal {name}", doc_group)
        prompt = (
            f"{bg}"
            f'Explain in plain English why "{name}" exists.\n\n'
            f"What business problem does it solve? What would be missing if it did not run?\n\n"
            f"Information:\n{content[:2500]}"
        )
        return self._call(prompt, max_tokens=500)

    def section_what_it_does(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"steps activities process {name}", doc_group)
        prompt = (
            f"{bg}"
            f'Describe in plain English what "{name}" does from start to finish.\n\n'
            f"Explain where the data comes from, what happens to it, and what the output is. "
            f"Focus on the business activity, not the technology.\n\n"
            f"Information:\n{content[:3000]}"
        )
        return self._call(prompt, max_tokens=600)

    def section_flow(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"dependencies connections sources outputs {name}", doc_group)
        prompt = (
            f"{bg}"
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
        return self._call_flow(prompt)

    def section_business_goal(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"business outcome value {name}", doc_group)
        prompt = (
            f"{bg}"
            f'Describe the business goal and value delivered by "{name}".\n\n'
            f"What business outcome does it enable? Which teams or decisions depend on it?\n\n"
            f"Information:\n{content[:2500]}"
        )
        return self._call(prompt, max_tokens=500)

    def section_data_quality(self, name: str, content: str, doc_group: str = "") -> str:
        bg = self._get_rag_context(f"validation error handling alerts quality {name}", doc_group)
        prompt = (
            f"{bg}"
            f'Describe the data quality controls and error handling in "{name}".\n\n'
            f"What checks ensure the data is accurate and complete? "
            f"What happens when something goes wrong — does the process stop, send an alert, "
            f"skip bad records, or flag issues for review?\n\n"
            f"Information:\n{content[:3000]}"
        )
        return self._call(prompt, max_tokens=600)

    @property
    def provider(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_NOISE_PREFIXES = (
    "no ", "note:", "answer", "paragraph", "section", "write ", "return ",
    "do not", "%%", "example:", "output:", "response:",
)


def _clean_output(text: str) -> str:
    """Remove common LLM artefacts: echoed instructions, meta-comments, code fences."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        # Drop lines that are echoed instructions or meta-comments
        if any(lower.startswith(p) for p in _NOISE_PREFIXES):
            continue
        # Drop code fences
        if stripped.startswith("```") or stripped.startswith("~~~"):
            continue
        # Drop lines that are just punctuation or single characters
        if len(stripped) <= 2:
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    # Collapse 3+ blank lines into 2
    import re
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned or "Insufficient information available."


def _clean_flow_output(text: str) -> str:
    """Clean flow section output, preserving the mermaid diagram block intact."""
    import re
    mermaid_start = text.find("```mermaid")
    if mermaid_start == -1:
        return _clean_output(text)

    text_part = text[:mermaid_start]
    diagram_part = text[mermaid_start:]

    cleaned_text = _clean_output(text_part)

    # Find the closing fence (skip past the opening ```mermaid)
    closing = diagram_part.find("```", len("```mermaid"))
    if closing == -1:
        mermaid_block = diagram_part.rstrip() + "\n```"
    else:
        mermaid_block = diagram_part[: closing + 3]

    # Collapse excess blank lines inside the mermaid block
    mermaid_block = re.sub(r"\n{3,}", "\n\n", mermaid_block)

    return f"{cleaned_text}\n\n{mermaid_block}".strip() or "Insufficient information available."


def _summarise_props(props: dict) -> str:
    if not props:
        return "(none)"
    parts = []
    for k, v in props.items():
        if isinstance(v, dict):
            parts.append(f"{k}: {{...}}")
        elif isinstance(v, list):
            parts.append(f"{k}: [{len(v)} items]")
        elif isinstance(v, str) and len(v) > 120:
            parts.append(f"{k}: {v[:120]}…")
        else:
            parts.append(f"{k}: {v}")
    return ", ".join(parts)

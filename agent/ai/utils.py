"""
Shared LLM output utilities.

These functions are used by both LLMClient and LocalClaudeClient and live
here to avoid circular imports and to keep each client module focused on
its provider-specific concerns.
"""

from __future__ import annotations

import re


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
        if any(lower.startswith(p) for p in _NOISE_PREFIXES):
            continue
        if stripped.startswith("```") or stripped.startswith("~~~"):
            continue
        if len(stripped) <= 2:
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned or "Insufficient information available."


def _clean_flow_output(text: str) -> str:
    """Clean flow section output, preserving the mermaid diagram block intact."""
    mermaid_start = text.find("```mermaid")
    if mermaid_start == -1:
        return _clean_output(text)

    text_part = text[:mermaid_start]
    diagram_part = text[mermaid_start:]

    cleaned_text = _clean_output(text_part)

    closing = diagram_part.find("```", len("```mermaid"))
    if closing == -1:
        mermaid_block = diagram_part.rstrip() + "\n```"
    else:
        mermaid_block = diagram_part[: closing + 3]

    mermaid_block = re.sub(r"\n{3,}", "\n\n", mermaid_block)

    return f"{cleaned_text}\n\n{mermaid_block}".strip() or "Insufficient information available."


def _clean_lineage_output(text: str) -> str:
    """Minimal cleanup for lineage section — preserves markdown tables, headings, and notes."""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            continue
        lines.append(line)
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned or "No column lineage detected in this artifact."


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


def build_system_prompt() -> str:
    """Return the active system prompt, appending company/project context if set."""
    import agent.prompts as prompts
    from agent.config import CONTEXT_TEXT
    base = prompts.get("system_prompt")
    if not CONTEXT_TEXT:
        return base
    return (
        f"{base}\n"
        f"Organisation and project context — use this to make the documentation more specific "
        f"and relevant:\n{CONTEXT_TEXT}\n"
    )

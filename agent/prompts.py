"""
Per-section prompt configuration.

Each document section (Purpose, Flow, Business Goal,
Data Quality & Alerts, Column Lineage) has its own prompt template that
controls what the LLM is asked to produce. The two system prompts — the
general business-analyst role and the lineage-analyst role — are also
configurable.

Templates use {{name}}, {{content}}, and {{rag_context}} as placeholders.
The agent substitutes real values at generation time.

Prompts are loaded once from a markdown file whose path is given by
PROMPTS_FILE in .env (default: prompts.md in the project root). Every
## heading in that file whose text matches a known key overrides the
built-in default for that key. Sections absent from the file keep their
defaults, so partial customisation is safe.

Call initialise() explicitly with the file path before the first LLM
call, or let get() auto-initialise from defaults on first use.
"""

from __future__ import annotations

import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Built-in defaults
# ---------------------------------------------------------------------------

DEFAULT_SYSTEM_PROMPT = """You are a business analyst writing internal documentation for non-technical readers (managers, project owners, operations staff).

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
- Do not use headings or code blocks unless explicitly requested."""

DEFAULT_LINEAGE_SYSTEM_PROMPT = """You are a data lineage analyst. Extract column-level data lineage from the code provided.

Output rules (follow exactly):
- Produce one Markdown table per layer pair, working backwards from gold to bronze.
- Label each table with a heading in the form: ### <Source Layer> → <Target Layer>  (e.g., ### Silver → Gold)
- Every table must use EXACTLY these headers: | Source | Target Column | Transformation Logic |
- "Source" = source column name (or table.column if the table is identifiable).
- "Target Column" = destination column name.
- "Transformation Logic" = a brief, plain-English description of what changes (e.g., "Cast to Integer", "Multiplied by tax rate", "Concatenated with separator", "Pass-through", "Derived from ML model output").
- When multiple source columns are combined into one target column, append a footnote marker [^N] to the Transformation Logic cell and add a **Note N:** line after the table explaining the merge rule.
- If the code does not contain clear column-level transformations, return this exact string: No column lineage detected in this artifact.
- Do not output any introductory text, prose explanations, or commentary outside of tables and notes."""

DEFAULT_PROMPTS: dict[str, str] = {
    "system_prompt": DEFAULT_SYSTEM_PROMPT,

    "lineage_system_prompt": DEFAULT_LINEAGE_SYSTEM_PROMPT,

    "purpose": """\
{{rag_context}}In one or two sentences, explain why "{{name}}" exists and what business problem it solves.

Information:
{{content}}

---

What would be missing or broken for the business if "{{name}}" did not run? Keep to one sentence.

Information:
{{content}}""",

    "flow": """\
{{rag_context}}In at most two short paragraphs, describe the data flow for "{{name}}": where data comes from, what this process does to it, and where the output goes. Use plain business language.

Information:
{{content}}

---

Produce a Mermaid diagram for "{{name}}". Follow this format exactly — no extra text after the diagram:

```mermaid
flowchart LR
    SourceSystem[External Source] --> ThisProcess[{{name}}] --> OutputReport[Downstream Consumer]
```

Rules for the diagram:
- Use flowchart LR
- Label every node in plain English using square brackets: NodeId[Plain English Label]
- Put real source systems and inputs on the left
- Put this process in the middle
- Put real downstream consumers or outputs on the right
- Use --> for all arrows

Information:
{{content}}""",

    "business_goal": """\
{{rag_context}}What business outcome does "{{name}}" deliver? Describe the value it produces in one or two sentences.

Information:
{{content}}

---

Which teams, reports, or decisions depend on "{{name}}"? What breaks if it stops running?

Information:
{{content}}""",

    "data_quality": """\
{{rag_context}}What validation checks does "{{name}}" apply to ensure the data is accurate and complete? List the specific rules or conditions checked.

Information:
{{content}}

---

What happens when a data quality check fails in "{{name}}"? Does the process stop, send an alert, skip bad records, or flag issues for review?

Information:
{{content}}""",

    "column_lineage": """\
Extract column-level data lineage for "{{name}}".

Trace each column from the gold (final output) table backwards through silver to bronze (raw source). Produce one table per layer pair (e.g., Silver → Gold, Bronze → Silver). Describe the transformation applied to each column in plain English.

Code and schema information:
{{content}}""",
}

# Keys that are valid in the prompts file.
SECTION_KEYS = tuple(DEFAULT_PROMPTS)

# ---------------------------------------------------------------------------
# Module state
# ---------------------------------------------------------------------------

_active: dict[str, str] | None = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def initialise(path: Path | None = None) -> None:
    """Load prompts from *path*, falling back to defaults for missing keys.

    Safe to call multiple times — each call reloads from scratch.
    """
    global _active
    merged = dict(DEFAULT_PROMPTS)
    if path is not None and path.exists():
        overrides = _parse_file(path)
        merged.update(overrides)
    _active = merged


def get(key: str) -> str:
    """Return the active template for *key*, auto-initialising from defaults."""
    if _active is None:
        initialise()
    return _active.get(key, DEFAULT_PROMPTS.get(key, ""))  # type: ignore[union-attr]


def render(template: str, **kwargs: str) -> str:
    """Replace {{variable}} placeholders in *template* with *kwargs* values."""
    result = template
    for k, v in kwargs.items():
        result = result.replace("{{" + k + "}}", v)
    return result


def get_sub_prompts(key: str) -> list[str]:
    """Return the ordered list of sub-prompts for *key*.

    A section template may contain one or more sub-prompts separated by lines
    consisting solely of ``---``.  Each sub-prompt is trimmed and empty parts
    (e.g. from a trailing separator) are discarded.  If the template has no
    separator the returned list contains the single template string.
    """
    template = get(key)
    parts = re.split(r"\n---+\n?", template)
    result = [p.strip() for p in parts if p.strip()]
    return result or [template]


def _strip_blockquotes(text: str) -> str:
    """Remove Markdown blockquote lines (starting with '>') from *text*."""
    lines = [line for line in text.splitlines() if not line.lstrip().startswith(">")]
    return "\n".join(lines)


def _reset() -> None:
    """Reset module state. Intended for tests only."""
    global _active
    _active = None


# ---------------------------------------------------------------------------
# File parser
# ---------------------------------------------------------------------------

def _parse_file(path: Path) -> dict[str, str]:
    """Parse a markdown file and return a dict of section_key → template."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return {}

    # Split on ## headings. Result: [preamble, key1, body1, key2, body2, ...]
    parts = re.split(r"^## (.+)$", text, flags=re.MULTILINE)
    result: dict[str, str] = {}
    for i in range(1, len(parts), 2):
        key = parts[i].strip()
        raw_body = parts[i + 1] if i + 1 < len(parts) else ""
        body = _strip_blockquotes(raw_body).strip()
        if key in DEFAULT_PROMPTS and body:
            result[key] = body
    return result

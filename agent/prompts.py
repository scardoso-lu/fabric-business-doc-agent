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

DEFAULT_PROMPTS: dict[str, str] = {
    "system_prompt": """\
You are a business analyst writing internal documentation for non-technical readers (managers, project owners, operations staff).

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
- Do not use headings or code blocks unless explicitly requested.""",

    "lineage_system_prompt": """\
You are a data lineage analyst. Extract column-level data lineage from the code provided.

Scope — only document tables that are written to persistent storage (data lake, lakehouse, or data warehouse):
- PySpark / Python: tables written with df.write.saveAsTable(), df.write.format(...).save(...), spark.sql("CREATE TABLE ..."), COPY INTO, or equivalent.
- SQL: permanent tables created or populated with CREATE TABLE, INSERT INTO, MERGE INTO, or SELECT INTO (not #temp, @variable, or CTE results).
- Power Query (M-code): only queries that are loaded to a destination (final output queries); skip intermediate helper queries that are only referenced by other queries.
- Exclude entirely: temporary tables (prefixed #, tmp_, temp_, or @), staging objects used only within the same script, in-memory DataFrames that are never persisted, CTEs, and subqueries.

Output rules (follow exactly):
- Produce one Markdown table per layer pair, working backwards from gold to bronze.
- Label each table with a heading in the form: ### <Source Layer> → <Target Layer>  (e.g., ### Silver → Gold)
- Every table must use EXACTLY these headers: | Source | Target Column | Transformation Logic |
- "Source" = source column name (or table.column if the table is identifiable).
- "Target Column" = destination column name.
- "Transformation Logic" = a brief, plain-English description of what changes (e.g., "Cast to Integer", "Multiplied by tax rate", "Concatenated with separator", "Pass-through", "Derived from ML model output").
- When multiple source columns are combined into one target column, append a footnote marker [^N] to the Transformation Logic cell and add a **Note N:** line after the table explaining the merge rule.
- If no persisted tables with detectable column-level transformations are found, return this exact string: No column lineage detected in this artifact.
- Do not output any introductory text, prose explanations, or commentary outside of tables and notes.""",

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
{{content}}

---

List the steps of "{{name}}" as a numbered pseudo-code walkthrough in plain English.

Rules:
- One line per step.
- Use two-space indentation for sub-steps inside loops, conditions, or branches.
- Label branches clearly (e.g. "If the file is empty:", "On failure:").
- Use plain business language — no programming syntax.
- Each step should say what it receives or checks, what it does, and what it produces or passes on.
- Precede the list with the bold heading **Steps:**

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
{{rag_context}}What validation checks, filters, or conditional logic does "{{name}}" apply to ensure the data is accurate and complete? List the specific rules, conditions, or thresholds checked.

Information:
{{content}}

---

What happens when something goes wrong in "{{name}}"? Look for:
- Exceptions or errors that are raised (raise statements, Fail activities, error conditions)
- If/else or Switch branches that handle bad data or failures
- External notifications triggered on failure: log messages, email alerts, webhook calls, Teams or Slack messages, API calls to monitoring systems

For each pattern found, describe: what condition triggers it, what the response is, and where the notification goes (recipient, log target, endpoint) if it can be identified from the code.

If no external alerting is found, state the fallback behaviour (stops silently, propagates the error, skips bad records, and so on).

Information:
{{content}}""",

    "column_lineage": """\
Extract column-level data lineage for "{{name}}".

Only trace tables that are written to persistent storage — the data lake, lakehouse, or data warehouse. Work backwards from the gold (final persisted output) through silver to bronze (raw source).

Skip temporary objects: any table or query whose name starts with #, tmp_, or temp_; any SQL @variable or CTE; any intermediate DataFrame or M-code query that is never written to a destination. If a layer contains only temporary objects, omit that layer entirely from the output.

Produce one table per layer pair (e.g., Silver → Gold, Bronze → Silver). Describe the transformation applied to each column in plain English.

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

    *path* may be a **directory** — each section lives in its own ``{key}.md``
    file — or a single markdown file with ``## key`` headings (legacy format).
    Safe to call multiple times; each call reloads from scratch.
    """
    global _active
    merged = dict(DEFAULT_PROMPTS)
    if path is not None and path.exists():
        if path.is_dir():
            overrides = _parse_dir(path)
        else:
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
# Loaders
# ---------------------------------------------------------------------------

def _parse_dir(directory: Path) -> dict[str, str]:
    """Load prompts from a directory of individual Markdown files.

    Each file must be named ``{section_key}.md``.  The entire file content is
    treated as the prompt body — no ``## heading`` is needed.  Editorial
    blockquote lines (lines starting with ``>``) are stripped before use, so
    you can annotate files freely without affecting the LLM prompt.
    """
    result: dict[str, str] = {}
    for key in DEFAULT_PROMPTS:
        file_path = directory / f"{key}.md"
        if file_path.exists():
            try:
                raw = file_path.read_text(encoding="utf-8")
                body = _strip_blockquotes(raw).strip()
                if body:
                    result[key] = body
            except OSError:
                pass
    return result


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

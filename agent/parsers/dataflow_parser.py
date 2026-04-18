"""
Parse Microsoft Fabric Dataflow Gen2 files.

Dataflow Gen2 files contain Power Query (M-code) query definitions.
Supported formats:
  - JSON with properties.definition.queries[].pq  (Fabric Git integration format)
  - JSON with top-level queries[].pq
  - JSON with a mashup string (section-based M-code)
  - Files with .dataflow extension (any of the above)
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class DataflowQuery:
    name: str
    pq_code: str
    description: str


@dataclass
class ParsedDataflow:
    name: str
    source_path: Path
    description: str
    queries: list[DataflowQuery] = field(default_factory=list)

    @property
    def all_mcode(self) -> str:
        parts = []
        for q in self.queries:
            header = f"// Query: {q.name}"
            if q.description:
                header += f"\n// {q.description}"
            parts.append(f"{header}\n{q.pq_code}")
        return "\n\n".join(parts)

    @property
    def query_names(self) -> list[str]:
        return [q.name for q in self.queries]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def parse_dataflow_file(path: Path) -> ParsedDataflow | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name") or path.stem
    description = data.get("description", "")

    queries = (
        _parse_queries_nested(data)
        or _parse_queries_flat(data)
        or _parse_mashup(data)
    )

    if not queries:
        return None

    return ParsedDataflow(
        name=name,
        source_path=path,
        description=description,
        queries=queries,
    )


def find_dataflow_files(root: Path) -> list[Path]:
    """Find all Dataflow Gen2 files under *root*."""
    candidates: list[Path] = []
    for ext in ("*.dataflow", "*.json"):
        candidates.extend(root.rglob(ext))

    dataflows: list[Path] = []
    for path in sorted(candidates):
        if ".git" in path.parts:
            continue
        df = parse_dataflow_file(path)
        if df is not None:
            dataflows.append(path)
    return dataflows


# ---------------------------------------------------------------------------
# Format handlers
# ---------------------------------------------------------------------------

def _parse_queries_nested(data: dict) -> list[DataflowQuery]:
    """Handle: properties.definition.queries[].pq"""
    queries_raw = (
        data.get("properties", {})
        .get("definition", {})
        .get("queries", [])
    )
    return _extract_query_list(queries_raw)


def _parse_queries_flat(data: dict) -> list[DataflowQuery]:
    """Handle: top-level queries[].pq"""
    return _extract_query_list(data.get("queries", []))


def _parse_mashup(data: dict) -> list[DataflowQuery]:
    """Handle: mashup string containing M-code sections."""
    mashup = data.get("mashup") or data.get("pbi:mashup", {})
    if isinstance(mashup, dict):
        mashup = mashup.get("mashup", "")
    if not isinstance(mashup, str) or not mashup.strip():
        return []
    return _parse_mashup_string(mashup)


def _extract_query_list(raw: list) -> list[DataflowQuery]:
    queries: list[DataflowQuery] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        pq = item.get("pq", "").strip()
        if not pq:
            continue
        queries.append(DataflowQuery(
            name=item.get("name", "Query"),
            pq_code=pq,
            description=item.get("description", ""),
        ))
    return queries


_SHARED_PATTERN = re.compile(
    r'shared\s+(\w+|\#"[^"]+")\s*=\s*(let\b.+?)\s*(?=shared\s|\Z)',
    re.DOTALL,
)


def _parse_mashup_string(mashup: str) -> list[DataflowQuery]:
    queries: list[DataflowQuery] = []
    for match in _SHARED_PATTERN.finditer(mashup):
        raw_name = match.group(1).strip('"#')
        pq_code = match.group(2).strip().rstrip(";")
        queries.append(DataflowQuery(name=raw_name, pq_code=pq_code, description=""))
    return queries

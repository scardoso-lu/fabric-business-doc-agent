"""
Parse Jupyter / Fabric notebook (.ipynb) files into structured sections.

Notebooks are scanned to build a list of logical sections, where each section
has a heading (from a markdown cell) and the code/markdown cells beneath it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NotebookCell:
    cell_type: str          # "code" or "markdown"
    source: str             # raw cell content as a single string
    cell_index: int


@dataclass
class NotebookSection:
    heading: str            # the markdown H2/H3 title, or "Introduction"
    cells: list[NotebookCell] = field(default_factory=list)

    @property
    def code_cells(self) -> list[NotebookCell]:
        return [c for c in self.cells if c.cell_type == "code"]

    @property
    def markdown_cells(self) -> list[NotebookCell]:
        return [c for c in self.cells if c.cell_type == "markdown"]

    @property
    def combined_code(self) -> str:
        return "\n\n".join(c.source for c in self.code_cells if c.source.strip())


@dataclass
class ParsedNotebook:
    name: str
    source_path: Path
    description: str        # first markdown cell content, if any
    sections: list[NotebookSection]
    language: str           # "python", "sql", etc.

    @property
    def all_code(self) -> str:
        return "\n\n".join(
            cell.source
            for section in self.sections
            for cell in section.cells
            if cell.cell_type == "code" and cell.source.strip()
        )


def _cell_source(raw: dict) -> str:
    src = raw.get("source", "")
    if isinstance(src, list):
        return "".join(src)
    return str(src)


def _extract_heading(source: str) -> str | None:
    """Return the first markdown heading text from a markdown cell, if present."""
    for line in source.splitlines():
        m = re.match(r"^#{1,6}\s+(.+)", line.strip())
        if m:
            return m.group(1).strip()
    return None


def parse_notebook_file(path: Path) -> ParsedNotebook | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if "cells" not in data:
        return None

    lang = (
        data.get("metadata", {})
        .get("kernelspec", {})
        .get("language", "python")
        .lower()
    )

    raw_cells = data["cells"]
    parsed_cells = [
        NotebookCell(
            cell_type=c.get("cell_type", "code"),
            source=_cell_source(c),
            cell_index=i,
        )
        for i, c in enumerate(raw_cells)
    ]

    # Extract description from the very first markdown cell
    description = ""
    for cell in parsed_cells:
        if cell.cell_type == "markdown" and cell.source.strip():
            description = cell.source.strip()
            break

    # Group cells into sections by markdown headings (H1-H3)
    sections: list[NotebookSection] = []
    current_section = NotebookSection(heading="Overview")

    for cell in parsed_cells:
        if cell.cell_type == "markdown":
            heading = _extract_heading(cell.source)
            if heading:
                if current_section.cells:
                    sections.append(current_section)
                current_section = NotebookSection(heading=heading)
                # Don't add the heading cell itself — the heading IS the section title
                continue
        current_section.cells.append(cell)

    if current_section.cells:
        sections.append(current_section)

    if not sections:
        sections = [NotebookSection(heading="Overview", cells=parsed_cells)]

    return ParsedNotebook(
        name=path.stem,
        source_path=path,
        description=description,
        sections=sections,
        language=lang,
    )


def find_notebook_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.ipynb") if ".git" not in p.parts
    )

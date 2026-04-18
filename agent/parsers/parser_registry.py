"""Registry of artifact parsers — the single entry point for dependency injection.

Call ``get_enabled_parsers(types)`` to get the active parser list for a run,
or ``get_parser(artifact_type)`` to look up one parser by name.

To add a new artifact type:
1. Implement ``ArtifactParser`` for the new type.
2. Register an instance in ``_REGISTRY`` below.
3. Add the type name to ``ARTIFACT_TYPES`` in ``.env``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from agent.parsers.base_parser import ArtifactParser
from agent.parsers.dataflow_parser import find_dataflow_files, parse_dataflow_file
from agent.parsers.notebook_parser import find_notebook_files, parse_notebook_file
from agent.parsers.pipeline_parser import find_pipeline_files, parse_pipeline_file


# ---------------------------------------------------------------------------
# Concrete parser implementations (thin wrappers around existing functions)
# ---------------------------------------------------------------------------

class _PipelineParser(ArtifactParser):
    @property
    def artifact_type(self) -> str:
        return "pipeline"

    def find_files(self, root: Path, name_filter: str | None = None) -> list[Path]:
        files = find_pipeline_files(root)
        if name_filter:
            files = [f for f in files if f.stem == name_filter]
        return files

    def parse(self, path: Path) -> Any | None:
        return parse_pipeline_file(path)


class _NotebookParser(ArtifactParser):
    @property
    def artifact_type(self) -> str:
        return "notebook"

    def find_files(self, root: Path, name_filter: str | None = None) -> list[Path]:
        files = find_notebook_files(root)
        if name_filter:
            files = [f for f in files if f.stem == name_filter]
        return files

    def parse(self, path: Path) -> Any | None:
        return parse_notebook_file(path)


class _DataflowParser(ArtifactParser):
    @property
    def artifact_type(self) -> str:
        return "dataflow"

    def find_files(self, root: Path, name_filter: str | None = None) -> list[Path]:
        files = find_dataflow_files(root)
        if name_filter:
            files = [f for f in files if f.stem == name_filter]
        return files

    def parse(self, path: Path) -> Any | None:
        return parse_dataflow_file(path)


class _PowerAutomateParser(ArtifactParser):
    @property
    def artifact_type(self) -> str:
        return "powerautomate"

    def find_files(self, root: Path, name_filter: str | None = None) -> list[Path]:
        from agent.parsers.powerautomate_parser import find_powerautomate_files
        files = find_powerautomate_files(root)
        if name_filter:
            files = [f for f in files if f.stem == name_filter]
        return files

    def parse(self, path: Path) -> Any | None:
        from agent.parsers.powerautomate_parser import parse_powerautomate_file
        return parse_powerautomate_file(path)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ArtifactParser] = {
    "pipeline":      _PipelineParser(),
    "notebook":      _NotebookParser(),
    "dataflow":      _DataflowParser(),
    "powerautomate": _PowerAutomateParser(),
}


def get_parser(artifact_type: str) -> ArtifactParser | None:
    """Return the parser for *artifact_type*, or None if the type is unknown."""
    return _REGISTRY.get(artifact_type.lower())


def get_enabled_parsers(enabled_types: list[str]) -> list[ArtifactParser]:
    """Return parsers for all types in *enabled_types*, in the given order."""
    return [_REGISTRY[t] for t in enabled_types if t in _REGISTRY]


def all_artifact_types() -> list[str]:
    """Return the names of all registered artifact types."""
    return list(_REGISTRY)

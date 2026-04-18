"""Abstract base class for all artifact parsers."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class ArtifactParser(ABC):
    """Discovers and parses one artifact type from the source directory.

    Subclass this to add support for a new artifact type.  Register the
    subclass in ``agent/parsers/parser_registry.py`` and add the type name
    to the ``ARTIFACT_TYPES`` environment variable.
    """

    @property
    @abstractmethod
    def artifact_type(self) -> str:
        """Short identifier: 'pipeline', 'notebook', 'dataflow', 'powerautomate'."""
        ...

    @abstractmethod
    def find_files(self, root: Path, name_filter: str | None = None) -> list[Path]:
        """Return all artifact files under *root*, optionally filtered by stem/name."""
        ...

    @abstractmethod
    def parse(self, path: Path) -> Any | None:
        """Parse one file; return the parsed artifact dataclass or None on failure."""
        ...

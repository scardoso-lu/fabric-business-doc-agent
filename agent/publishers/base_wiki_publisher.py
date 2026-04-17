from __future__ import annotations

from abc import ABC, abstractmethod


class BaseWikiPublisher(ABC):
    """Common interface for all wiki publisher implementations."""

    @abstractmethod
    def publish(self, name: str, content: str) -> str:
        """Create or update a wiki page for *name* with *content*. Returns the page URL."""
        ...

    @abstractmethod
    def page_exists(self, name: str) -> bool:
        """Return True if a page for *name* already exists in the wiki."""
        ...

"""
Wiki publisher factory.

Reads WIKI_TYPE from the environment and returns the appropriate publisher.
Supported values: azuredevops (default), confluence.
"""

from __future__ import annotations

import os

from agent.publishers.base_wiki_publisher import BaseWikiPublisher


def create_wiki_publisher() -> BaseWikiPublisher:
    wiki_type = os.getenv("WIKI_TYPE", "azuredevops").lower()
    if wiki_type == "confluence":
        from agent.publishers.confluence_publisher import _confluence_publisher_from_env
        return _confluence_publisher_from_env()
    from agent.publishers.wiki_publisher import _azuredevops_publisher_from_env
    return _azuredevops_publisher_from_env()

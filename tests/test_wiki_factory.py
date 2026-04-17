"""Tests for create_wiki_publisher factory."""

import pytest
from unittest.mock import patch

from agent.publishers.wiki_factory import create_wiki_publisher
from agent.publishers.wiki_publisher import AzureDevOpsWikiPublisher
from agent.publishers.confluence_publisher import ConfluencePublisher


_AZDO_ENV = {
    "AZDO_ORG": "org",
    "AZDO_PROJECT": "proj",
    "AZDO_WIKI_ID": "proj.wiki",
    "AZDO_PAT": "token",
}

_CONFLUENCE_ENV = {
    "CONFLUENCE_URL": "https://x.atlassian.net",
    "CONFLUENCE_SPACE_KEY": "SPACE",
    "CONFLUENCE_EMAIL": "a@b.com",
    "CONFLUENCE_API_TOKEN": "tok",
}


class TestCreateWikiPublisher:
    def test_defaults_to_azuredevops(self, monkeypatch):
        monkeypatch.delenv("WIKI_TYPE", raising=False)
        for k, v in _AZDO_ENV.items():
            monkeypatch.setenv(k, v)
        pub = create_wiki_publisher()
        assert isinstance(pub, AzureDevOpsWikiPublisher)

    def test_explicit_azuredevops(self, monkeypatch):
        monkeypatch.setenv("WIKI_TYPE", "azuredevops")
        for k, v in _AZDO_ENV.items():
            monkeypatch.setenv(k, v)
        pub = create_wiki_publisher()
        assert isinstance(pub, AzureDevOpsWikiPublisher)

    def test_confluence_type(self, monkeypatch):
        monkeypatch.setenv("WIKI_TYPE", "confluence")
        for k, v in _CONFLUENCE_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("CONFLUENCE_PARENT_PAGE_ID", raising=False)
        pub = create_wiki_publisher()
        assert isinstance(pub, ConfluencePublisher)

    def test_wiki_type_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("WIKI_TYPE", "Confluence")
        for k, v in _CONFLUENCE_ENV.items():
            monkeypatch.setenv(k, v)
        monkeypatch.delenv("CONFLUENCE_PARENT_PAGE_ID", raising=False)
        pub = create_wiki_publisher()
        assert isinstance(pub, ConfluencePublisher)

    def test_azdo_raises_without_required_vars(self, monkeypatch):
        monkeypatch.delenv("WIKI_TYPE", raising=False)
        for k in _AZDO_ENV:
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(ValueError):
            create_wiki_publisher()

    def test_confluence_raises_without_required_vars(self, monkeypatch):
        monkeypatch.setenv("WIKI_TYPE", "confluence")
        for k in _CONFLUENCE_ENV:
            monkeypatch.delenv(k, raising=False)
        with pytest.raises(ValueError):
            create_wiki_publisher()

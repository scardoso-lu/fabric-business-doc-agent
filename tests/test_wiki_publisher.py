"""Tests for WikiPublisher and publisher_from_env."""

import pytest
from unittest.mock import MagicMock, patch

from agent.publishers.wiki_publisher import WikiPublisher, publisher_from_env


@pytest.fixture
def publisher():
    return WikiPublisher(
        org="myorg",
        project="myproject",
        wiki_id="myproject.wiki",
        pat="secret-token",
    )


@pytest.fixture
def publisher_with_prefix():
    return WikiPublisher(
        org="myorg",
        project="myproject",
        wiki_id="myproject.wiki",
        pat="secret-token",
        path_prefix="/Fabric Docs",
    )


def _mock_get(status: int, etag: str | None = None):
    m = MagicMock()
    m.status_code = status
    m.headers = {"ETag": etag} if etag else {}
    m.raise_for_status = MagicMock()
    return m


def _mock_put():
    m = MagicMock()
    m.raise_for_status = MagicMock()
    return m


# ---------------------------------------------------------------------------
# WikiPublisher.publish
# ---------------------------------------------------------------------------

class TestPublish:
    def test_creates_new_page_without_if_match(self, publisher):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)), \
             patch("agent.publishers.wiki_publisher.requests.put", return_value=_mock_put()) as put_mock:
            publisher.publish("MyPipeline", "# Content")

        headers = put_mock.call_args.kwargs["headers"]
        assert "If-Match" not in headers

    def test_updates_existing_page_with_etag(self, publisher):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(200, '"abc123"')), \
             patch("agent.publishers.wiki_publisher.requests.put", return_value=_mock_put()) as put_mock:
            publisher.publish("MyPipeline", "# Updated")

        headers = put_mock.call_args.kwargs["headers"]
        assert headers["If-Match"] == '"abc123"'

    def test_sends_correct_content(self, publisher):
        content = "# MyPage\n\nSome content here."
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)), \
             patch("agent.publishers.wiki_publisher.requests.put", return_value=_mock_put()) as put_mock:
            publisher.publish("MyPage", content)

        assert put_mock.call_args.kwargs["json"] == {"content": content}

    def test_page_path_without_prefix(self, publisher):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)) as get_mock, \
             patch("agent.publishers.wiki_publisher.requests.put", return_value=_mock_put()):
            publisher.publish("MyPage", "content")

        params = get_mock.call_args.kwargs["params"]
        assert params["path"] == "/MyPage"

    def test_page_path_with_prefix(self, publisher_with_prefix):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)) as get_mock, \
             patch("agent.publishers.wiki_publisher.requests.put", return_value=_mock_put()):
            publisher_with_prefix.publish("MyPage", "content")

        params = get_mock.call_args.kwargs["params"]
        assert params["path"] == "/Fabric Docs/MyPage"

    def test_returns_url_string(self, publisher):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)), \
             patch("agent.publishers.wiki_publisher.requests.put", return_value=_mock_put()):
            url = publisher.publish("MyPage", "content")

        assert isinstance(url, str)
        assert "MyPage" in url


# ---------------------------------------------------------------------------
# WikiPublisher path prefix normalisation
# ---------------------------------------------------------------------------

class TestPageExists:
    def test_returns_true_when_page_found(self, publisher):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(200, '"v1"')):
            assert publisher.page_exists("MyPipeline") is True

    def test_returns_false_when_page_not_found(self, publisher):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)):
            assert publisher.page_exists("MyPipeline") is False

    def test_uses_prefix_in_path(self, publisher_with_prefix):
        with patch("agent.publishers.wiki_publisher.requests.get", return_value=_mock_get(404)) as get_mock:
            publisher_with_prefix.page_exists("MyPage")
        params = get_mock.call_args.kwargs["params"]
        assert params["path"] == "/Fabric Docs/MyPage"


class TestPathPrefix:
    def test_prefix_leading_slash_added(self):
        pub = WikiPublisher("o", "p", "w", "pat", path_prefix="Fabric Docs")
        assert pub._prefix == "/Fabric Docs"

    def test_prefix_trailing_slash_stripped(self):
        pub = WikiPublisher("o", "p", "w", "pat", path_prefix="/Fabric Docs/")
        assert pub._prefix == "/Fabric Docs"

    def test_empty_prefix_stays_empty(self):
        pub = WikiPublisher("o", "p", "w", "pat", path_prefix="")
        assert pub._prefix == ""


# ---------------------------------------------------------------------------
# publisher_from_env
# ---------------------------------------------------------------------------

class TestPublisherFromEnv:
    def test_raises_when_org_missing(self, monkeypatch):
        monkeypatch.delenv("AZDO_ORG", raising=False)
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_WIKI_ID", "proj.wiki")
        monkeypatch.setenv("AZDO_PAT", "token")
        with pytest.raises(ValueError, match="AZDO_ORG"):
            publisher_from_env()

    def test_raises_when_pat_missing(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_WIKI_ID", "proj.wiki")
        monkeypatch.delenv("AZDO_PAT", raising=False)
        with pytest.raises(ValueError, match="AZDO_PAT"):
            publisher_from_env()

    def test_raises_listing_all_missing(self, monkeypatch):
        for var in ("AZDO_ORG", "AZDO_PROJECT", "AZDO_WIKI_ID", "AZDO_PAT"):
            monkeypatch.delenv(var, raising=False)
        with pytest.raises(ValueError):
            publisher_from_env()

    def test_returns_publisher_with_all_vars(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_WIKI_ID", "proj.wiki")
        monkeypatch.setenv("AZDO_PAT", "token")
        monkeypatch.delenv("AZDO_WIKI_PATH_PREFIX", raising=False)
        pub = publisher_from_env()
        assert isinstance(pub, WikiPublisher)

    def test_applies_path_prefix_from_env(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_WIKI_ID", "proj.wiki")
        monkeypatch.setenv("AZDO_PAT", "token")
        monkeypatch.setenv("AZDO_WIKI_PATH_PREFIX", "/Docs")
        pub = publisher_from_env()
        assert pub._prefix == "/Docs"

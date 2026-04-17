"""Tests for ConfluencePublisher and helpers."""

import pytest
from unittest.mock import MagicMock, patch

from agent.publishers.confluence_publisher import (
    ConfluencePublisher,
    _confluence_publisher_from_env,
    _to_storage,
    _inline,
    _table_to_storage,
)


@pytest.fixture
def publisher():
    return ConfluencePublisher(
        url="https://example.atlassian.net",
        space_key="FABRIC",
        email="user@example.com",
        api_token="secret",
    )


@pytest.fixture
def publisher_with_parent():
    return ConfluencePublisher(
        url="https://example.atlassian.net",
        space_key="FABRIC",
        email="user@example.com",
        api_token="secret",
        parent_page_id="12345",
    )


def _mock_get_response(status: int, results: list | None = None):
    m = MagicMock()
    m.status_code = status
    m.raise_for_status = MagicMock()
    m.json.return_value = {"results": results or []}
    return m


def _mock_post_put_response(page_id: str = "99", webui: str = "/wiki/spaces/FABRIC/pages/99"):
    m = MagicMock()
    m.raise_for_status = MagicMock()
    m.json.return_value = {"id": page_id, "_links": {"webui": webui}}
    return m


# ---------------------------------------------------------------------------
# page_exists
# ---------------------------------------------------------------------------

class TestPageExists:
    def test_returns_true_when_page_found(self, publisher):
        fake_result = [{"id": "1", "version": {"number": 1}}]
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, fake_result)):
            assert publisher.page_exists("MyPage") is True

    def test_returns_false_when_no_results(self, publisher):
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, [])):
            assert publisher.page_exists("MyPage") is False


# ---------------------------------------------------------------------------
# publish — create path
# ---------------------------------------------------------------------------

class TestPublishCreate:
    def test_creates_page_when_not_exists(self, publisher):
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, [])), \
             patch("agent.publishers.confluence_publisher.requests.post",
                   return_value=_mock_post_put_response()) as post_mock:
            publisher.publish("NewPage", "# Hello")

        post_mock.assert_called_once()

    def test_create_sends_space_key(self, publisher):
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, [])), \
             patch("agent.publishers.confluence_publisher.requests.post",
                   return_value=_mock_post_put_response()) as post_mock:
            publisher.publish("NewPage", "# Hello")

        body = post_mock.call_args.kwargs["json"]
        assert body["space"]["key"] == "FABRIC"

    def test_create_without_parent_has_no_ancestors(self, publisher):
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, [])), \
             patch("agent.publishers.confluence_publisher.requests.post",
                   return_value=_mock_post_put_response()) as post_mock:
            publisher.publish("NewPage", "# Hello")

        body = post_mock.call_args.kwargs["json"]
        assert "ancestors" not in body

    def test_create_with_parent_includes_ancestors(self, publisher_with_parent):
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, [])), \
             patch("agent.publishers.confluence_publisher.requests.post",
                   return_value=_mock_post_put_response()) as post_mock:
            publisher_with_parent.publish("NewPage", "# Hello")

        body = post_mock.call_args.kwargs["json"]
        assert body["ancestors"] == [{"id": "12345"}]

    def test_returns_url_string(self, publisher):
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, [])), \
             patch("agent.publishers.confluence_publisher.requests.post",
                   return_value=_mock_post_put_response(webui="/wiki/pages/99")):
            url = publisher.publish("NewPage", "# Hello")

        assert url == "https://example.atlassian.net/wiki/pages/99"


# ---------------------------------------------------------------------------
# publish — update path
# ---------------------------------------------------------------------------

class TestPublishUpdate:
    def test_updates_existing_page(self, publisher):
        existing = [{"id": "55", "version": {"number": 3}}]
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, existing)), \
             patch("agent.publishers.confluence_publisher.requests.put",
                   return_value=_mock_post_put_response("55")) as put_mock:
            publisher.publish("ExistingPage", "# Updated")

        put_mock.assert_called_once()

    def test_update_increments_version(self, publisher):
        existing = [{"id": "55", "version": {"number": 3}}]
        with patch("agent.publishers.confluence_publisher.requests.get",
                   return_value=_mock_get_response(200, existing)), \
             patch("agent.publishers.confluence_publisher.requests.put",
                   return_value=_mock_post_put_response("55")) as put_mock:
            publisher.publish("ExistingPage", "# Updated")

        body = put_mock.call_args.kwargs["json"]
        assert body["version"]["number"] == 4


# ---------------------------------------------------------------------------
# _confluence_publisher_from_env
# ---------------------------------------------------------------------------

class TestConfluencePublisherFromEnv:
    _REQUIRED = {
        "CONFLUENCE_URL": "https://x.atlassian.net",
        "CONFLUENCE_SPACE_KEY": "SPACE",
        "CONFLUENCE_EMAIL": "a@b.com",
        "CONFLUENCE_API_TOKEN": "tok",
    }

    def _set_all(self, monkeypatch):
        for k, v in self._REQUIRED.items():
            monkeypatch.setenv(k, v)

    def test_raises_when_url_missing(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CONFLUENCE_URL")
        with pytest.raises(ValueError, match="CONFLUENCE_URL"):
            _confluence_publisher_from_env()

    def test_raises_when_space_missing(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CONFLUENCE_SPACE_KEY")
        with pytest.raises(ValueError, match="CONFLUENCE_SPACE_KEY"):
            _confluence_publisher_from_env()

    def test_raises_when_email_missing(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CONFLUENCE_EMAIL")
        with pytest.raises(ValueError, match="CONFLUENCE_EMAIL"):
            _confluence_publisher_from_env()

    def test_raises_when_token_missing(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CONFLUENCE_API_TOKEN")
        with pytest.raises(ValueError, match="CONFLUENCE_API_TOKEN"):
            _confluence_publisher_from_env()

    def test_returns_publisher_with_all_vars(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.delenv("CONFLUENCE_PARENT_PAGE_ID", raising=False)
        pub = _confluence_publisher_from_env()
        assert isinstance(pub, ConfluencePublisher)

    def test_applies_parent_page_id(self, monkeypatch):
        self._set_all(monkeypatch)
        monkeypatch.setenv("CONFLUENCE_PARENT_PAGE_ID", "42")
        pub = _confluence_publisher_from_env()
        assert pub._parent_id == "42"


# ---------------------------------------------------------------------------
# _inline
# ---------------------------------------------------------------------------

class TestInline:
    def test_bold(self):
        assert _inline("**hello**") == "<strong>hello</strong>"

    def test_italic(self):
        assert _inline("*world*") == "<em>world</em>"

    def test_code(self):
        assert _inline("`snippet`") == "<code>snippet</code>"

    def test_html_escaping(self):
        assert "&amp;" in _inline("a & b")
        assert "&lt;" in _inline("<tag>")

    def test_plain_text_unchanged(self):
        assert _inline("hello world") == "hello world"


# ---------------------------------------------------------------------------
# _table_to_storage
# ---------------------------------------------------------------------------

class TestTableToStorage:
    def test_first_row_is_th(self):
        rows = ["| Col A | Col B |", "| --- | --- |", "| val1 | val2 |"]
        result = _table_to_storage(rows)
        assert "<th>Col A</th>" in result
        assert "<th>Col B</th>" in result

    def test_data_rows_are_td(self):
        rows = ["| Col A | Col B |", "| --- | --- |", "| val1 | val2 |"]
        result = _table_to_storage(rows)
        assert "<td>val1</td>" in result

    def test_separator_row_skipped(self):
        rows = ["| A |", "| :--- |", "| x |"]
        result = _table_to_storage(rows)
        assert ":---" not in result

    def test_wraps_in_table_tags(self):
        rows = ["| A |", "| B |"]
        result = _table_to_storage(rows)
        assert result.startswith("<table>")
        assert result.endswith("</table>")


# ---------------------------------------------------------------------------
# _to_storage
# ---------------------------------------------------------------------------

class TestToStorage:
    def test_h1(self):
        assert "<h1>Title</h1>" in _to_storage("# Title")

    def test_h2(self):
        assert "<h2>Section</h2>" in _to_storage("## Section")

    def test_paragraph(self):
        assert "<p>Hello world</p>" in _to_storage("Hello world")

    def test_bullet_list(self):
        md = "- item one\n- item two"
        result = _to_storage(md)
        assert "<ul>" in result
        assert "<li>item one</li>" in result
        assert "<li>item two</li>" in result

    def test_horizontal_rule(self):
        assert "<hr/>" in _to_storage("---")

    def test_blank_lines_ignored(self):
        result = _to_storage("line one\n\nline two")
        assert result.count("<p>") == 2

    def test_code_block(self):
        md = "```python\nprint('hi')\n```"
        result = _to_storage(md)
        assert 'ac:name="code"' in result
        assert "print('hi')" in result

    def test_mermaid_block(self):
        md = "```mermaid\ngraph TD\nA --> B\n```"
        result = _to_storage(md)
        assert 'language">mermaid' in result
        assert "graph TD" in result

    def test_table_converted(self):
        md = "| A | B |\n| --- | --- |\n| 1 | 2 |"
        result = _to_storage(md)
        assert "<table>" in result
        assert "<th>A</th>" in result

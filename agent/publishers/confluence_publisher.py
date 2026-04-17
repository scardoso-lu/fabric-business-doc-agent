"""
Confluence wiki publisher.

Pushes generated markdown files to a Confluence space via the REST API v1.
Markdown is converted to Confluence storage format (XHTML) before upload.
Pages are created if they don't exist, or updated (incrementing the version).

Required .env variables:
    CONFLUENCE_URL          Base URL, e.g. https://mycompany.atlassian.net
    CONFLUENCE_SPACE_KEY    Space key, e.g. FABRIC
    CONFLUENCE_EMAIL        User email (Confluence Cloud)
    CONFLUENCE_API_TOKEN    API token (Confluence Cloud) or password (Server)

Optional:
    CONFLUENCE_PARENT_PAGE_ID   ID of the parent page. When set, all pages
                                are created as children of this page.
"""

from __future__ import annotations

import base64
import html
import os
import re

import requests

from agent.publishers.base_wiki_publisher import BaseWikiPublisher


class ConfluencePublisher(BaseWikiPublisher):
    _API = "/wiki/rest/api/content"

    def __init__(
        self,
        url: str,
        space_key: str,
        email: str,
        api_token: str,
        parent_page_id: str = "",
    ) -> None:
        self._base = url.rstrip("/") + self._API
        self._space = space_key
        self._parent_id = parent_page_id
        token = base64.b64encode(f"{email}:{api_token}".encode()).decode()
        self._auth_header = {
            "Authorization": f"Basic {token}",
            "Content-Type": "application/json",
        }
        self._web_base = url.rstrip("/")

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def publish(self, name: str, content: str) -> str:
        storage = _to_storage(content)
        page = self._get_page(name)
        if page:
            page_id = page["id"]
            version = page["version"]["number"] + 1
            return self._update_page(page_id, version, name, storage)
        return self._create_page(name, storage)

    def page_exists(self, name: str) -> bool:
        return self._get_page(name) is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_page(self, name: str) -> dict | None:
        resp = requests.get(
            self._base,
            params={"title": name, "spaceKey": self._space, "expand": "version"},
            headers=self._auth_header,
            timeout=30,
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return results[0] if results else None

    def _create_page(self, name: str, storage_content: str) -> str:
        body: dict = {
            "type": "page",
            "title": name,
            "space": {"key": self._space},
            "body": {"storage": {"value": storage_content, "representation": "storage"}},
        }
        if self._parent_id:
            body["ancestors"] = [{"id": self._parent_id}]
        resp = requests.post(self._base, headers=self._auth_header, json=body, timeout=30)
        resp.raise_for_status()
        return self._page_url(resp.json())

    def _update_page(self, page_id: str, version: int, name: str, storage_content: str) -> str:
        body = {
            "type": "page",
            "title": name,
            "version": {"number": version},
            "body": {"storage": {"value": storage_content, "representation": "storage"}},
        }
        resp = requests.put(
            f"{self._base}/{page_id}",
            headers=self._auth_header,
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
        return self._page_url(resp.json())

    def _page_url(self, page_data: dict) -> str:
        web_ui = page_data.get("_links", {}).get("webui", "")
        return f"{self._web_base}{web_ui}" if web_ui else self._web_base


def _confluence_publisher_from_env() -> ConfluencePublisher:
    missing = []
    url       = os.getenv("CONFLUENCE_URL", "")
    space_key = os.getenv("CONFLUENCE_SPACE_KEY", "")
    email     = os.getenv("CONFLUENCE_EMAIL", "")
    api_token = os.getenv("CONFLUENCE_API_TOKEN", "")
    parent_id = os.getenv("CONFLUENCE_PARENT_PAGE_ID", "")

    if not url:       missing.append("CONFLUENCE_URL")
    if not space_key: missing.append("CONFLUENCE_SPACE_KEY")
    if not email:     missing.append("CONFLUENCE_EMAIL")
    if not api_token: missing.append("CONFLUENCE_API_TOKEN")

    if missing:
        raise ValueError(
            f"Confluence wiki publishing requires these .env variables: {', '.join(missing)}"
        )
    return ConfluencePublisher(url, space_key, email, api_token, parent_page_id=parent_id)


# ---------------------------------------------------------------------------
# Markdown → Confluence storage format converter
# ---------------------------------------------------------------------------

def _to_storage(markdown: str) -> str:
    """Convert our generated markdown to Confluence storage format (XHTML)."""
    lines = markdown.splitlines()
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]

        # Fenced code / mermaid block
        if line.strip().startswith("```"):
            lang = line.strip()[3:].strip()
            block: list[str] = []
            i += 1
            while i < len(lines) and not lines[i].strip() == "```":
                block.append(lines[i])
                i += 1
            code_body = "\n".join(block)
            if lang == "mermaid":
                out.append(
                    '<ac:structured-macro ac:name="code">'
                    '<ac:parameter ac:name="language">mermaid</ac:parameter>'
                    f'<ac:plain-text-body><![CDATA[{code_body}]]></ac:plain-text-body>'
                    "</ac:structured-macro>"
                )
            else:
                lang_attr = f'<ac:parameter ac:name="language">{lang}</ac:parameter>' if lang else ""
                out.append(
                    f'<ac:structured-macro ac:name="code">{lang_attr}'
                    f'<ac:plain-text-body><![CDATA[{code_body}]]></ac:plain-text-body>'
                    "</ac:structured-macro>"
                )

        # Headings
        elif line.startswith("# "):
            out.append(f"<h1>{_inline(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{_inline(line[3:])}</h2>")

        # Horizontal rule / doc separator
        elif line.strip() == "---":
            out.append("<hr/>")

        # Markdown table — collect all consecutive table rows
        elif line.startswith("| "):
            rows: list[str] = []
            while i < len(lines) and lines[i].startswith("| "):
                rows.append(lines[i])
                i += 1
            out.append(_table_to_storage(rows))
            continue

        # Bullet list — collect consecutive items
        elif line.startswith("- ") or line.startswith("* "):
            items: list[str] = []
            while i < len(lines) and (lines[i].startswith("- ") or lines[i].startswith("* ")):
                items.append(f"<li>{_inline(lines[i][2:])}</li>")
                i += 1
            out.append("<ul>" + "".join(items) + "</ul>")
            continue

        # Blank line — skip
        elif line.strip() == "":
            pass

        # Regular paragraph
        else:
            out.append(f"<p>{_inline(line)}</p>")

        i += 1

    return "\n".join(out)


def _inline(text: str) -> str:
    """Apply inline markdown formatting to an already-HTML-escaped string."""
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"\*(.+?)\*",     r"<em>\1</em>",         text)
    text = re.sub(r"`(.+?)`",       r"<code>\1</code>",      text)
    return text


def _table_to_storage(rows: list[str]) -> str:
    """Convert a list of markdown table row strings to a Confluence storage table."""
    table = "<table>"
    first_data_row = True
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        # Skip separator rows (e.g. | --- | --- |)
        if all(re.fullmatch(r"[-: ]+", c) for c in cells):
            continue
        tag = "th" if first_data_row else "td"
        first_data_row = False
        table += "<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>"
    table += "</table>"
    return table

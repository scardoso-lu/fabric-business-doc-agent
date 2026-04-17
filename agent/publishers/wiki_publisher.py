"""
Azure DevOps Wiki publisher.

Pushes generated markdown files to an Azure DevOps project wiki via the REST API.
Each file becomes one wiki page. Pages are created if they don't exist, or updated
if they do (using the ETag version the API requires for safe updates).

Required .env variables:
    AZDO_ORG        Azure DevOps organisation name
    AZDO_PROJECT    Project name
    AZDO_WIKI_ID    Wiki identifier (the wiki name shown in the URL)
    AZDO_PAT        Personal Access Token with Wiki (Read & Write) scope

Optional:
    AZDO_WIKI_PATH_PREFIX   Page path prefix, e.g. "/Fabric Docs".
                            Defaults to "" (pages go at the wiki root).
"""

from __future__ import annotations

import base64
import os

import requests

from agent.publishers.base_wiki_publisher import BaseWikiPublisher


class AzureDevOpsWikiPublisher(BaseWikiPublisher):
    _API_VERSION = "7.1"

    def __init__(self, org: str, project: str, wiki_id: str, pat: str, path_prefix: str = "") -> None:
        self._base = (
            f"https://dev.azure.com/{org}/{project}/_apis/wiki/wikis/{wiki_id}/pages"
        )
        token = base64.b64encode(f":{pat}".encode()).decode()
        self._auth_header = {"Authorization": f"Basic {token}"}
        self._prefix = ("/" + path_prefix.strip("/")) if path_prefix else ""

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------

    def publish(self, name: str, content: str) -> str:
        page_path = f"{self._prefix}/{name}" if self._prefix else f"/{name}"
        etag = self._get_etag(page_path)
        self._put_page(page_path, content, etag)
        return self._page_url(page_path)

    def page_exists(self, name: str) -> bool:
        page_path = f"{self._prefix}/{name}" if self._prefix else f"/{name}"
        return self._get_etag(page_path) is not None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_etag(self, page_path: str) -> str | None:
        resp = requests.get(
            self._base,
            params={"path": page_path, "api-version": self._API_VERSION},
            headers=self._auth_header,
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.headers.get("ETag", "")
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    def _put_page(self, page_path: str, content: str, etag: str | None) -> None:
        headers = {**self._auth_header, "Content-Type": "application/json"}
        if etag is not None:
            headers["If-Match"] = etag
        resp = requests.put(
            self._base,
            params={"path": page_path, "api-version": self._API_VERSION},
            headers=headers,
            json={"content": content},
            timeout=30,
        )
        resp.raise_for_status()

    def _page_url(self, page_path: str) -> str:
        encoded = page_path.lstrip("/").replace(" ", "%20")
        base_url = self._base.split("/_apis/")[0]
        return f"{base_url}/_wiki/wikis/{encoded}"


def _azuredevops_publisher_from_env() -> AzureDevOpsWikiPublisher:
    missing = []
    org     = os.getenv("AZDO_ORG", "")
    project = os.getenv("AZDO_PROJECT", "")
    wiki_id = os.getenv("AZDO_WIKI_ID", "")
    pat     = os.getenv("AZDO_PAT", "")
    prefix  = os.getenv("AZDO_WIKI_PATH_PREFIX", "")

    if not org:     missing.append("AZDO_ORG")
    if not project: missing.append("AZDO_PROJECT")
    if not wiki_id: missing.append("AZDO_WIKI_ID")
    if not pat:     missing.append("AZDO_PAT")

    if missing:
        raise ValueError(
            f"Azure DevOps wiki publishing requires these .env variables: {', '.join(missing)}"
        )
    return AzureDevOpsWikiPublisher(org, project, wiki_id, pat, path_prefix=prefix)


# Keep old name for test backward compatibility
WikiPublisher = AzureDevOpsWikiPublisher
publisher_from_env = _azuredevops_publisher_from_env

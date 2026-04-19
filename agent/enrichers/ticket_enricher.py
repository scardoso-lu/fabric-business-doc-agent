"""
Ticket enricher — fetches related work items and pull requests for an artifact.

Supported backends (both optional, both tried if configured):
  Jira      — set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN (and optionally JIRA_PROJECT_KEY)
  Azure DevOps — set AZDO_ORG, AZDO_PROJECT, AZDO_PAT (same vars as wiki publishing)

Returns a plain-text summary of found items, or an empty string when nothing
is found or neither backend is configured. The caller is responsible for
deciding how to use the context (e.g. prepend to purpose content).

Work item search strategy (Azure DevOps):
  1. ADO Search REST API (almsearch.dev.azure.com) — full-text across all fields,
     fetches up to _SEARCH_CANDIDATES results.
  2. LLM re-ranking — the already-running LLM client filters the candidates down
     to those genuinely relevant to the artifact (skipped when client is None).
  3. WIQL fallback — used when the Search API is unavailable (e.g. on-premises
     ADO Server without Search enabled).
"""

from __future__ import annotations

import base64
import os
import re

import requests

_MAX_RESULTS = 5          # WIQL fallback and PR search result cap
_SEARCH_CANDIDATES = 10   # wider net for Search API before LLM re-ranking
_TIMEOUT = 10

# Common Fabric/Power Automate type prefixes that are never part of the business name
_PREFIX_RE = re.compile(
    r"^(?:pl|nb|df|pa|pipeline|notebook|dataflow|powerautomate|flow)[-_]",
    re.IGNORECASE,
)
# Version suffixes like _v2, -v3
_VERSION_RE = re.compile(r"[-_]v\d+$", re.IGNORECASE)
# CamelCase word boundary: LoadCustomerData → Load Customer Data
_CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# ADO Search API highlight tags
_HIGHLIGHT_TAG_RE = re.compile(r"</?highlighthit>", re.IGNORECASE)


def _normalize_artifact_name(name: str) -> str:
    """
    Convert a technical artifact name to a human-readable search string.

    Strips common type prefixes and version suffixes, splits CamelCase,
    and replaces underscores/hyphens with spaces so the result matches
    the natural-language titles used in work items and pull requests.

    Examples:
      pl_load_customer_data     → load customer data
      nb_SalesForecast_v2       → SalesForecast  → sales forecast
      LoadCustomerData          → Load Customer Data
      customer-data-pipeline    → customer data pipeline
    """
    name = _PREFIX_RE.sub("", name)
    name = _VERSION_RE.sub("", name)
    name = _CAMEL_RE.sub(" ", name)
    name = re.sub(r"[-_]+", " ", name)
    return name.strip()


def _strip_highlight_tags(text: str) -> str:
    """Remove <highlighthit> / </highlighthit> tags from ADO Search API snippets."""
    return _HIGHLIGHT_TAG_RE.sub("", text)


def fetch_ticket_context(artifact_name: str, client=None) -> str:
    """Return a formatted string of related tickets/PRs, or '' if none found.

    Args:
        artifact_name: The technical name of the artifact being documented.
        client: Optional BaseLLMClient used to re-rank Azure DevOps search
                results.  When None, all Search API candidates are returned
                without filtering.
    """
    parts: list[str] = []

    jira_ctx = _fetch_jira(artifact_name)
    if jira_ctx:
        parts.append(jira_ctx)

    azdo_ctx = _fetch_azdo(artifact_name, client)
    if azdo_ctx:
        parts.append(azdo_ctx)

    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# Jira
# ---------------------------------------------------------------------------

def _fetch_jira(name: str) -> str:
    url = os.getenv("JIRA_URL", "").rstrip("/")
    email = os.getenv("JIRA_EMAIL", "")
    token = os.getenv("JIRA_API_TOKEN", "")

    if not (url and email and token):
        return ""

    project_key = os.getenv("JIRA_PROJECT_KEY", "")
    normalized = _normalize_artifact_name(name)
    if normalized and normalized.lower() != name.lower():
        text_clause = f'text ~ "{name}" OR text ~ "{normalized}"'
    else:
        text_clause = f'text ~ "{name}"'
    jql = f"({text_clause})"
    if project_key:
        jql = f"project = {project_key} AND {jql}"
    jql += " ORDER BY updated DESC"

    auth = base64.b64encode(f"{email}:{token}".encode()).decode()
    headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}

    try:
        resp = requests.get(
            f"{url}/rest/api/3/issue/search",
            headers=headers,
            params={"jql": jql, "maxResults": _MAX_RESULTS, "fields": "summary,description"},
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        issues = resp.json().get("issues", [])
        if not issues:
            return ""

        lines = ["Jira issues:"]
        for issue in issues:
            key = issue["key"]
            fields = issue.get("fields", {})
            summary = fields.get("summary", "")
            desc = _extract_jira_text(fields.get("description"))
            line = f"- [{key}] {summary}"
            if desc:
                line += f"\n  {desc[:200]}"
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""


def _extract_jira_text(node) -> str:
    """Recursively extract plain text from a Jira Atlassian Document Format node."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node.strip()
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        return " ".join(_extract_jira_text(c) for c in node.get("content", [])).strip()
    if isinstance(node, list):
        return " ".join(_extract_jira_text(c) for c in node).strip()
    return ""


# ---------------------------------------------------------------------------
# Azure DevOps
# ---------------------------------------------------------------------------

def _fetch_azdo(name: str, client=None) -> str:
    org = os.getenv("AZDO_ORG", "")
    project = os.getenv("AZDO_PROJECT", "")
    pat = os.getenv("AZDO_PAT", "")

    if not (org and project and pat):
        return ""

    auth = base64.b64encode(f":{pat}".encode()).decode()
    headers = {
        "Authorization": f"Basic {auth}",
        "Content-Type": "application/json",
    }
    base_url = f"https://dev.azure.com/{org}/{project}/_apis"

    parts: list[str] = []

    # Search API first (full-text, all fields); WIQL as fallback
    wi_ctx = _search_azdo_workitems(name, org, project, headers)
    if not wi_ctx:
        wi_ctx = _fetch_azdo_workitems(name, base_url, headers)
    if wi_ctx:
        wi_ctx = _rerank_work_items(name, wi_ctx, client)
        if wi_ctx:
            parts.append(wi_ctx)

    pr_ctx = _fetch_azdo_prs(name, base_url, headers)
    if pr_ctx:
        parts.append(pr_ctx)

    return "\n\n".join(parts)


def _search_azdo_workitems(name: str, org: str, project: str, headers: dict) -> str:
    """Full-text search across all work item fields via the ADO Search REST API.

    Fetches up to _SEARCH_CANDIDATES results so the LLM re-ranker has a wider
    pool to choose the best matches from.  Field names in the response are
    lowercase (system.id, system.title, …), unlike the WIQL endpoint.
    """
    normalized = _normalize_artifact_name(name)
    search_text = normalized if normalized else name
    url = (
        f"https://almsearch.dev.azure.com/{org}/{project}"
        f"/_apis/search/workitemsearchresults?api-version=7.1-preview.1"
    )
    payload = {
        "searchText": search_text,
        "$top": _SEARCH_CANDIDATES,
        "includeSnippet": True,
        "filters": {"System.TeamProject": [project]},
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=_TIMEOUT)
        resp.raise_for_status()
        results = resp.json().get("results", [])
        if not results:
            return ""

        lines = ["Azure DevOps work items:"]
        for result in results:
            fields  = result.get("fields", {})
            wi_id   = fields.get("system.id", "")
            title   = fields.get("system.title", "")
            wi_type = fields.get("system.workitemtype", "")
            state   = fields.get("system.state", "")

            hits    = result.get("hits", [])
            snippet = ""
            if hits:
                raw_hl  = hits[0].get("highlights", [""])[0]
                snippet = _strip_highlight_tags(raw_hl)
            if not snippet:
                raw_desc = fields.get("system.description", "") or ""
                snippet  = re.sub(r"<[^>]+>", " ", raw_desc).strip()[:200]

            line = f"- [#{wi_id}] {title}"
            meta = [p for p in (wi_type, state) if p]
            if meta:
                line += f" ({', '.join(meta)})"
            if snippet:
                line += f"\n  {snippet}"
            lines.append(line)

        return "\n".join(lines)
    except Exception:
        return ""


def _rerank_work_items(artifact_name: str, items_text: str, client) -> str:
    """Ask the LLM to keep only work items genuinely relevant to the artifact.

    Passes the raw Search/WIQL result block to the active LLM client with a
    short filtering prompt.  Returns the original block unchanged when:
      - client is None (no LLM configured)
      - the LLM strips everything useful
      - the LLM call raises an exception
    """
    if client is None:
        return items_text

    prompt = (
        f"The following Azure DevOps work items were retrieved while documenting "
        f'the artifact "{artifact_name}". '
        f"Keep only the items that are genuinely relevant to this artifact. "
        f"Remove any that are unrelated or only tangentially matched. "
        f'Return exactly the same bullet-point format — each line starting with "- [#". '
        f"If none are relevant, return an empty string.\n\n"
        f"{items_text}"
    )
    try:
        filtered = client._call(prompt, max_tokens=500)
        if not filtered or "- [#" not in filtered:
            return items_text
        return "Azure DevOps work items:\n" + filtered.strip()
    except Exception:
        return items_text


def _fetch_azdo_workitems(name: str, base_url: str, headers: dict) -> str:
    safe_name = name.replace("'", "''")
    normalized = _normalize_artifact_name(name)
    safe_norm = normalized.replace("'", "''")

    # Match the raw technical name (exact substring) OR the human-readable
    # normalized form using word-level matching so "load customer data" matches
    # "Load Customer Data Pipeline" even though the artifact is "pl_load_customer_data".
    if safe_norm and safe_norm.lower() != safe_name.lower():
        where = (
            f"[System.Title] CONTAINS '{safe_name}' "
            f"OR [System.Title] CONTAINS WORDS '{safe_norm}'"
        )
    else:
        where = f"[System.Title] CONTAINS '{safe_name}'"

    wiql = {
        "query": (
            f"SELECT [System.Id] FROM WorkItems "
            f"WHERE {where} "
            f"ORDER BY [System.ChangedDate] DESC"
        )
    }
    try:
        resp = requests.post(
            f"{base_url}/wit/wiql?api-version=7.1",
            json=wiql,
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        ids = [wi["id"] for wi in resp.json().get("workItems", [])][:_MAX_RESULTS]
        if not ids:
            return ""

        resp2 = requests.get(
            f"{base_url}/wit/workitems",
            params={
                "ids": ",".join(str(i) for i in ids),
                "fields": "System.Title,System.Description",
                "api-version": "7.1",
            },
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp2.raise_for_status()
        items = resp2.json().get("value", [])
        if not items:
            return ""

        lines = ["Azure DevOps work items:"]
        for item in items:
            wi_id = item["id"]
            fields = item.get("fields", {})
            title = fields.get("System.Title", "")
            desc = re.sub(r"<[^>]+>", " ", fields.get("System.Description", "") or "").strip()
            line = f"- [#{wi_id}] {title}"
            if desc:
                line += f"\n  {desc[:200]}"
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""


def _fetch_azdo_prs(name: str, base_url: str, headers: dict) -> str:
    normalized = _normalize_artifact_name(name)
    search_title = normalized if normalized else name
    try:
        resp = requests.get(
            f"{base_url}/git/pullrequests",
            params={
                "searchCriteria.status": "all",
                "searchCriteria.title": search_title,
                "$top": _MAX_RESULTS,
                "api-version": "7.1",
            },
            headers=headers,
            timeout=_TIMEOUT,
        )
        resp.raise_for_status()
        prs = resp.json().get("value", [])
        if not prs:
            return ""

        lines = ["Azure DevOps pull requests:"]
        for pr in prs:
            pr_id = pr.get("pullRequestId", "")
            title = pr.get("title", "")
            desc = (pr.get("description", "") or "")[:200]
            line = f"- [PR #{pr_id}] {title}"
            if desc:
                line += f"\n  {desc}"
            lines.append(line)
        return "\n".join(lines)
    except Exception:
        return ""

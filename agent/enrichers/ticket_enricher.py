"""
Ticket enricher — fetches related work items and pull requests for an artifact.

Supported backends (both optional, both tried if configured):
  Jira      — set JIRA_URL, JIRA_EMAIL, JIRA_API_TOKEN (and optionally JIRA_PROJECT_KEY)
  Azure DevOps — set AZDO_ORG, AZDO_PROJECT, AZDO_PAT (same vars as wiki publishing)

Returns a plain-text summary of found items, or an empty string when nothing
is found or neither backend is configured. The caller is responsible for
deciding how to use the context (e.g. prepend to purpose content).
"""

from __future__ import annotations

import base64
import os
import re

import requests

_MAX_RESULTS = 5
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


def fetch_ticket_context(artifact_name: str) -> str:
    """Return a formatted string of related tickets/PRs, or '' if none found."""
    parts: list[str] = []

    jira_ctx = _fetch_jira(artifact_name)
    if jira_ctx:
        parts.append(jira_ctx)

    azdo_ctx = _fetch_azdo(artifact_name)
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

def _fetch_azdo(name: str) -> str:
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

    wi_ctx = _fetch_azdo_workitems(name, base_url, headers)
    if wi_ctx:
        parts.append(wi_ctx)

    pr_ctx = _fetch_azdo_prs(name, base_url, headers)
    if pr_ctx:
        parts.append(pr_ctx)

    return "\n\n".join(parts)


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

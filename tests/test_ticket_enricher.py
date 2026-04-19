"""Tests for agent/enrichers/ticket_enricher.py"""

from unittest.mock import MagicMock, patch

import pytest

from agent.enrichers.ticket_enricher import (
    _extract_jira_text,
    _fetch_azdo,
    _fetch_azdo_prs,
    _fetch_azdo_workitems,
    _fetch_jira,
    _normalize_artifact_name,
    fetch_ticket_context,
)


# ---------------------------------------------------------------------------
# _normalize_artifact_name
# ---------------------------------------------------------------------------

class TestNormalizeArtifactName:
    def test_strips_pl_prefix(self):
        assert _normalize_artifact_name("pl_load_customer_data") == "load customer data"

    def test_strips_nb_prefix(self):
        assert _normalize_artifact_name("nb_sales_forecast") == "sales forecast"

    def test_strips_df_prefix(self):
        assert _normalize_artifact_name("df_order_processing") == "order processing"

    def test_strips_pa_prefix(self):
        assert _normalize_artifact_name("pa_send_notification") == "send notification"

    def test_strips_pipeline_prefix(self):
        assert _normalize_artifact_name("pipeline_load_data") == "load data"

    def test_strips_version_suffix(self):
        assert _normalize_artifact_name("pl_load_data_v2") == "load data"

    def test_strips_version_suffix_hyphen(self):
        assert _normalize_artifact_name("nb_forecast-v3") == "forecast"

    def test_splits_camelcase(self):
        assert _normalize_artifact_name("LoadCustomerData") == "Load Customer Data"

    def test_replaces_underscores_with_spaces(self):
        assert _normalize_artifact_name("load_customer_data") == "load customer data"

    def test_replaces_hyphens_with_spaces(self):
        assert _normalize_artifact_name("load-customer-data") == "load customer data"

    def test_prefix_and_camel(self):
        result = _normalize_artifact_name("pl_LoadCustomerData")
        assert "Load Customer Data" in result
        assert "pl" not in result.lower().split()[0]

    def test_no_transformation_needed(self):
        assert _normalize_artifact_name("salesdata") == "salesdata"

    def test_empty_string(self):
        assert _normalize_artifact_name("") == ""


# ---------------------------------------------------------------------------
# _extract_jira_text
# ---------------------------------------------------------------------------

class TestExtractJiraText:
    def test_none_returns_empty(self):
        assert _extract_jira_text(None) == ""

    def test_plain_string(self):
        assert _extract_jira_text("hello") == "hello"

    def test_text_node(self):
        node = {"type": "text", "text": "Load daily sales data"}
        assert _extract_jira_text(node) == "Load daily sales data"

    def test_nested_document(self):
        doc = {
            "type": "doc",
            "content": [
                {
                    "type": "paragraph",
                    "content": [{"type": "text", "text": "This pipeline loads data."}],
                }
            ],
        }
        assert "This pipeline loads data." in _extract_jira_text(doc)

    def test_list_of_nodes(self):
        nodes = [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]
        result = _extract_jira_text(nodes)
        assert "A" in result and "B" in result


# ---------------------------------------------------------------------------
# _fetch_jira — not configured
# ---------------------------------------------------------------------------

class TestFetchJiraNotConfigured:
    def test_returns_empty_when_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("JIRA_URL", raising=False)
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        assert _fetch_jira("MyPipeline") == ""

    def test_returns_empty_when_partial_config(self, monkeypatch):
        monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
        monkeypatch.delenv("JIRA_EMAIL", raising=False)
        monkeypatch.delenv("JIRA_API_TOKEN", raising=False)
        assert _fetch_jira("MyPipeline") == ""


# ---------------------------------------------------------------------------
# _fetch_jira — configured, mocked HTTP
# ---------------------------------------------------------------------------

class TestFetchJiraConfigured:
    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("JIRA_URL", "https://example.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "user@example.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "token123")
        monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)

    def _mock_response(self, issues: list) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"issues": issues}
        return resp

    def test_empty_results_returns_empty(self):
        with patch("requests.get", return_value=self._mock_response([])):
            assert _fetch_jira("MyPipeline") == ""

    def test_formats_issues_correctly(self):
        issues = [
            {
                "key": "PROJ-123",
                "fields": {
                    "summary": "Implement sales pipeline",
                    "description": {"type": "doc", "content": [
                        {"type": "paragraph", "content": [{"type": "text", "text": "Load sales data daily."}]}
                    ]},
                },
            }
        ]
        with patch("requests.get", return_value=self._mock_response(issues)):
            result = _fetch_jira("SalesPipeline")
        assert "PROJ-123" in result
        assert "Implement sales pipeline" in result
        assert "Load sales data daily." in result

    def test_includes_jira_issues_header(self):
        issues = [{"key": "X-1", "fields": {"summary": "Test", "description": None}}]
        with patch("requests.get", return_value=self._mock_response(issues)):
            result = _fetch_jira("X")
        assert result.startswith("Jira issues:")

    def test_http_error_returns_empty(self):
        with patch("requests.get", side_effect=Exception("timeout")):
            assert _fetch_jira("MyPipeline") == ""

    def test_project_key_included_in_jql(self, monkeypatch):
        monkeypatch.setenv("JIRA_PROJECT_KEY", "MYPROJ")
        captured = {}

        def mock_get(url, headers, params, timeout):
            captured["jql"] = params["jql"]
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"issues": []}
            return resp

        with patch("requests.get", side_effect=mock_get):
            _fetch_jira("PipelineX")
        assert "project = MYPROJ" in captured["jql"]

    def test_jql_includes_normalized_name_for_prefixed_artifact(self, monkeypatch):
        monkeypatch.delenv("JIRA_PROJECT_KEY", raising=False)
        captured = {}

        def mock_get(url, headers, params, timeout):
            captured["jql"] = params["jql"]
            resp = MagicMock()
            resp.raise_for_status.return_value = None
            resp.json.return_value = {"issues": []}
            return resp

        with patch("requests.get", side_effect=mock_get):
            _fetch_jira("pl_load_customer_data")

        jql = captured["jql"]
        assert "pl_load_customer_data" in jql
        assert "load customer data" in jql


# ---------------------------------------------------------------------------
# _fetch_azdo — not configured
# ---------------------------------------------------------------------------

class TestFetchAzdoNotConfigured:
    def test_returns_empty_when_no_env_vars(self, monkeypatch):
        monkeypatch.delenv("AZDO_ORG", raising=False)
        monkeypatch.delenv("AZDO_PROJECT", raising=False)
        monkeypatch.delenv("AZDO_PAT", raising=False)
        assert _fetch_azdo("MyPipeline") == ""

    def test_returns_empty_when_partial_config(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "myorg")
        monkeypatch.delenv("AZDO_PROJECT", raising=False)
        monkeypatch.delenv("AZDO_PAT", raising=False)
        assert _fetch_azdo("MyPipeline") == ""


# ---------------------------------------------------------------------------
# _fetch_azdo_workitems — mocked HTTP
# ---------------------------------------------------------------------------

class TestFetchAzdoWorkitems:
    _BASE = "https://dev.azure.com/org/proj/_apis"

    def _headers(self) -> dict:
        import base64
        auth = base64.b64encode(b":pat").decode()
        return {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    def test_empty_wiql_result_returns_empty(self):
        wiql_resp = MagicMock()
        wiql_resp.raise_for_status.return_value = None
        wiql_resp.json.return_value = {"workItems": []}

        with patch("requests.post", return_value=wiql_resp):
            result = _fetch_azdo_workitems("NoPipeline", self._BASE, self._headers())
        assert result == ""

    def test_formats_work_items_correctly(self):
        wiql_resp = MagicMock()
        wiql_resp.raise_for_status.return_value = None
        wiql_resp.json.return_value = {"workItems": [{"id": 42}]}

        items_resp = MagicMock()
        items_resp.raise_for_status.return_value = None
        items_resp.json.return_value = {
            "value": [
                {
                    "id": 42,
                    "fields": {
                        "System.Title": "Build SalesPipeline",
                        "System.Description": "<p>Load data from Salesforce</p>",
                    },
                }
            ]
        }

        with patch("requests.post", return_value=wiql_resp), \
             patch("requests.get", return_value=items_resp):
            result = _fetch_azdo_workitems("SalesPipeline", self._BASE, self._headers())

        assert "#42" in result
        assert "Build SalesPipeline" in result
        assert "Load data from Salesforce" in result

    def test_html_stripped_from_description(self):
        wiql_resp = MagicMock()
        wiql_resp.raise_for_status.return_value = None
        wiql_resp.json.return_value = {"workItems": [{"id": 1}]}

        items_resp = MagicMock()
        items_resp.raise_for_status.return_value = None
        items_resp.json.return_value = {
            "value": [{"id": 1, "fields": {
                "System.Title": "T",
                "System.Description": "<b>Bold</b> plain text",
            }}]
        }
        with patch("requests.post", return_value=wiql_resp), \
             patch("requests.get", return_value=items_resp):
            result = _fetch_azdo_workitems("T", self._BASE, self._headers())
        assert "<b>" not in result
        assert "Bold" in result

    def test_http_error_returns_empty(self):
        with patch("requests.post", side_effect=Exception("network error")):
            result = _fetch_azdo_workitems("X", self._BASE, self._headers())
        assert result == ""

    def test_wiql_uses_contains_words_with_normalized_name(self):
        """Prefixed snake_case names should produce an OR with CONTAINS WORDS."""
        captured = {}
        wiql_resp = MagicMock()
        wiql_resp.raise_for_status.return_value = None
        wiql_resp.json.return_value = {"workItems": []}

        def mock_post(url, json, headers, timeout):
            captured["query"] = json["query"]
            return wiql_resp

        with patch("requests.post", side_effect=mock_post):
            _fetch_azdo_workitems("pl_load_customer_data", self._BASE, self._headers())

        query = captured["query"]
        assert "CONTAINS WORDS" in query
        assert "load customer data" in query.lower()

    def test_wiql_no_or_when_name_unchanged_by_normalisation(self):
        """A name that normalises to itself should use a simple CONTAINS."""
        captured = {}
        wiql_resp = MagicMock()
        wiql_resp.raise_for_status.return_value = None
        wiql_resp.json.return_value = {"workItems": []}

        def mock_post(url, json, headers, timeout):
            captured["query"] = json["query"]
            return wiql_resp

        with patch("requests.post", side_effect=mock_post):
            _fetch_azdo_workitems("salesdata", self._BASE, self._headers())

        assert "CONTAINS WORDS" not in captured["query"]
        assert "salesdata" in captured["query"]


# ---------------------------------------------------------------------------
# _fetch_azdo_prs — mocked HTTP
# ---------------------------------------------------------------------------

class TestFetchAzdoPRs:
    _BASE = "https://dev.azure.com/org/proj/_apis"

    def _headers(self) -> dict:
        import base64
        auth = base64.b64encode(b":pat").decode()
        return {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    def test_empty_prs_returns_empty(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"value": []}
        with patch("requests.get", return_value=resp):
            assert _fetch_azdo_prs("X", self._BASE, self._headers()) == ""

    def test_formats_prs_correctly(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {
            "value": [{"pullRequestId": 99, "title": "Add SalesPipeline", "description": "Initial implementation"}]
        }
        with patch("requests.get", return_value=resp):
            result = _fetch_azdo_prs("SalesPipeline", self._BASE, self._headers())
        assert "PR #99" in result
        assert "Add SalesPipeline" in result

    def test_pr_search_uses_normalized_title(self):
        """PR search should use the human-readable name, not the prefixed one."""
        captured = {}
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"value": []}

        def mock_get(url, params, headers, timeout):
            captured["title"] = params.get("searchCriteria.title")
            return resp

        with patch("requests.get", side_effect=mock_get):
            _fetch_azdo_prs("pl_load_customer_data", self._BASE, self._headers())

        assert captured["title"] == "load customer data"

    def test_http_error_returns_empty(self):
        with patch("requests.get", side_effect=Exception("timeout")):
            assert _fetch_azdo_prs("X", self._BASE, self._headers()) == ""


# ---------------------------------------------------------------------------
# fetch_ticket_context — integration
# ---------------------------------------------------------------------------

class TestFetchTicketContext:
    def test_returns_empty_when_nothing_configured(self, monkeypatch):
        for var in ("JIRA_URL", "JIRA_EMAIL", "JIRA_API_TOKEN", "AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT"):
            monkeypatch.delenv(var, raising=False)
        assert fetch_ticket_context("AnyArtifact") == ""

    def test_combines_jira_and_azdo(self, monkeypatch):
        monkeypatch.setenv("JIRA_URL", "https://j.example.com")
        monkeypatch.setenv("JIRA_EMAIL", "u@x.com")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok")
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_PAT", "pat")

        with patch("agent.enrichers.ticket_enricher._fetch_jira", return_value="Jira issues:\n- [J-1] Test") as mj, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo", return_value="Azure DevOps work items:\n- [#1] Test") as ma:
            result = fetch_ticket_context("Artifact")

        assert "Jira issues:" in result
        assert "Azure DevOps work items:" in result
        mj.assert_called_once_with("Artifact")
        ma.assert_called_once_with("Artifact")

    def test_skips_empty_backends(self, monkeypatch):
        for var in ("AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT"):
            monkeypatch.delenv(var, raising=False)

        with patch("agent.enrichers.ticket_enricher._fetch_jira", return_value="Jira issues:\n- [J-1] X"):
            result = fetch_ticket_context("Artifact")

        assert result == "Jira issues:\n- [J-1] X"

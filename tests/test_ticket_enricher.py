"""Tests for agent/enrichers/ticket_enricher.py"""

from unittest.mock import MagicMock, patch

import pytest

from agent.enrichers.ticket_enricher import (
    _SEARCH_CANDIDATES,
    _build_pr_workitem_context,
    _extract_jira_text,
    _fetch_azdo,
    _fetch_azdo_prs,
    _fetch_azdo_workitems,
    _fetch_jira,
    _fetch_pr_linked_workitems,
    _normalize_artifact_name,
    _rerank_work_items,
    _search_azdo_workitems,
    _strip_highlight_tags,
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
# _strip_highlight_tags
# ---------------------------------------------------------------------------

class TestStripHighlightTags:
    def test_removes_open_and_close_tags(self):
        result = _strip_highlight_tags(
            "loads <highlighthit>customer data</highlighthit> from Salesforce"
        )
        assert result == "loads customer data from Salesforce"

    def test_case_insensitive(self):
        assert _strip_highlight_tags("<HIGHLIGHTHIT>text</HIGHLIGHTHIT>") == "text"

    def test_multiple_highlights(self):
        result = _strip_highlight_tags(
            "<highlighthit>load</highlighthit> and <highlighthit>customer</highlighthit>"
        )
        assert result == "load and customer"

    def test_no_tags_unchanged(self):
        assert _strip_highlight_tags("plain text") == "plain text"

    def test_empty_string(self):
        assert _strip_highlight_tags("") == ""


# ---------------------------------------------------------------------------
# _search_azdo_workitems
# ---------------------------------------------------------------------------

class TestSearchAzdoWorkitems:
    _ORG = "org"
    _PROJECT = "proj"

    def _headers(self) -> dict:
        import base64
        auth = base64.b64encode(b":pat").decode()
        return {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    def _make_result(
        self,
        wi_id="42",
        title="Load Customer Data Pipeline",
        wi_type="Task",
        state="Active",
        highlights=None,
        description="",
    ) -> dict:
        result = {
            "fields": {
                "system.id": wi_id,
                "system.title": title,
                "system.workitemtype": wi_type,
                "system.state": state,
                "system.description": description,
            },
            "hits": [],
        }
        if highlights is not None:
            result["hits"] = [
                {"fieldReferenceName": "system.description", "highlights": highlights}
            ]
        return result

    def _mock_post(self, results: list) -> MagicMock:
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"count": len(results), "results": results}
        return resp

    def test_successful_search_returns_formatted_items(self):
        resp = self._mock_post([self._make_result(
            highlights=["loads <highlighthit>customer data</highlighthit> from Salesforce"]
        )])
        with patch("requests.post", return_value=resp):
            result = _search_azdo_workitems(
                "pl_load_customer_data", self._ORG, self._PROJECT, self._headers()
            )
        assert result.startswith("Azure DevOps work items:")
        assert "#42" in result
        assert "Load Customer Data Pipeline" in result
        assert "Task" in result
        assert "Active" in result
        assert "<highlighthit>" not in result
        assert "customer data" in result

    def test_highlight_tags_stripped(self):
        resp = self._mock_post([self._make_result(
            highlights=["<highlighthit>load</highlighthit> data pipeline"]
        )])
        with patch("requests.post", return_value=resp):
            result = _search_azdo_workitems("load data", self._ORG, self._PROJECT, self._headers())
        assert "<highlighthit>" not in result
        assert "load data pipeline" in result

    def test_falls_back_to_description_when_no_hits(self):
        resp = self._mock_post([self._make_result(
            highlights=None,
            description="<p>Loads customer data from the data lake.</p>",
        )])
        with patch("requests.post", return_value=resp):
            result = _search_azdo_workitems(
                "customer data", self._ORG, self._PROJECT, self._headers()
            )
        assert "Loads customer data from the data lake." in result
        assert "<p>" not in result

    def test_empty_results_returns_empty(self):
        resp = self._mock_post([])
        with patch("requests.post", return_value=resp):
            result = _search_azdo_workitems("NoMatch", self._ORG, self._PROJECT, self._headers())
        assert result == ""

    def test_http_error_returns_empty(self):
        with patch("requests.post", side_effect=Exception("503")):
            result = _search_azdo_workitems("Any", self._ORG, self._PROJECT, self._headers())
        assert result == ""

    def test_posts_to_search_host(self):
        captured = {}
        resp = self._mock_post([])

        def mock_post(url, json, headers, timeout):
            captured["url"] = url
            return resp

        with patch("requests.post", side_effect=mock_post):
            _search_azdo_workitems("any", self._ORG, self._PROJECT, self._headers())

        assert "almsearch.dev.azure.com" in captured["url"]
        assert self._ORG in captured["url"]
        assert self._PROJECT in captured["url"]

    def test_sends_normalized_name_as_search_text(self):
        captured = {}
        resp = self._mock_post([])

        def mock_post(url, json, headers, timeout):
            captured["body"] = json
            return resp

        with patch("requests.post", side_effect=mock_post):
            _search_azdo_workitems(
                "pl_load_customer_data", self._ORG, self._PROJECT, self._headers()
            )

        assert captured["body"]["searchText"] == "load customer data"
        assert captured["body"]["$top"] == _SEARCH_CANDIDATES

    def test_top_equals_search_candidates_constant(self):
        assert _SEARCH_CANDIDATES == 10

    def test_includes_type_and_state_in_output(self):
        resp = self._mock_post([self._make_result(wi_type="User Story", state="Resolved")])
        with patch("requests.post", return_value=resp):
            result = _search_azdo_workitems("any", self._ORG, self._PROJECT, self._headers())
        assert "User Story" in result
        assert "Resolved" in result


# ---------------------------------------------------------------------------
# _rerank_work_items
# ---------------------------------------------------------------------------

class TestRerankWorkItems:
    _ITEMS = (
        "Azure DevOps work items:\n"
        "- [#1] Load Customer Data (Task, Active)\n"
        "  Loads customer data from lake.\n"
        "- [#2] Unrelated ticket (Bug, New)\n"
        "  Something completely different."
    )

    def test_returns_original_when_no_client(self):
        assert _rerank_work_items("pl_load_customer_data", self._ITEMS, None) == self._ITEMS

    def test_calls_client_with_artifact_name_and_items(self):
        client = MagicMock()
        client._call.return_value = "- [#1] Load Customer Data (Task, Active)"
        result = _rerank_work_items("pl_load_customer_data", self._ITEMS, client)
        prompt = client._call.call_args[0][0]
        assert "pl_load_customer_data" in prompt
        assert "Azure DevOps work items:" in prompt

    def test_reattaches_header_to_filtered_result(self):
        client = MagicMock()
        client._call.return_value = "- [#1] Load Customer Data (Task, Active)"
        result = _rerank_work_items("artifact", self._ITEMS, client)
        assert result.startswith("Azure DevOps work items:")
        assert "- [#1]" in result

    def test_falls_back_to_original_when_llm_strips_all(self):
        client = MagicMock()
        client._call.return_value = "None of these are relevant."
        result = _rerank_work_items("artifact", self._ITEMS, client)
        assert result == self._ITEMS

    def test_falls_back_to_original_when_llm_returns_empty(self):
        client = MagicMock()
        client._call.return_value = ""
        result = _rerank_work_items("artifact", self._ITEMS, client)
        assert result == self._ITEMS

    def test_falls_back_to_original_on_llm_exception(self):
        client = MagicMock()
        client._call.side_effect = RuntimeError("LLM unavailable")
        result = _rerank_work_items("artifact", self._ITEMS, client)
        assert result == self._ITEMS


# ---------------------------------------------------------------------------
# _fetch_azdo — fallback and re-rank integration
# ---------------------------------------------------------------------------

class TestFetchAzdoFallbackAndRerank:
    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_PAT", "pat")

    def test_falls_back_to_wiql_when_search_returns_empty(self):
        wiql_result = "Azure DevOps work items:\n- [#7] Fallback Item"
        with patch("agent.enrichers.ticket_enricher._search_azdo_workitems", return_value="") as ms, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_workitems", return_value=wiql_result) as mw, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_prs", return_value=""), \
             patch("agent.enrichers.ticket_enricher._rerank_work_items", side_effect=lambda n, t, c: t):
            result = _fetch_azdo("MyPipeline")
        ms.assert_called_once()
        mw.assert_called_once()
        assert "Fallback Item" in result

    def test_wiql_not_called_when_search_succeeds(self):
        search_result = "Azure DevOps work items:\n- [#42] Search Result"
        with patch("agent.enrichers.ticket_enricher._search_azdo_workitems", return_value=search_result) as ms, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_workitems", return_value="should not appear") as mw, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_prs", return_value=""), \
             patch("agent.enrichers.ticket_enricher._rerank_work_items", side_effect=lambda n, t, c: t):
            result = _fetch_azdo("MyPipeline")
        ms.assert_called_once()
        mw.assert_not_called()
        assert "Search Result" in result
        assert "should not appear" not in result

    def test_rerank_called_with_client(self):
        client = MagicMock()
        search_result = "Azure DevOps work items:\n- [#1] Item"
        with patch("agent.enrichers.ticket_enricher._search_azdo_workitems", return_value=search_result), \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_prs", return_value=""), \
             patch("agent.enrichers.ticket_enricher._rerank_work_items", return_value=search_result) as mr:
            _fetch_azdo("MyPipeline", client)
        mr.assert_called_once_with("MyPipeline", search_result, client)

    def test_rerank_not_called_when_no_work_items(self):
        with patch("agent.enrichers.ticket_enricher._search_azdo_workitems", return_value=""), \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_workitems", return_value=""), \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_prs", return_value=""), \
             patch("agent.enrichers.ticket_enricher._rerank_work_items") as mr:
            _fetch_azdo("MyPipeline")
        mr.assert_not_called()


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
# _fetch_azdo_workitems — mocked HTTP (WIQL fallback)
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
# _fetch_pr_linked_workitems
# ---------------------------------------------------------------------------

class TestFetchPrLinkedWorkitems:
    _BASE = "https://dev.azure.com/org/proj/_apis"

    def _headers(self) -> dict:
        import base64
        auth = base64.b64encode(b":pat").decode()
        return {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    def test_returns_list_of_ids(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"value": [{"id": 101}, {"id": 102}]}
        with patch("requests.get", return_value=resp):
            result = _fetch_pr_linked_workitems(42, self._BASE, self._headers())
        assert result == [101, 102]

    def test_empty_value_returns_empty_list(self):
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"value": []}
        with patch("requests.get", return_value=resp):
            assert _fetch_pr_linked_workitems(42, self._BASE, self._headers()) == []

    def test_http_error_returns_empty_list(self):
        with patch("requests.get", side_effect=Exception("network error")):
            assert _fetch_pr_linked_workitems(42, self._BASE, self._headers()) == []

    def test_calls_correct_endpoint(self):
        captured = {}
        resp = MagicMock()
        resp.raise_for_status.return_value = None
        resp.json.return_value = {"value": []}

        def mock_get(url, params, headers, timeout):
            captured["url"] = url
            return resp

        with patch("requests.get", side_effect=mock_get):
            _fetch_pr_linked_workitems(99, self._BASE, self._headers())

        assert "/git/pullrequests/99/workitems" in captured["url"]


# ---------------------------------------------------------------------------
# _build_pr_workitem_context
# ---------------------------------------------------------------------------

class TestBuildPrWorkitemContext:
    _BASE = "https://dev.azure.com/org/proj/_apis"

    def _headers(self) -> dict:
        import base64
        auth = base64.b64encode(b":pat").decode()
        return {"Authorization": f"Basic {auth}", "Content-Type": "application/json"}

    def _pr_resp(self, prs: list) -> MagicMock:
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {"value": prs}
        return m

    def _wi_resp(self, items: list) -> MagicMock:
        m = MagicMock()
        m.raise_for_status.return_value = None
        m.json.return_value = {"value": items}
        return m

    def test_returns_empty_when_no_prs(self):
        with patch("requests.get", return_value=self._pr_resp([])):
            assert _build_pr_workitem_context("MyPipeline", self._BASE, self._headers()) == ""

    def test_returns_empty_when_prs_have_no_linked_workitems(self):
        pr = {"pullRequestId": 1, "title": "My PR", "description": ""}
        wi_empty = MagicMock()
        wi_empty.raise_for_status.return_value = None
        wi_empty.json.return_value = {"value": []}

        def mock_get(url, **kwargs):
            if "workitems" in url and "pullrequests" in url:
                return wi_empty
            return self._pr_resp([pr])

        with patch("requests.get", side_effect=mock_get):
            assert _build_pr_workitem_context("MyPipeline", self._BASE, self._headers()) == ""

    def test_returns_combined_context_when_linked_workitems_found(self):
        pr = {"pullRequestId": 42, "title": "Load customer data", "description": "Implements load"}
        wi_linked = MagicMock()
        wi_linked.raise_for_status.return_value = None
        wi_linked.json.return_value = {"value": [{"id": 101}]}
        wi_details = self._wi_resp([{
            "id": 101,
            "fields": {
                "System.Title": "Daily customer load",
                "System.Description": "Load Salesforce data daily.",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "Must complete by 06:00 UTC.",
            }
        }])

        call_count = {"n": 0}

        def mock_get(url, **kwargs):
            call_count["n"] += 1
            if "pullrequests/42/workitems" in url:
                return wi_linked
            if "wit/workitems" in url:
                return wi_details
            return self._pr_resp([pr])

        with patch("requests.get", side_effect=mock_get):
            result = _build_pr_workitem_context("pl_load_customer_data", self._BASE, self._headers())

        assert result.startswith("Azure DevOps pull requests with linked work items:")
        assert "PR #42" in result
        assert "Load customer data" in result
        assert "Implements load" in result
        assert "#101" in result
        assert "Daily customer load" in result
        assert "Load Salesforce data daily." in result
        assert "Acceptance criteria:" in result
        assert "Must complete by 06:00 UTC." in result

    def test_html_stripped_from_workitem_description(self):
        pr = {"pullRequestId": 1, "title": "PR", "description": ""}
        wi_linked = MagicMock()
        wi_linked.raise_for_status.return_value = None
        wi_linked.json.return_value = {"value": [{"id": 5}]}
        wi_details = self._wi_resp([{
            "id": 5,
            "fields": {
                "System.Title": "Fix",
                "System.Description": "<p>Load <b>customer</b> data.</p>",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            }
        }])

        def mock_get(url, **kwargs):
            if "pullrequests/1/workitems" in url:
                return wi_linked
            if "wit/workitems" in url:
                return wi_details
            return self._pr_resp([pr])

        with patch("requests.get", side_effect=mock_get):
            result = _build_pr_workitem_context("Fix", self._BASE, self._headers())

        assert "<p>" not in result
        assert "<b>" not in result
        assert "customer" in result

    def test_acceptance_criteria_omitted_when_empty(self):
        pr = {"pullRequestId": 1, "title": "PR", "description": ""}
        wi_linked = MagicMock()
        wi_linked.raise_for_status.return_value = None
        wi_linked.json.return_value = {"value": [{"id": 5}]}
        wi_details = self._wi_resp([{
            "id": 5,
            "fields": {
                "System.Title": "Task",
                "System.Description": "Do something.",
                "Microsoft.VSTS.Common.AcceptanceCriteria": "",
            }
        }])

        def mock_get(url, **kwargs):
            if "pullrequests/1/workitems" in url:
                return wi_linked
            if "wit/workitems" in url:
                return wi_details
            return self._pr_resp([pr])

        with patch("requests.get", side_effect=mock_get):
            result = _build_pr_workitem_context("Task", self._BASE, self._headers())

        assert "Acceptance criteria:" not in result

    def test_pr_api_failure_returns_empty(self):
        with patch("requests.get", side_effect=Exception("timeout")):
            assert _build_pr_workitem_context("X", self._BASE, self._headers()) == ""

    def test_wi_details_failure_returns_empty(self):
        pr = {"pullRequestId": 1, "title": "PR", "description": ""}
        wi_linked = MagicMock()
        wi_linked.raise_for_status.return_value = None
        wi_linked.json.return_value = {"value": [{"id": 5}]}

        call_n = {"n": 0}

        def mock_get(url, **kwargs):
            call_n["n"] += 1
            if "pullrequests/1/workitems" in url:
                return wi_linked
            if "wit/workitems" in url:
                raise Exception("API error")
            return self._pr_resp([pr])

        with patch("requests.get", side_effect=mock_get):
            assert _build_pr_workitem_context("X", self._BASE, self._headers()) == ""

    def test_uses_normalized_name_for_pr_search(self):
        captured = {}
        resp_empty = MagicMock()
        resp_empty.raise_for_status.return_value = None
        resp_empty.json.return_value = {"value": []}

        def mock_get(url, params=None, **kwargs):
            if "pullrequests" in url and "workitems" not in url:
                captured["title"] = (params or {}).get("searchCriteria.title")
            return resp_empty

        with patch("requests.get", side_effect=mock_get):
            _build_pr_workitem_context("pl_load_customer_data", self._BASE, self._headers())

        assert captured.get("title") == "load customer data"


# ---------------------------------------------------------------------------
# _fetch_azdo — PR deep-dive takes priority over Search API
# ---------------------------------------------------------------------------

class TestFetchAzdoPrPriority:
    @pytest.fixture(autouse=True)
    def _set_env(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_PAT", "pat")

    def test_returns_pr_wi_context_and_skips_search_when_linked_wis_found(self):
        pr_wi_result = "Azure DevOps pull requests with linked work items:\n- [PR #1] My PR\n  - [#10] Task"

        with patch("agent.enrichers.ticket_enricher._build_pr_workitem_context",
                   return_value=pr_wi_result) as mock_pr_wi, \
             patch("agent.enrichers.ticket_enricher._search_azdo_workitems",
                   return_value="should not appear") as mock_search, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_prs",
                   return_value="should not appear") as mock_prs:
            result = _fetch_azdo("MyPipeline")

        mock_pr_wi.assert_called_once()
        mock_search.assert_not_called()
        mock_prs.assert_not_called()
        assert pr_wi_result == result

    def test_falls_back_to_search_when_no_linked_wis(self):
        with patch("agent.enrichers.ticket_enricher._build_pr_workitem_context",
                   return_value="") as mock_pr_wi, \
             patch("agent.enrichers.ticket_enricher._search_azdo_workitems",
                   return_value="Azure DevOps work items:\n- [#42] Found via search") as mock_search, \
             patch("agent.enrichers.ticket_enricher._fetch_azdo_prs",
                   return_value=""):
            result = _fetch_azdo("MyPipeline")

        mock_pr_wi.assert_called_once()
        mock_search.assert_called_once()
        assert "Found via search" in result


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
        ma.assert_called_once_with("Artifact", None)

    def test_passes_client_to_fetch_azdo(self, monkeypatch):
        monkeypatch.setenv("AZDO_ORG", "org")
        monkeypatch.setenv("AZDO_PROJECT", "proj")
        monkeypatch.setenv("AZDO_PAT", "pat")
        client = MagicMock()

        with patch("agent.enrichers.ticket_enricher._fetch_jira", return_value=""), \
             patch("agent.enrichers.ticket_enricher._fetch_azdo", return_value="") as ma:
            fetch_ticket_context("Artifact", client)

        ma.assert_called_once_with("Artifact", client)

    def test_skips_empty_backends(self, monkeypatch):
        for var in ("AZDO_ORG", "AZDO_PROJECT", "AZDO_PAT"):
            monkeypatch.delenv(var, raising=False)

        with patch("agent.enrichers.ticket_enricher._fetch_jira", return_value="Jira issues:\n- [J-1] X"):
            result = fetch_ticket_context("Artifact")

        assert result == "Jira issues:\n- [J-1] X"

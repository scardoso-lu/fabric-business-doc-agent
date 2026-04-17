"""Tests for doc_generator content builders and full document generation."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.generators.doc_generator import (
    _depends_on_text,
    _meta_block,
    _notebook_contents,
    _pipeline_contents,
    _resolve_notebook,
    generate_notebook_doc,
    generate_pipeline_doc,
    get_linked_notebooks,
)
from agent.parsers.pipeline_parser import ActivityDependency
from tests.conftest import (
    make_activity,
    make_notebook,
    make_notebook_section,
    make_pipeline,
)


# ---------------------------------------------------------------------------
# _meta_block
# ---------------------------------------------------------------------------

class TestMetaBlock:
    def test_contains_doc_type(self):
        result = _meta_block("Pipeline", Path("sales.json"))
        assert "Pipeline" in result

    def test_contains_source_filename(self):
        result = _meta_block("Pipeline", Path("sales_pipeline.json"))
        assert "sales_pipeline.json" in result

    def test_contains_generated_date(self):
        result = _meta_block("Data Process", Path("nb.ipynb"))
        import re
        assert re.search(r"\d{4}-\d{2}-\d{2}", result)

    def test_is_markdown_table(self):
        result = _meta_block("Pipeline", Path("p.json"))
        assert "| **Type** |" in result


# ---------------------------------------------------------------------------
# _depends_on_text
# ---------------------------------------------------------------------------

class TestDependsOnText:
    def test_empty_returns_empty_string(self):
        activity = make_activity(depends_on=[])
        assert _depends_on_text(activity) == ""

    def test_succeeded_condition(self):
        dep = ActivityDependency(activity_name="LoadData", conditions=["Succeeded"])
        activity = make_activity(depends_on=[dep])
        result = _depends_on_text(activity)
        assert "LoadData" in result
        assert "succeeded" in result.lower()

    def test_failed_condition(self):
        dep = ActivityDependency(activity_name="CheckData", conditions=["Failed"])
        activity = make_activity(depends_on=[dep])
        result = _depends_on_text(activity)
        assert "failed" in result.lower()

    def test_completed_condition(self):
        dep = ActivityDependency(activity_name="StepA", conditions=["Completed"])
        activity = make_activity(depends_on=[dep])
        result = _depends_on_text(activity)
        assert "regardless" in result.lower()

    def test_multiple_dependencies(self):
        deps = [
            ActivityDependency("StepA", ["Succeeded"]),
            ActivityDependency("StepB", ["Succeeded"]),
        ]
        activity = make_activity(depends_on=deps)
        result = _depends_on_text(activity)
        assert "StepA" in result
        assert "StepB" in result


# ---------------------------------------------------------------------------
# _resolve_notebook
# ---------------------------------------------------------------------------

class TestResolveNotebook:
    def test_resolves_by_notebook_id(self):
        nb = make_notebook(name="transform")
        activity = make_activity(
            activity_type="TridentNotebook",
            type_properties={"notebookId": "transform"},
        )
        assert _resolve_notebook(activity, {"transform": nb}) is nb

    def test_resolves_case_insensitive(self):
        nb = make_notebook(name="Transform")
        activity = make_activity(
            activity_type="TridentNotebook",
            type_properties={"notebookId": "transform"},
        )
        assert _resolve_notebook(activity, {"Transform": nb}) is nb

    def test_resolves_by_activity_name_fallback(self):
        nb = make_notebook(name="CleanData")
        activity = make_activity(
            name="CleanData",
            activity_type="TridentNotebook",
            type_properties={},
        )
        assert _resolve_notebook(activity, {"CleanData": nb}) is nb

    def test_non_notebook_activity_returns_none(self):
        activity = make_activity(activity_type="Copy")
        assert _resolve_notebook(activity, {"anything": make_notebook()}) is None

    def test_missing_notebook_returns_none(self):
        activity = make_activity(
            activity_type="TridentNotebook",
            type_properties={"notebookId": "missing"},
        )
        assert _resolve_notebook(activity, {}) is None


# ---------------------------------------------------------------------------
# get_linked_notebooks
# ---------------------------------------------------------------------------

class TestGetLinkedNotebooks:
    def test_finds_linked_notebook(self):
        nb = make_notebook(name="transform")
        activity = make_activity(
            activity_type="TridentNotebook",
            type_properties={"notebookId": "transform"},
        )
        pipeline = make_pipeline(activities=[activity])
        linked = get_linked_notebooks(pipeline, {"transform": nb})
        assert "transform" in linked

    def test_no_linked_notebooks(self):
        activity = make_activity(activity_type="Copy")
        pipeline = make_pipeline(activities=[activity])
        linked = get_linked_notebooks(pipeline, {})
        assert len(linked) == 0

    def test_multiple_linked_notebooks(self):
        nb1 = make_notebook(name="load")
        nb2 = make_notebook(name="clean")
        activities = [
            make_activity("A", "TridentNotebook", type_properties={"notebookId": "load"}),
            make_activity("B", "TridentNotebook", type_properties={"notebookId": "clean"}),
        ]
        pipeline = make_pipeline(activities=activities)
        linked = get_linked_notebooks(pipeline, {"load": nb1, "clean": nb2})
        assert "load" in linked
        assert "clean" in linked


# ---------------------------------------------------------------------------
# _pipeline_contents
# ---------------------------------------------------------------------------

class TestPipelineContents:
    def test_returns_all_section_keys(self):
        pipeline = make_pipeline(activities=[make_activity()])
        contents = _pipeline_contents(pipeline, {})
        assert set(contents.keys()) == {"purpose", "what", "relationships", "goal", "quality"}

    def test_pipeline_name_in_all_sections(self):
        pipeline = make_pipeline(name="SalesPipeline")
        contents = _pipeline_contents(pipeline, {})
        for key, value in contents.items():
            assert "SalesPipeline" in value, f"Pipeline name missing from '{key}' section"

    def test_linked_notebook_appears_in_what(self):
        nb = make_notebook(name="TransformData")
        activity = make_activity(
            activity_type="TridentNotebook",
            type_properties={"notebookId": "TransformData"},
        )
        pipeline = make_pipeline(activities=[activity])
        contents = _pipeline_contents(pipeline, {"TransformData": nb})
        assert "TransformData" in contents["what"]

    def test_external_source_appears_in_relationships(self):
        activity = make_activity(
            name="FetchFromAPI",
            activity_type="Web",
            type_properties={"url": "https://api.example.com"},
        )
        pipeline = make_pipeline(activities=[activity])
        contents = _pipeline_contents(pipeline, {})
        assert "FetchFromAPI" in contents["relationships"]

    def test_quality_contains_control_activities(self):
        activity = make_activity(name="CheckResult", activity_type="IfCondition")
        pipeline = make_pipeline(activities=[activity])
        contents = _pipeline_contents(pipeline, {})
        assert "CheckResult" in contents["quality"]


# ---------------------------------------------------------------------------
# _notebook_contents
# ---------------------------------------------------------------------------

class TestNotebookContents:
    def test_returns_all_section_keys(self):
        nb = make_notebook()
        contents = _notebook_contents(nb)
        assert set(contents.keys()) == {"purpose", "what", "relationships", "goal", "quality"}

    def test_notebook_name_in_all_sections(self):
        nb = make_notebook(name="RevenueCalc")
        contents = _notebook_contents(nb)
        for key, value in contents.items():
            assert "RevenueCalc" in value, f"Notebook name missing from '{key}' section"

    def test_section_headings_appear(self):
        sections = [make_notebook_section("Load"), make_notebook_section("Transform")]
        nb = make_notebook(sections=sections)
        contents = _notebook_contents(nb)
        assert "Load" in contents["purpose"]
        assert "Transform" in contents["purpose"]


# ---------------------------------------------------------------------------
# Full document generation (mocked client)
# ---------------------------------------------------------------------------

def _make_mock_client():
    client = MagicMock()
    client.section_purpose.return_value = "This process loads sales data."
    client.section_what_it_does.return_value = "It copies files from the feed."
    client.section_flow.return_value = (
        "Data flows from the external feed to the storage area.\n\n"
        "```mermaid\nflowchart LR\n    Feed --> Pipeline --> Storage\n```"
    )
    client.section_business_goal.return_value = "Enables daily reporting."
    client.section_data_quality.return_value = "Fails if source is unavailable."
    return client


class TestGeneratePipelineDoc:
    def test_contains_pipeline_name_heading(self):
        client = _make_mock_client()
        pipeline = make_pipeline(name="SalesPipeline")
        result = generate_pipeline_doc(pipeline, {}, client)
        assert "# SalesPipeline" in result

    def test_contains_all_sections(self):
        client = _make_mock_client()
        result = generate_pipeline_doc(make_pipeline(), {}, client)
        for heading in ("## Purpose", "## What It Does", "## Flow", "## Business Goal", "## Data Quality & Alerts"):
            assert heading in result

    def test_contains_llm_responses(self):
        client = _make_mock_client()
        result = generate_pipeline_doc(make_pipeline(), {}, client)
        assert "This process loads sales data." in result
        assert "Enables daily reporting." in result

    def test_mermaid_diagram_preserved(self):
        client = _make_mock_client()
        result = generate_pipeline_doc(make_pipeline(), {}, client)
        assert "```mermaid" in result
        assert "flowchart LR" in result

    def test_calls_each_section_method_once(self):
        client = _make_mock_client()
        generate_pipeline_doc(make_pipeline(), {}, client)
        client.section_purpose.assert_called_once()
        client.section_what_it_does.assert_called_once()
        client.section_flow.assert_called_once()
        client.section_business_goal.assert_called_once()
        client.section_data_quality.assert_called_once()

    def test_contains_footer(self):
        client = _make_mock_client()
        result = generate_pipeline_doc(make_pipeline(name="P", path=Path("P.json")), {}, client)
        assert "P.json" in result


class TestGenerateNotebookDoc:
    def test_contains_notebook_name_heading(self):
        client = _make_mock_client()
        nb = make_notebook(name="RevenueCalc")
        result = generate_notebook_doc(nb, client)
        assert "# RevenueCalc" in result

    def test_contains_all_sections(self):
        client = _make_mock_client()
        result = generate_notebook_doc(make_notebook(), client)
        for heading in ("## Purpose", "## What It Does", "## Flow", "## Business Goal", "## Data Quality & Alerts"):
            assert heading in result

    def test_calls_each_section_method_once(self):
        client = _make_mock_client()
        generate_notebook_doc(make_notebook(), client)
        client.section_purpose.assert_called_once()
        client.section_flow.assert_called_once()

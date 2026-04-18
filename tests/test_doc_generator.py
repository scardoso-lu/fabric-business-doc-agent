"""Tests for doc_generator content builders and full document generation."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent.generators.doc_generator import (
    _dataflow_contents,
    _depends_on_text,
    _lineage_content,
    _lineage_content_dataflow,
    _lineage_content_notebook,
    _meta_block,
    _notebook_contents,
    _pipeline_contents,
    _resolve_dataflow,
    _resolve_notebook,
    generate_dataflow_doc,
    generate_notebook_doc,
    generate_pipeline_doc,
    get_linked_dataflows,
    get_linked_notebooks,
)
from agent.parsers.pipeline_parser import ActivityDependency
from tests.conftest import (
    make_activity,
    make_dataflow,
    make_dataflow_query,
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
        assert set(contents.keys()) == {"purpose", "relationships", "goal", "quality"}

    def test_pipeline_name_in_all_sections(self):
        pipeline = make_pipeline(name="SalesPipeline")
        contents = _pipeline_contents(pipeline, {})
        for key, value in contents.items():
            assert "SalesPipeline" in value, f"Pipeline name missing from '{key}' section"

    def test_linked_notebook_appears_in_relationships(self):
        nb = make_notebook(name="TransformData")
        activity = make_activity(
            activity_type="TridentNotebook",
            type_properties={"notebookId": "TransformData"},
        )
        pipeline = make_pipeline(activities=[activity])
        contents = _pipeline_contents(pipeline, {"TransformData": nb})
        assert "TransformData" in contents["relationships"]

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
        assert set(contents.keys()) == {"purpose", "relationships", "goal", "quality"}

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
# _lineage_content / _lineage_content_notebook
# ---------------------------------------------------------------------------

class TestLineageContent:
    def test_pipeline_includes_notebook_code(self):
        nb = make_notebook(name="Transform", sections=[make_notebook_section("Load", code="df = spark.read.delta(...)")])
        activity = make_activity(activity_type="TridentNotebook", type_properties={"notebookId": "Transform"})
        pipeline = make_pipeline(activities=[activity])
        result = _lineage_content(pipeline, {"Transform": nb})
        assert "df = spark.read.delta(...)" in result

    def test_pipeline_without_notebooks_includes_activity_descriptions(self):
        activity = make_activity(name="CopyFiles", activity_type="Copy", description="Copies raw files")
        pipeline = make_pipeline(activities=[activity])
        result = _lineage_content(pipeline, {})
        assert "Copies raw files" in result

    def test_pipeline_name_always_present(self):
        pipeline = make_pipeline(name="MySalesPipeline")
        result = _lineage_content(pipeline, {})
        assert "MySalesPipeline" in result

    def test_notebook_lineage_includes_all_code(self):
        sections = [
            make_notebook_section("Load", code="raw = spark.read.csv(...)"),
            make_notebook_section("Transform", code="gold = raw.withColumn('revenue', col('price') * col('qty'))"),
        ]
        nb = make_notebook(name="ETL", sections=sections)
        result = _lineage_content_notebook(nb)
        assert "raw = spark.read.csv(...)" in result
        assert "col('revenue')" in result or "revenue" in result

    def test_notebook_lineage_includes_name(self):
        nb = make_notebook(name="GoldTransform")
        result = _lineage_content_notebook(nb)
        assert "GoldTransform" in result


# ---------------------------------------------------------------------------
# Full document generation (mocked client)
# ---------------------------------------------------------------------------

def _make_mock_client():
    client = MagicMock()
    client.section_purpose.return_value = "This process loads sales data."
    client.section_flow.return_value = (
        "Data flows from the external feed to the storage area.\n\n"
        "```mermaid\nflowchart LR\n    Feed --> Pipeline --> Storage\n```"
    )
    client.section_business_goal.return_value = "Enables daily reporting."
    client.section_data_quality.return_value = "Fails if source is unavailable."
    client.section_column_lineage.return_value = "No column lineage detected in this artifact."
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
        for heading in ("## Purpose", "## Flow", "## Business Goal", "## Data Quality & Alerts", "## Column Lineage"):
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
        client.section_flow.assert_called_once()
        client.section_business_goal.assert_called_once()
        client.section_data_quality.assert_called_once()
        client.section_column_lineage.assert_called_once()

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
        for heading in ("## Purpose", "## Flow", "## Business Goal", "## Data Quality & Alerts", "## Column Lineage"):
            assert heading in result

    def test_calls_each_section_method_once(self):
        client = _make_mock_client()
        generate_notebook_doc(make_notebook(), client)
        client.section_purpose.assert_called_once()
        client.section_flow.assert_called_once()
        client.section_column_lineage.assert_called_once()


# ---------------------------------------------------------------------------
# _resolve_dataflow
# ---------------------------------------------------------------------------

class TestResolveDataflow:
    def test_resolves_by_dataflow_id(self):
        df = make_dataflow(name="SalesDF")
        activity = make_activity(
            activity_type="ExecuteDataflow",
            type_properties={"dataflowId": "SalesDF"},
        )
        assert _resolve_dataflow(activity, {"SalesDF": df}) is df

    def test_resolves_case_insensitive(self):
        df = make_dataflow(name="SalesDF")
        activity = make_activity(
            activity_type="ExecuteDataflow",
            type_properties={"dataflowId": "salesdf"},
        )
        assert _resolve_dataflow(activity, {"SalesDF": df}) is df

    def test_resolves_by_reference_name(self):
        df = make_dataflow(name="PopulationDF")
        activity = make_activity(
            activity_type="Dataflow",
            type_properties={"dataflow": {"referenceName": "PopulationDF"}},
        )
        assert _resolve_dataflow(activity, {"PopulationDF": df}) is df

    def test_resolves_by_activity_name_fallback(self):
        df = make_dataflow(name="SalesDF")
        activity = make_activity(name="SalesDF", activity_type="ExecuteDataflow", type_properties={})
        assert _resolve_dataflow(activity, {"SalesDF": df}) is df

    def test_non_dataflow_activity_returns_none(self):
        activity = make_activity(activity_type="Copy")
        assert _resolve_dataflow(activity, {"DF": make_dataflow()}) is None

    def test_missing_dataflow_returns_none(self):
        activity = make_activity(
            activity_type="ExecuteDataflow",
            type_properties={"dataflowId": "missing"},
        )
        assert _resolve_dataflow(activity, {}) is None


# ---------------------------------------------------------------------------
# get_linked_dataflows
# ---------------------------------------------------------------------------

class TestGetLinkedDataflows:
    def test_finds_linked_dataflow(self):
        df = make_dataflow(name="SalesDF")
        activity = make_activity(
            activity_type="ExecuteDataflow",
            type_properties={"dataflowId": "SalesDF"},
        )
        pipeline = make_pipeline(activities=[activity])
        linked = get_linked_dataflows(pipeline, {"SalesDF": df})
        assert "SalesDF" in linked

    def test_no_dataflow_activities(self):
        pipeline = make_pipeline(activities=[make_activity(activity_type="Copy")])
        assert len(get_linked_dataflows(pipeline, {})) == 0

    def test_multiple_linked_dataflows(self):
        df1 = make_dataflow(name="DF1")
        df2 = make_dataflow(name="DF2")
        activities = [
            make_activity("A", "ExecuteDataflow", type_properties={"dataflowId": "DF1"}),
            make_activity("B", "ExecuteDataflow", type_properties={"dataflowId": "DF2"}),
        ]
        pipeline = make_pipeline(activities=activities)
        linked = get_linked_dataflows(pipeline, {"DF1": df1, "DF2": df2})
        assert "DF1" in linked
        assert "DF2" in linked


# ---------------------------------------------------------------------------
# _dataflow_contents
# ---------------------------------------------------------------------------

class TestDataflowContents:
    def test_returns_all_section_keys(self):
        df = make_dataflow()
        contents = _dataflow_contents(df)
        assert set(contents.keys()) == {"purpose", "relationships", "goal", "quality"}

    def test_dataflow_name_in_all_sections(self):
        df = make_dataflow(name="SalesTransform")
        contents = _dataflow_contents(df)
        for key, value in contents.items():
            assert "SalesTransform" in value, f"Dataflow name missing from '{key}' section"

    def test_mcode_preamble_present(self):
        df = make_dataflow()
        contents = _dataflow_contents(df)
        assert "Power Query" in contents["purpose"]

    def test_quality_section_has_filter_hint(self):
        df = make_dataflow()
        contents = _dataflow_contents(df)
        assert "filter" in contents["quality"].lower() or "null" in contents["quality"].lower()


# ---------------------------------------------------------------------------
# _lineage_content_dataflow
# ---------------------------------------------------------------------------

class TestLineageContentDataflow:
    def test_includes_mcode(self):
        pq = "let\n    Source = Csv.Document(File.Contents(\"data.csv\"))\nin\n    Source"
        query = make_dataflow_query(name="RawData", pq_code=pq)
        df = make_dataflow(name="MyDF", queries=[query])
        result = _lineage_content_dataflow(df)
        assert "Csv.Document" in result

    def test_includes_dataflow_name(self):
        df = make_dataflow(name="PopulationDF")
        result = _lineage_content_dataflow(df)
        assert "PopulationDF" in result

    def test_includes_preamble(self):
        df = make_dataflow()
        result = _lineage_content_dataflow(df)
        assert "Power Query" in result


# ---------------------------------------------------------------------------
# _pipeline_contents — with dataflow_map
# ---------------------------------------------------------------------------

class TestPipelineContentsWithDataflow:
    def test_dataflow_queries_appear_in_relationships(self):
        query = make_dataflow_query(name="GoldQuery")
        df = make_dataflow(name="SalesDF", queries=[query])
        activity = make_activity(
            name="RunSalesDF",
            activity_type="ExecuteDataflow",
            type_properties={"dataflowId": "SalesDF"},
        )
        pipeline = make_pipeline(activities=[activity])
        contents = _pipeline_contents(pipeline, {}, {"SalesDF": df})
        assert "SalesDF" in contents["relationships"]

    def test_no_dataflow_map_still_works(self):
        pipeline = make_pipeline(activities=[make_activity()])
        contents = _pipeline_contents(pipeline, {})
        assert set(contents.keys()) == {"purpose", "relationships", "goal", "quality"}


# ---------------------------------------------------------------------------
# generate_dataflow_doc (mocked client)
# ---------------------------------------------------------------------------

class TestGenerateDataflowDoc:
    def test_contains_dataflow_name_heading(self):
        client = _make_mock_client()
        df = make_dataflow(name="SalesTransform")
        result = generate_dataflow_doc(df, client)
        assert "# SalesTransform" in result

    def test_contains_all_sections(self):
        client = _make_mock_client()
        result = generate_dataflow_doc(make_dataflow(), client)
        for heading in ("## Purpose", "## Flow", "## Business Goal", "## Data Quality & Alerts", "## Column Lineage"):
            assert heading in result

    def test_meta_block_shows_dataflow_type(self):
        client = _make_mock_client()
        result = generate_dataflow_doc(make_dataflow(), client)
        assert "Dataflow Gen2" in result

    def test_calls_each_section_method_once(self):
        client = _make_mock_client()
        generate_dataflow_doc(make_dataflow(), client)
        client.section_purpose.assert_called_once()
        client.section_flow.assert_called_once()
        client.section_business_goal.assert_called_once()
        client.section_data_quality.assert_called_once()
        client.section_column_lineage.assert_called_once()

    def test_contains_footer_with_source_filename(self):
        client = _make_mock_client()
        df = make_dataflow(name="DF", path=Path("my_flow.json"))
        result = generate_dataflow_doc(df, client)
        assert "my_flow.json" in result

"""Tests for pipeline and notebook parsers."""

import json
import pytest
from pathlib import Path

from agent.parsers.pipeline_parser import (
    parse_pipeline_file,
    find_pipeline_files,
    ActivityDependency,
)
from agent.parsers.notebook_parser import (
    parse_notebook_file,
    find_notebook_files,
    _extract_heading,
    _cell_source,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

PIPELINE_WITH_PROPERTIES = {
    "name": "SalesPipeline",
    "properties": {
        "description": "Loads and transforms sales data",
        "activities": [
            {
                "name": "CopyFiles",
                "type": "Copy",
                "dependsOn": [],
                "typeProperties": {"source": "blob", "sink": "lakehouse"},
            },
            {
                "name": "RunTransform",
                "type": "TridentNotebook",
                "dependsOn": [
                    {"activity": "CopyFiles", "dependencyConditions": ["Succeeded"]}
                ],
                "typeProperties": {"notebookId": "transform_nb"},
            },
        ],
        "parameters": {
            "env": {"type": "string", "defaultValue": "prod"},
        },
    },
}

PIPELINE_BARE = {
    "activities": [
        {"name": "Load", "type": "Copy", "dependsOn": [], "typeProperties": {}},
    ]
}

NOTEBOOK = {
    "cells": [
        {"cell_type": "markdown", "source": "# Sales Transform\nThis notebook transforms sales data."},
        {"cell_type": "markdown", "source": "## Load Data"},
        {"cell_type": "code", "source": "df = spark.read.parquet('/data/sales')"},
        {"cell_type": "markdown", "source": "## Clean"},
        {"cell_type": "code", "source": "df = df.dropna()"},
    ],
    "metadata": {"kernelspec": {"language": "python"}},
}


# ---------------------------------------------------------------------------
# Pipeline parser
# ---------------------------------------------------------------------------

class TestParsePipelineFile:
    def test_parses_name(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        assert pipeline.name == "SalesPipeline"

    def test_parses_description(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        assert parse_pipeline_file(p).description == "Loads and transforms sales data"

    def test_parses_activities(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        assert len(pipeline.activities) == 2
        names = [a.name for a in pipeline.activities]
        assert "CopyFiles" in names
        assert "RunTransform" in names

    def test_parses_activity_types(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        copy = pipeline.activity_by_name("CopyFiles")
        assert copy.activity_type == "Copy"

    def test_parses_activity_type_properties(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        copy = pipeline.activity_by_name("CopyFiles")
        assert copy.type_properties["source"] == "blob"

    def test_parses_dependency(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        nb = pipeline.activity_by_name("RunTransform")
        assert len(nb.depends_on) == 1
        assert nb.depends_on[0].activity_name == "CopyFiles"
        assert nb.depends_on[0].conditions == ["Succeeded"]

    def test_parses_parameters(self, tmp_path):
        p = _write(tmp_path, "pipeline.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        assert len(pipeline.parameters) == 1
        assert pipeline.parameters[0].name == "env"
        assert pipeline.parameters[0].default_value == "prod"

    def test_accepts_bare_format(self, tmp_path):
        p = _write(tmp_path, "bare.json", PIPELINE_BARE)
        pipeline = parse_pipeline_file(p)
        assert pipeline is not None
        assert len(pipeline.activities) == 1

    def test_returns_none_for_non_pipeline_json(self, tmp_path):
        p = _write(tmp_path, "other.json", {"name": "not_a_pipeline", "value": 42})
        assert parse_pipeline_file(p) is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not valid json", encoding="utf-8")
        assert parse_pipeline_file(p) is None

    def test_stem_used_as_name_when_missing(self, tmp_path):
        data = {"activities": [{"name": "A", "type": "Copy", "dependsOn": [], "typeProperties": {}}]}
        p = _write(tmp_path, "my_pipeline.json", data)
        pipeline = parse_pipeline_file(p)
        assert pipeline.name == "my_pipeline"


class TestOrderedActivities:
    def test_root_activities_first(self, tmp_path):
        p = _write(tmp_path, "p.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        ordered = pipeline.ordered_activities()
        names = [a.name for a in ordered]
        assert names.index("CopyFiles") < names.index("RunTransform")

    def test_root_activities(self, tmp_path):
        p = _write(tmp_path, "p.json", PIPELINE_WITH_PROPERTIES)
        pipeline = parse_pipeline_file(p)
        roots = pipeline.root_activities()
        assert len(roots) == 1
        assert roots[0].name == "CopyFiles"


class TestFindPipelineFiles:
    def test_finds_json_pipelines(self, tmp_path):
        _write(tmp_path, "p1.json", PIPELINE_WITH_PROPERTIES)
        _write(tmp_path, "p2.json", PIPELINE_BARE)
        _write(tmp_path, "not_pipeline.json", {"key": "value"})
        results = find_pipeline_files(tmp_path)
        assert len(results) == 2

    def test_excludes_git_directory(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        _write(git_dir, "pipeline.json", PIPELINE_BARE)
        results = find_pipeline_files(tmp_path)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# Notebook parser
# ---------------------------------------------------------------------------

class TestParseNotebookFile:
    def test_parses_name_from_stem(self, tmp_path):
        p = _write(tmp_path, "sales_transform.ipynb", NOTEBOOK)
        nb = parse_notebook_file(p)
        assert nb.name == "sales_transform"

    def test_parses_language(self, tmp_path):
        p = _write(tmp_path, "nb.ipynb", NOTEBOOK)
        assert parse_notebook_file(p).language == "python"

    def test_extracts_description_from_first_markdown(self, tmp_path):
        p = _write(tmp_path, "nb.ipynb", NOTEBOOK)
        nb = parse_notebook_file(p)
        assert "Sales Transform" in nb.description or "sales data" in nb.description

    def test_groups_cells_into_sections(self, tmp_path):
        p = _write(tmp_path, "nb.ipynb", NOTEBOOK)
        nb = parse_notebook_file(p)
        headings = [s.heading for s in nb.sections]
        assert "Load Data" in headings
        assert "Clean" in headings

    def test_all_code_combines_code_cells(self, tmp_path):
        p = _write(tmp_path, "nb.ipynb", NOTEBOOK)
        nb = parse_notebook_file(p)
        assert "spark.read.parquet" in nb.all_code
        assert "dropna" in nb.all_code

    def test_returns_none_without_cells_key(self, tmp_path):
        p = _write(tmp_path, "bad.ipynb", {"metadata": {}})
        assert parse_notebook_file(p) is None

    def test_returns_none_for_invalid_json(self, tmp_path):
        p = tmp_path / "bad.ipynb"
        p.write_text("not json", encoding="utf-8")
        assert parse_notebook_file(p) is None

    def test_notebook_with_no_headings_has_overview_section(self, tmp_path):
        data = {
            "cells": [{"cell_type": "code", "source": "x = 1"}],
            "metadata": {},
        }
        p = _write(tmp_path, "flat.ipynb", data)
        nb = parse_notebook_file(p)
        assert len(nb.sections) == 1
        assert nb.sections[0].heading == "Overview"


class TestHelpers:
    def test_extract_heading_h2(self):
        assert _extract_heading("## Load Data\nsome text") == "Load Data"

    def test_extract_heading_h1(self):
        assert _extract_heading("# Title") == "Title"

    def test_extract_heading_none(self):
        assert _extract_heading("no heading here") is None

    def test_extract_heading_h3(self):
        assert _extract_heading("### Sub Section") == "Sub Section"

    def test_cell_source_list(self):
        assert _cell_source({"source": ["line1\n", "line2"]}) == "line1\nline2"

    def test_cell_source_string(self):
        assert _cell_source({"source": "plain string"}) == "plain string"

    def test_cell_source_missing(self):
        assert _cell_source({}) == ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p

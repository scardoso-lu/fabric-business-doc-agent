"""Tests for the Dataflow Gen2 parser."""

import json
import textwrap
from pathlib import Path

import pytest

from agent.parsers.dataflow_parser import (
    ParsedDataflow,
    DataflowQuery,
    find_dataflow_files,
    parse_dataflow_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_json(tmp_path: Path, name: str, data: dict) -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# parse_dataflow_file — nested format (properties.definition.queries)
# ---------------------------------------------------------------------------

class TestParseNestedFormat:
    def test_returns_parsed_dataflow(self, tmp_path):
        path = _write_json(tmp_path, "sales.json", {
            "name": "Sales Dataflow",
            "properties": {
                "definition": {
                    "queries": [
                        {"name": "RawSales", "pq": "let\n    Source = 1\nin\n    Source"}
                    ]
                }
            }
        })
        df = parse_dataflow_file(path)
        assert df is not None
        assert df.name == "Sales Dataflow"

    def test_query_names_parsed(self, tmp_path):
        path = _write_json(tmp_path, "df.json", {
            "name": "DF",
            "properties": {"definition": {"queries": [
                {"name": "Q1", "pq": "let\n    x = 1\nin\n    x"},
                {"name": "Q2", "pq": "let\n    y = 2\nin\n    y"},
            ]}}
        })
        df = parse_dataflow_file(path)
        assert df.query_names == ["Q1", "Q2"]

    def test_pq_code_stored(self, tmp_path):
        pq = "let\n    Source = Sql.Database(\"srv\", \"db\")\nin\n    Source"
        path = _write_json(tmp_path, "df.json", {
            "name": "DF",
            "properties": {"definition": {"queries": [{"name": "Q", "pq": pq}]}}
        })
        df = parse_dataflow_file(path)
        assert df.queries[0].pq_code == pq

    def test_description_extracted(self, tmp_path):
        path = _write_json(tmp_path, "df.json", {
            "name": "DF",
            "description": "Top-level description",
            "properties": {"definition": {"queries": [{"name": "Q", "pq": "let\n x=1\nin\n x"}]}}
        })
        df = parse_dataflow_file(path)
        assert df.description == "Top-level description"

    def test_query_description_extracted(self, tmp_path):
        path = _write_json(tmp_path, "df.json", {
            "name": "DF",
            "properties": {"definition": {"queries": [
                {"name": "Q", "pq": "let\n x=1\nin\n x", "description": "Bronze layer"}
            ]}}
        })
        df = parse_dataflow_file(path)
        assert df.queries[0].description == "Bronze layer"


# ---------------------------------------------------------------------------
# parse_dataflow_file — flat format (top-level queries)
# ---------------------------------------------------------------------------

class TestParseFlatFormat:
    def test_flat_queries_parsed(self, tmp_path):
        path = _write_json(tmp_path, "df.json", {
            "name": "FlatDF",
            "queries": [{"name": "Q1", "pq": "let\n x=1\nin\n x"}]
        })
        df = parse_dataflow_file(path)
        assert df is not None
        assert df.query_names == ["Q1"]

    def test_name_falls_back_to_stem(self, tmp_path):
        path = _write_json(tmp_path, "my_flow.json", {
            "queries": [{"name": "Q", "pq": "let\n x=1\nin\n x"}]
        })
        df = parse_dataflow_file(path)
        assert df.name == "my_flow"


# ---------------------------------------------------------------------------
# parse_dataflow_file — mashup format
# ---------------------------------------------------------------------------

class TestParseMashupFormat:
    def test_shared_query_extracted(self, tmp_path):
        mashup = textwrap.dedent("""\
            section Section1;
            shared SalesData = let
                Source = Csv.Document(File.Contents("data.csv")),
                Promoted = Table.PromoteHeaders(Source)
            in
                Promoted;
        """)
        path = _write_json(tmp_path, "df.json", {"name": "MashupDF", "mashup": mashup})
        df = parse_dataflow_file(path)
        assert df is not None
        assert any(q.name == "SalesData" for q in df.queries)

    def test_multiple_shared_queries(self, tmp_path):
        mashup = (
            'section Section1;\n'
            'shared QueryA = let\n    x = 1\nin\n    x;\n'
            'shared QueryB = let\n    y = 2\nin\n    y;\n'
        )
        path = _write_json(tmp_path, "df.json", {"name": "MDF", "mashup": mashup})
        df = parse_dataflow_file(path)
        assert df is not None
        assert len(df.queries) == 2


# ---------------------------------------------------------------------------
# parse_dataflow_file — rejection cases
# ---------------------------------------------------------------------------

class TestParseRejection:
    def test_returns_none_for_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("not json", encoding="utf-8")
        assert parse_dataflow_file(path) is None

    def test_returns_none_for_missing_file(self, tmp_path):
        assert parse_dataflow_file(tmp_path / "missing.json") is None

    def test_returns_none_for_pipeline_json(self, tmp_path):
        path = _write_json(tmp_path, "pipeline.json", {
            "name": "Pipeline",
            "properties": {"activities": [{"name": "Copy", "type": "Copy", "dependsOn": [], "typeProperties": {}}]}
        })
        assert parse_dataflow_file(path) is None

    def test_returns_none_when_no_pq_fields(self, tmp_path):
        path = _write_json(tmp_path, "df.json", {
            "name": "DF",
            "queries": [{"name": "Q"}]
        })
        assert parse_dataflow_file(path) is None


# ---------------------------------------------------------------------------
# ParsedDataflow properties
# ---------------------------------------------------------------------------

class TestParsedDataflowProperties:
    def test_all_mcode_includes_query_names(self):
        df = ParsedDataflow(
            name="DF",
            source_path=Path("df.json"),
            description="",
            queries=[
                DataflowQuery(name="Bronze", pq_code="let\n x=1\nin\n x", description=""),
                DataflowQuery(name="Gold", pq_code="let\n y=2\nin\n y", description=""),
            ],
        )
        mcode = df.all_mcode
        assert "Bronze" in mcode
        assert "Gold" in mcode
        assert "x=1" in mcode

    def test_all_mcode_includes_description_when_set(self):
        df = ParsedDataflow(
            name="DF",
            source_path=Path("df.json"),
            description="",
            queries=[DataflowQuery(name="Q", pq_code="let\n x=1\nin\n x", description="Raw layer")],
        )
        assert "Raw layer" in df.all_mcode

    def test_query_names_property(self):
        df = ParsedDataflow(
            name="DF",
            source_path=Path("df.json"),
            description="",
            queries=[
                DataflowQuery(name="A", pq_code="let\n x=1\nin\n x", description=""),
                DataflowQuery(name="B", pq_code="let\n y=2\nin\n y", description=""),
            ],
        )
        assert df.query_names == ["A", "B"]


# ---------------------------------------------------------------------------
# find_dataflow_files
# ---------------------------------------------------------------------------

class TestFindDataflowFiles:
    def test_finds_dataflow_in_subdirectory(self, tmp_path):
        sub = tmp_path / "dataflows"
        sub.mkdir()
        _write_json(sub, "sales.json", {
            "name": "Sales DF",
            "queries": [{"name": "Q", "pq": "let\n x=1\nin\n x"}],
        })
        found = find_dataflow_files(tmp_path)
        assert any(p.name == "sales.json" for p in found)

    def test_skips_pipeline_json(self, tmp_path):
        _write_json(tmp_path, "pipeline.json", {
            "name": "P",
            "properties": {"activities": [{"name": "A", "type": "Copy", "dependsOn": [], "typeProperties": {}}]},
        })
        found = find_dataflow_files(tmp_path)
        assert not any(p.name == "pipeline.json" for p in found)

    def test_skips_git_directory(self, tmp_path):
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        _write_json(git_dir, "df.json", {
            "name": "DF",
            "queries": [{"name": "Q", "pq": "let\n x=1\nin\n x"}],
        })
        found = find_dataflow_files(tmp_path)
        assert not any(".git" in str(p) for p in found)

    def test_finds_dataflow_extension(self, tmp_path):
        path = tmp_path / "sales.dataflow"
        path.write_text(json.dumps({
            "name": "Sales DF",
            "queries": [{"name": "Q", "pq": "let\n x=1\nin\n x"}],
        }), encoding="utf-8")
        found = find_dataflow_files(tmp_path)
        assert any(p.name == "sales.dataflow" for p in found)

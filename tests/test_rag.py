"""Tests for RAG keyword index and retriever."""

import pytest

from agent.rag.indexer import DocGroup, _sanitize, build_keyword_index
from agent.rag.retriever import RAGRetriever
from tests.conftest import make_activity, make_notebook, make_notebook_section, make_pipeline


# ---------------------------------------------------------------------------
# build_keyword_index
# ---------------------------------------------------------------------------

class TestBuildKeywordIndex:
    def test_indexes_pipeline_group(self):
        activity = make_activity(name="LoadSales", activity_type="Copy")
        pipeline = make_pipeline(name="SalesPipeline", activities=[activity])
        group = DocGroup(group_id="SalesPipeline", pipeline=pipeline, notebooks=[])
        index = build_keyword_index([group])
        assert "SalesPipeline" in index

    def test_pipeline_name_in_chunks(self):
        pipeline = make_pipeline(name="InventoryPipeline")
        group = DocGroup(group_id="InventoryPipeline", pipeline=pipeline, notebooks=[])
        index = build_keyword_index([group])
        chunks = index["InventoryPipeline"]
        assert any("InventoryPipeline" in chunk for chunk in chunks)

    def test_activity_name_in_chunks(self):
        activity = make_activity(name="FetchOrders")
        pipeline = make_pipeline(activities=[activity])
        group = DocGroup(group_id=pipeline.name, pipeline=pipeline, notebooks=[])
        index = build_keyword_index([group])
        chunks = index[pipeline.name]
        assert any("FetchOrders" in chunk for chunk in chunks)

    def test_indexes_notebook_group(self):
        nb = make_notebook(name="TransformNB")
        group = DocGroup(group_id="TransformNB", pipeline=None, notebooks=[nb])
        index = build_keyword_index([group])
        assert "TransformNB" in index

    def test_notebook_heading_in_chunks(self):
        section = make_notebook_section(heading="Revenue Calculation")
        nb = make_notebook(name="RevenueNB", sections=[section])
        group = DocGroup(group_id="RevenueNB", pipeline=None, notebooks=[nb])
        index = build_keyword_index([group])
        chunks = index["RevenueNB"]
        assert any("Revenue Calculation" in chunk for chunk in chunks)

    def test_multiple_groups_independent(self):
        g1 = DocGroup(group_id="G1", pipeline=make_pipeline("G1"), notebooks=[])
        g2 = DocGroup(group_id="G2", pipeline=make_pipeline("G2"), notebooks=[])
        index = build_keyword_index([g1, g2])
        assert "G1" in index
        assert "G2" in index
        assert all("G1" not in chunk for chunk in index["G2"])

    def test_empty_groups(self):
        index = build_keyword_index([])
        assert index == {}


# ---------------------------------------------------------------------------
# RAGRetriever — keyword search
# ---------------------------------------------------------------------------

class TestRAGRetrieverKeyword:
    def _make_index(self):
        return {
            "sales": [
                "Pipeline: Sales data pipeline for revenue tracking",
                "Activity: Load customer records from external source",
                "Activity: Transform order data for reporting",
                "Notebook: Something completely unrelated to the query",
            ]
        }

    def test_returns_relevant_chunks(self):
        retriever = RAGRetriever(keyword_index=self._make_index())
        results = retriever.query("sales revenue pipeline", "sales", top_k=3)
        assert len(results) > 0

    def test_most_relevant_chunk_first(self):
        retriever = RAGRetriever(keyword_index=self._make_index())
        results = retriever.query("sales revenue tracking pipeline", "sales", top_k=3)
        assert "Sales data pipeline for revenue tracking" in results[0]

    def test_respects_top_k(self):
        retriever = RAGRetriever(keyword_index=self._make_index())
        results = retriever.query("sales data", "sales", top_k=2)
        assert len(results) <= 2

    def test_returns_empty_for_unknown_group(self):
        retriever = RAGRetriever(keyword_index=self._make_index())
        assert retriever.query("anything", "nonexistent", top_k=3) == []

    def test_returns_empty_when_no_word_overlap(self):
        retriever = RAGRetriever(keyword_index=self._make_index())
        results = retriever.query("zzz yyy xxx", "sales", top_k=3)
        assert results == []

    def test_no_qdrant_falls_back_to_keyword(self):
        index = {"g": ["revenue sales report quarterly data"]}
        retriever = RAGRetriever(keyword_index=index, qdrant=None, llm_client=None)
        results = retriever.query("revenue sales", "g", top_k=2)
        assert len(results) == 1

    def test_empty_keyword_index(self):
        retriever = RAGRetriever(keyword_index={})
        assert retriever.query("anything", "sales", top_k=3) == []


# ---------------------------------------------------------------------------
# _sanitize
# ---------------------------------------------------------------------------

class TestSanitize:
    def test_removes_do_not(self):
        result = _sanitize("do not reproduce this\nValid content here.")
        assert "do not" not in result
        assert "Valid content here." in result

    def test_removes_return_the(self):
        result = _sanitize("return the result\nKeep this line.")
        assert "return the result" not in result
        assert "Keep this line." in result

    def test_removes_code_fences(self):
        result = _sanitize("Good line\n```python\ncode\n```\nMore content")
        assert "```" not in result
        assert "Good line" in result

    def test_removes_percent_percent(self):
        result = _sanitize("%%python\ndf = spark.read.csv('path')")
        assert "%%" not in result

    def test_preserves_normal_content(self):
        text = "Pipeline processes customer records from the external service."
        assert _sanitize(text) == text

    def test_removes_note_prefix(self):
        result = _sanitize("note: this is important\nActual content.")
        assert "note:" not in result.lower()
        assert "Actual content." in result

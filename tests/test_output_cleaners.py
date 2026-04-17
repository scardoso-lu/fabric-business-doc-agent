"""Tests for _clean_output, _clean_flow_output, and _summarise_props."""

from agent.ai.llm_client import _clean_output, _clean_flow_output, _summarise_props


class TestCleanOutput:
    def test_removes_noise_prefix_note(self):
        result = _clean_output("note: ignore this\nThis is valid.")
        assert "note:" not in result.lower()
        assert "This is valid." in result

    def test_removes_noise_prefix_return(self):
        result = _clean_output("return the result\nValid content.")
        assert "return the result" not in result
        assert "Valid content." in result

    def test_removes_code_fences(self):
        result = _clean_output("Valid line.\n```python\ncode\n```\nAnother line.")
        assert "```" not in result
        assert "Valid line." in result
        assert "Another line." in result

    def test_removes_tilde_fences(self):
        result = _clean_output("Content.\n~~~\nfenced\n~~~")
        assert "~~~" not in result
        assert "Content." in result

    def test_removes_short_lines(self):
        lines = _clean_output(".\nThis is proper content.").splitlines()
        assert "." not in lines

    def test_collapses_excess_blank_lines(self):
        result = _clean_output("Line one.\n\n\n\n\nLine two.")
        assert "\n\n\n" not in result
        assert "Line one." in result
        assert "Line two." in result

    def test_returns_fallback_when_all_noise(self):
        result = _clean_output("note: nothing\nreturn the answer\n```fence```")
        assert result == "Insufficient information available."

    def test_preserves_valid_content(self):
        text = "The process loads sales records from the external feed.\n\nIt then updates the reporting store."
        result = _clean_output(text)
        assert "sales records" in result
        assert "reporting store" in result

    def test_removes_answer_prefix(self):
        result = _clean_output("answer: here is the output\nReal content.")
        assert "answer:" not in result.lower()


class TestCleanFlowOutput:
    MERMAID = "```mermaid\nflowchart LR\n    Source --> Process --> Output\n```"

    def test_preserves_mermaid_block(self):
        text = f"Data flows from the external feed.\n\n{self.MERMAID}"
        result = _clean_flow_output(text)
        assert "```mermaid" in result
        assert "flowchart LR" in result
        assert "Source --> Process --> Output" in result

    def test_cleans_prose_before_mermaid(self):
        text = f"note: ignore\nData flows through the process.\n\n{self.MERMAID}"
        result = _clean_flow_output(text)
        assert "note:" not in result.lower()
        assert "Data flows through the process." in result

    def test_falls_back_to_clean_output_when_no_mermaid(self):
        text = "note: skip this\nValid prose only."
        result = _clean_flow_output(text)
        assert "note:" not in result.lower()
        assert "Valid prose only." in result

    def test_handles_unclosed_mermaid_block(self):
        text = "Some text.\n\n```mermaid\nflowchart LR\n    A --> B"
        result = _clean_flow_output(text)
        assert "```mermaid" in result
        assert "A --> B" in result
        assert result.endswith("```")

    def test_collapses_blank_lines_in_mermaid(self):
        text = f"Text.\n\n```mermaid\nflowchart LR\n\n\n    A --> B\n```"
        result = _clean_flow_output(text)
        assert "\n\n\n" not in result


class TestSummariseProps:
    def test_empty_dict(self):
        assert _summarise_props({}) == "(none)"

    def test_simple_string_value(self):
        result = _summarise_props({"source": "blob_storage"})
        assert "source: blob_storage" in result

    def test_long_string_truncated(self):
        result = _summarise_props({"key": "x" * 200})
        assert len(result) < 200
        assert "…" in result

    def test_dict_value_summarised(self):
        result = _summarise_props({"nested": {"a": 1, "b": 2}})
        assert "nested: {...}" in result

    def test_list_value_summarised(self):
        result = _summarise_props({"items": [1, 2, 3]})
        assert "[3 items]" in result

    def test_multiple_keys(self):
        result = _summarise_props({"a": "one", "b": "two"})
        assert "a: one" in result
        assert "b: two" in result

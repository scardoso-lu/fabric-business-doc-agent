"""Tests for agent/prompts.py — loading, rendering, and fallback behaviour."""

import textwrap
from pathlib import Path

import pytest

import agent.prompts as prompts_mod
from agent.prompts import (
    DEFAULT_PROMPTS,
    SECTION_KEYS,
    _parse_file,
    _reset,
    _strip_blockquotes,
    get,
    get_sub_prompts,
    initialise,
    render,
)


@pytest.fixture(autouse=True)
def reset_prompts():
    """Ensure each test starts with a clean module state."""
    _reset()
    yield
    _reset()


# ---------------------------------------------------------------------------
# render
# ---------------------------------------------------------------------------

class TestRender:
    def test_substitutes_name(self):
        result = render("Hello {{name}}!", name="MyPipeline", content="", rag_context="")
        assert result == "Hello MyPipeline!"

    def test_substitutes_content(self):
        result = render("Info: {{content}}", name="", content="some data", rag_context="")
        assert result == "Info: some data"

    def test_substitutes_rag_context(self):
        result = render("{{rag_context}}Question?", name="", content="", rag_context="Background.\n\n")
        assert result == "Background.\n\nQuestion?"

    def test_empty_rag_context_leaves_no_gap(self):
        result = render("{{rag_context}}Question?", name="", content="", rag_context="")
        assert result == "Question?"

    def test_unknown_placeholder_left_intact(self):
        result = render("{{unknown}} stays", name="", content="", rag_context="")
        assert "{{unknown}}" in result

    def test_multiple_occurrences_all_replaced(self):
        result = render("{{name}} and {{name}}", name="X", content="", rag_context="")
        assert result == "X and X"


# ---------------------------------------------------------------------------
# get — auto-initialises from defaults
# ---------------------------------------------------------------------------

class TestGet:
    def test_returns_default_when_not_initialised(self):
        result = get("purpose")
        assert result == DEFAULT_PROMPTS["purpose"]

    def test_all_keys_return_non_empty_string(self):
        for key in SECTION_KEYS:
            assert get(key), f"get('{key}') returned empty"

    def test_unknown_key_returns_empty_string(self):
        assert get("nonexistent_key") == ""


# ---------------------------------------------------------------------------
# initialise — defaults only
# ---------------------------------------------------------------------------

class TestInitialiseDefaults:
    def test_no_path_uses_defaults(self):
        initialise(None)
        assert get("purpose") == DEFAULT_PROMPTS["purpose"]

    def test_missing_file_uses_defaults(self, tmp_path):
        initialise(tmp_path / "does_not_exist.md")
        assert get("system_prompt") == DEFAULT_PROMPTS["system_prompt"]

    def test_calling_twice_resets(self):
        initialise(None)
        first = get("purpose")
        initialise(None)
        assert get("purpose") == first


# ---------------------------------------------------------------------------
# initialise — file overrides
# ---------------------------------------------------------------------------

class TestInitialiseFromFile:
    def _write(self, tmp_path: Path, content: str) -> Path:
        p = tmp_path / "prompts.md"
        p.write_text(content, encoding="utf-8")
        return p

    def test_overrides_single_section(self, tmp_path):
        p = self._write(tmp_path, "## purpose\n\nMy custom purpose prompt for {{name}}.")
        initialise(p)
        assert get("purpose") == "My custom purpose prompt for {{name}}."

    def test_missing_section_keeps_default(self, tmp_path):
        p = self._write(tmp_path, "## purpose\n\nCustom purpose.")
        initialise(p)
        assert get("flow") == DEFAULT_PROMPTS["flow"]

    def test_overrides_system_prompt(self, tmp_path):
        p = self._write(tmp_path, "## system_prompt\n\nYou are a concise writer.")
        initialise(p)
        assert get("system_prompt") == "You are a concise writer."

    def test_overrides_lineage_system_prompt(self, tmp_path):
        p = self._write(tmp_path, "## lineage_system_prompt\n\nExtract lineage tables.")
        initialise(p)
        assert get("lineage_system_prompt") == "Extract lineage tables."

    def test_multiple_overrides(self, tmp_path):
        p = self._write(tmp_path, textwrap.dedent("""\
            ## purpose
            Custom purpose.

            ## business_goal
            Custom goal.
        """))
        initialise(p)
        assert get("purpose") == "Custom purpose."
        assert get("business_goal") == "Custom goal."
        assert get("flow") == DEFAULT_PROMPTS["flow"]

    def test_unknown_section_key_ignored(self, tmp_path):
        p = self._write(tmp_path, "## unknown_key\n\nThis should be ignored.")
        initialise(p)
        assert "unknown_key" not in DEFAULT_PROMPTS
        assert get("purpose") == DEFAULT_PROMPTS["purpose"]

    def test_preamble_before_first_heading_ignored(self, tmp_path):
        p = self._write(tmp_path, textwrap.dedent("""\
            # Title

            Some intro text that should be ignored.

            ## purpose
            Overridden purpose.
        """))
        initialise(p)
        assert get("purpose") == "Overridden purpose."

    def test_empty_section_body_keeps_default(self, tmp_path):
        p = self._write(tmp_path, "## purpose\n\n## flow\n\nCustom flow.")
        initialise(p)
        assert get("purpose") == DEFAULT_PROMPTS["purpose"]
        assert get("flow") == "Custom flow."

    def test_render_uses_overridden_template(self, tmp_path):
        p = self._write(tmp_path, "## purpose\n\nTell me about {{name}}.")
        initialise(p)
        result = render(get("purpose"), name="SalesPipeline", content="...", rag_context="")
        assert "SalesPipeline" in result
        assert "Tell me about" in result


# ---------------------------------------------------------------------------
# _parse_file
# ---------------------------------------------------------------------------

class TestParseFile:
    def test_returns_empty_dict_for_missing_file(self, tmp_path):
        result = _parse_file(tmp_path / "missing.md")
        assert result == {}

    def test_parses_single_section(self, tmp_path):
        p = tmp_path / "p.md"
        p.write_text("## purpose\n\nHello.", encoding="utf-8")
        result = _parse_file(p)
        assert result == {"purpose": "Hello."}

    def test_ignores_unknown_keys(self, tmp_path):
        p = tmp_path / "p.md"
        p.write_text("## bogus\n\nSome text.", encoding="utf-8")
        result = _parse_file(p)
        assert "bogus" not in result

    def test_strips_whitespace_from_body(self, tmp_path):
        p = tmp_path / "p.md"
        p.write_text("## purpose\n\n\n  Hello world.  \n\n", encoding="utf-8")
        result = _parse_file(p)
        assert result["purpose"] == "Hello world."


# ---------------------------------------------------------------------------
# _strip_blockquotes
# ---------------------------------------------------------------------------

class TestStripBlockquotes:
    def test_removes_blockquote_lines(self):
        text = "> This is a note\nReal content"
        result = _strip_blockquotes(text)
        assert "> This is a note" not in result
        assert "Real content" in result

    def test_leaves_non_blockquote_lines(self):
        assert _strip_blockquotes("Hello\nWorld") == "Hello\nWorld"

    def test_removes_indented_blockquote(self):
        text = "  > indented note\nContent"
        result = _strip_blockquotes(text)
        assert "indented note" not in result
        assert "Content" in result

    def test_empty_string(self):
        assert _strip_blockquotes("") == ""

    def test_all_blockquotes_returns_empty_or_whitespace(self):
        result = _strip_blockquotes("> a\n> b")
        assert result.strip() == ""


# ---------------------------------------------------------------------------
# get_sub_prompts
# ---------------------------------------------------------------------------

class TestGetSubPrompts:
    def test_single_prompt_returns_list_of_one(self):
        result = get_sub_prompts("column_lineage")
        assert isinstance(result, list)
        assert len(result) == 1

    def test_purpose_has_two_sub_prompts(self):
        result = get_sub_prompts("purpose")
        assert len(result) == 2

    def test_flow_has_two_sub_prompts(self):
        result = get_sub_prompts("flow")
        assert len(result) == 2

    def test_flow_second_sub_prompt_contains_mermaid(self):
        result = get_sub_prompts("flow")
        assert "```mermaid" in result[1]

    def test_flow_first_sub_prompt_has_no_mermaid(self):
        result = get_sub_prompts("flow")
        assert "```mermaid" not in result[0]

    def test_business_goal_has_two_sub_prompts(self):
        result = get_sub_prompts("business_goal")
        assert len(result) == 2

    def test_data_quality_has_two_sub_prompts(self):
        result = get_sub_prompts("data_quality")
        assert len(result) == 2

    def test_all_sub_prompts_are_non_empty(self):
        for key in SECTION_KEYS:
            for i, sp in enumerate(get_sub_prompts(key)):
                assert sp.strip(), f"get_sub_prompts('{key}')[{i}] is empty"

    def test_unknown_key_returns_single_empty_or_fallback(self):
        result = get_sub_prompts("nonexistent_key")
        assert isinstance(result, list)

    def test_custom_template_with_separator(self, tmp_path):
        p = tmp_path / "prompts.md"
        p.write_text("## purpose\n\nFirst part.\n\n---\n\nSecond part.\n", encoding="utf-8")
        initialise(p)
        result = get_sub_prompts("purpose")
        assert len(result) == 2
        assert result[0] == "First part."
        assert result[1] == "Second part."

    def test_blockquotes_stripped_from_file_sub_prompts(self, tmp_path):
        p = tmp_path / "prompts.md"
        p.write_text("## purpose\n\n> Editor note\n\nReal prompt.\n", encoding="utf-8")
        initialise(p)
        result = get_sub_prompts("purpose")
        assert len(result) == 1
        assert result[0] == "Real prompt."
        assert "> Editor note" not in result[0]

    def test_trailing_separator_does_not_produce_empty_part(self, tmp_path):
        p = tmp_path / "prompts.md"
        p.write_text("## purpose\n\nOnly part.\n\n---\n", encoding="utf-8")
        initialise(p)
        result = get_sub_prompts("purpose")
        assert len(result) == 1
        assert result[0] == "Only part."


# ---------------------------------------------------------------------------
# _parse_file — blockquote stripping
# ---------------------------------------------------------------------------

class TestParseFileBlockquotes:
    def test_blockquote_lines_stripped_from_body(self, tmp_path):
        p = tmp_path / "p.md"
        p.write_text("## purpose\n\n> Editorial note\n\nActual prompt.\n", encoding="utf-8")
        result = _parse_file(p)
        assert "> Editorial note" not in result["purpose"]
        assert "Actual prompt." in result["purpose"]

    def test_only_blockquote_body_treated_as_empty(self, tmp_path):
        p = tmp_path / "p.md"
        p.write_text("## purpose\n\n> Just a note\n", encoding="utf-8")
        result = _parse_file(p)
        assert "purpose" not in result


# ---------------------------------------------------------------------------
# Default prompts completeness
# ---------------------------------------------------------------------------

class TestDefaultPromptsCompleteness:
    def test_all_section_keys_have_defaults(self):
        for key in SECTION_KEYS:
            assert key in DEFAULT_PROMPTS, f"Missing default for '{key}'"
            assert DEFAULT_PROMPTS[key].strip(), f"Empty default for '{key}'"

    def test_purpose_template_has_name_placeholder(self):
        assert "{{name}}" in DEFAULT_PROMPTS["purpose"]

    def test_purpose_template_has_content_placeholder(self):
        assert "{{content}}" in DEFAULT_PROMPTS["purpose"]

    def test_flow_template_has_mermaid_block(self):
        assert "```mermaid" in DEFAULT_PROMPTS["flow"]

    def test_flow_template_uses_name_in_diagram(self):
        assert "{{name}}" in DEFAULT_PROMPTS["flow"]

    def test_lineage_template_has_content_placeholder(self):
        assert "{{content}}" in DEFAULT_PROMPTS["column_lineage"]

    def test_system_prompt_mentions_business_analyst(self):
        assert "business analyst" in DEFAULT_PROMPTS["system_prompt"].lower()

    def test_lineage_system_prompt_mentions_tables(self):
        assert "| Source | Target Column" in DEFAULT_PROMPTS["lineage_system_prompt"]

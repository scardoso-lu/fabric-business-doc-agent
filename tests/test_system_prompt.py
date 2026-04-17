"""Tests for build_system_prompt — context file injection."""

import agent.config as config_mod
from agent.ai.llm_client import SYSTEM_PROMPT, build_system_prompt


def test_no_context_returns_base_prompt(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
    result = build_system_prompt()
    assert result == SYSTEM_PROMPT


def test_with_context_appends_to_base_prompt(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "We are a retail analytics company.")
    result = build_system_prompt()
    assert SYSTEM_PROMPT in result
    assert "We are a retail analytics company." in result


def test_with_context_includes_label(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "Company context here.")
    result = build_system_prompt()
    assert "Organisation and project context" in result


def test_context_appears_after_system_prompt(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "Domain context.")
    result = build_system_prompt()
    system_pos = result.find(SYSTEM_PROMPT)
    context_pos = result.find("Domain context.")
    assert system_pos < context_pos


def test_whitespace_context_treated_as_empty(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
    result = build_system_prompt()
    assert result == SYSTEM_PROMPT

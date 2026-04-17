"""Tests for create_client factory."""

import pytest
from unittest.mock import patch

import agent.ai.client_factory as factory_mod
import agent.config as config_mod
from agent.ai.local_claude_client import LocalClaudeClient


class TestCreateClient:
    def test_returns_local_claude_client(self, monkeypatch):
        monkeypatch.setattr(factory_mod, "LLM_PROVIDER", "local")
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
        from agent.ai.client_factory import create_client
        client = create_client()
        assert isinstance(client, LocalClaudeClient)

    def test_local_client_has_no_rag(self, monkeypatch):
        monkeypatch.setattr(factory_mod, "LLM_PROVIDER", "local")
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
        from agent.ai.client_factory import create_client
        client = create_client()
        assert client.supports_rag is False
        assert client.embedding_model is None

    def test_anthropic_raises_without_api_key(self, monkeypatch):
        import agent.ai.llm_client as llm_mod
        monkeypatch.setattr(factory_mod, "LLM_PROVIDER", "anthropic")
        monkeypatch.setattr(llm_mod, "LLM_PROVIDER", "anthropic")
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        from agent.ai.client_factory import create_client
        with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
            create_client()

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setattr(factory_mod, "LLM_PROVIDER", "unknown_provider")
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
        from agent.ai.client_factory import create_client
        with pytest.raises(ValueError):
            create_client()

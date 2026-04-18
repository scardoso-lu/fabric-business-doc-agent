"""Tests for LocalClaudeClient."""

import pytest
from unittest.mock import MagicMock, patch

import agent.config as config_mod


@pytest.fixture(autouse=True)
def no_context(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")


def _make_client():
    from agent.ai.local_claude_client import LocalClaudeClient
    return LocalClaudeClient(timeout=30)


def _subprocess_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_provider_is_local(self):
        assert _make_client().provider == "local"

    def test_supports_rag_is_false(self):
        assert _make_client().supports_rag is False

    def test_embedding_model_is_none(self):
        assert _make_client().embedding_model is None

    def test_embed_returns_none(self):
        assert _make_client().embed(["text"]) is None

    def test_set_retriever_is_noop(self):
        client = _make_client()
        client.set_retriever(MagicMock())  # must not raise


# ---------------------------------------------------------------------------
# _call
# ---------------------------------------------------------------------------

class TestCall:
    def test_invokes_claude_cli(self):
        client = _make_client()
        result_mock = _subprocess_result(stdout="The process loads data.")
        with patch("subprocess.run", return_value=result_mock) as run_mock:
            client._call("Explain this pipeline.")
        args = run_mock.call_args[0][0]
        assert args[0] == "claude"
        assert args[1] == "-p"

    def test_prompt_includes_user_message(self):
        client = _make_client()
        result_mock = _subprocess_result(stdout="Response.")
        with patch("subprocess.run", return_value=result_mock) as run_mock:
            client._call("My specific prompt text.")
        prompt = run_mock.call_args[0][0][2]
        assert "My specific prompt text." in prompt

    def test_system_prompt_prepended(self):
        client = _make_client()
        result_mock = _subprocess_result(stdout="Response.")
        with patch("subprocess.run", return_value=result_mock) as run_mock:
            client._call("User message.")
        prompt = run_mock.call_args[0][0][2]
        from agent.ai.llm_client import SYSTEM_PROMPT
        assert SYSTEM_PROMPT[:50] in prompt

    def test_returns_cleaned_output(self):
        client = _make_client()
        result_mock = _subprocess_result(stdout="note: ignore\nReal output content.")
        with patch("subprocess.run", return_value=result_mock):
            result = client._call("prompt")
        assert "note:" not in result.lower()
        assert "Real output content." in result

    def test_raises_on_nonzero_exit(self):
        client = _make_client()
        result_mock = _subprocess_result(returncode=1, stderr="Model error")
        with patch("subprocess.run", return_value=result_mock):
            with pytest.raises(RuntimeError, match="claude CLI"):
                client._call("prompt")

    def test_passes_timeout(self):
        client = _make_client()
        result_mock = _subprocess_result(stdout="ok")
        with patch("subprocess.run", return_value=result_mock) as run_mock:
            client._call("prompt")
        assert run_mock.call_args.kwargs.get("timeout") == 30

    def test_context_appended_to_prompt(self, monkeypatch):
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "We are a healthcare company.")
        from agent.ai.local_claude_client import LocalClaudeClient
        client = LocalClaudeClient()
        result_mock = _subprocess_result(stdout="Response.")
        with patch("subprocess.run", return_value=result_mock) as run_mock:
            client._call("Explain this.")
        prompt = run_mock.call_args[0][0][2]
        assert "We are a healthcare company." in prompt


# ---------------------------------------------------------------------------
# _call_flow
# ---------------------------------------------------------------------------

class TestCallFlow:
    def test_preserves_mermaid_block(self):
        client = _make_client()
        stdout = (
            "Data flows from the source feed to the storage area.\n\n"
            "```mermaid\nflowchart LR\n    Feed --> Process --> Store\n```"
        )
        with patch("subprocess.run", return_value=_subprocess_result(stdout=stdout)):
            result = client._call_flow("Flow prompt.")
        assert "```mermaid" in result
        assert "Feed --> Process --> Store" in result

    def test_cleans_prose_before_mermaid(self):
        client = _make_client()
        stdout = (
            "note: ignore this\nData flows from source to output.\n\n"
            "```mermaid\nflowchart LR\n    A --> B\n```"
        )
        with patch("subprocess.run", return_value=_subprocess_result(stdout=stdout)):
            result = client._call_flow("Flow prompt.")
        assert "note:" not in result.lower()
        assert "Data flows from source to output." in result

    def test_raises_on_nonzero_exit(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(returncode=1, stderr="err")):
            with pytest.raises(RuntimeError):
                client._call_flow("prompt")


# ---------------------------------------------------------------------------
# Section methods (smoke tests — verify they call _call / _call_flow)
# ---------------------------------------------------------------------------

class TestSectionMethods:
    def _patched_call(self, method_name: str, *args):
        """Verify _call is invoked at least once (once per sub-prompt)."""
        client = _make_client()
        with patch.object(client, "_call", return_value="section text") as m:
            result = getattr(client, method_name)(*args)
            assert m.call_count >= 1
            assert isinstance(result, str)

    def test_section_purpose_calls_call(self):
        self._patched_call("section_purpose", "PipelineName", "content")

    def test_section_business_goal_calls_call(self):
        self._patched_call("section_business_goal", "PipelineName", "content")

    def test_section_data_quality_calls_call(self):
        self._patched_call("section_data_quality", "PipelineName", "content")

    def test_section_flow_calls_call_flow(self):
        client = _make_client()
        with patch.object(client, "_call_flow", return_value="flow text") as m:
            with patch.object(client, "_call", return_value="prose text"):
                client.section_flow("PipelineName", "content")
            assert m.call_count >= 1

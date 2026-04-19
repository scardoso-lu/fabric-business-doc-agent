"""Tests for CopilotCLIClient."""

import subprocess
import pytest
from unittest.mock import MagicMock, patch

import agent.config as config_mod


@pytest.fixture(autouse=True)
def no_context(monkeypatch):
    monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")


def _make_client():
    from agent.ai.copilot_client import CopilotCLIClient
    return CopilotCLIClient(timeout=30)


def _subprocess_result(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
    m = MagicMock()
    m.returncode = returncode
    m.stdout = stdout
    m.stderr = stderr
    return m


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

class TestStripAnsi:
    def test_removes_colour_codes(self):
        from agent.ai.copilot_client import _strip_ansi
        assert _strip_ansi("\x1b[32mgreen\x1b[0m") == "green"

    def test_removes_cursor_movement(self):
        from agent.ai.copilot_client import _strip_ansi
        assert _strip_ansi("\x1b[1Aup text") == "up text"

    def test_passthrough_plain_text(self):
        from agent.ai.copilot_client import _strip_ansi
        assert _strip_ansi("plain text") == "plain text"


class TestStripCopilotHeader:
    def test_removes_welcome_banner(self):
        from agent.ai.copilot_client import _strip_copilot_header
        text = "Welcome to GitHub Copilot in the CLI!\nversion 1.0.0\nActual content."
        result = _strip_copilot_header(text)
        assert "Welcome to" not in result
        assert "version 1.0.0" not in result
        assert "Actual content." in result

    def test_removes_explanation_label(self):
        from agent.ai.copilot_client import _strip_copilot_header
        text = "Explanation:\nThis pipeline loads customer data."
        result = _strip_copilot_header(text)
        assert "Explanation:" not in result
        assert "This pipeline loads customer data." in result

    def test_preserves_content_lines(self):
        from agent.ai.copilot_client import _strip_copilot_header
        text = "The pipeline reads from the bronze layer."
        assert _strip_copilot_header(text) == text


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------

class TestProperties:
    def test_provider_is_copilot(self):
        assert _make_client().provider == "copilot"

    def test_model_string(self):
        assert "copilot" in _make_client().model.lower()

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
# _run — subprocess integration
# ---------------------------------------------------------------------------

class TestRun:
    def test_invokes_gh_copilot_explain(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(stdout="ok")) as run_mock:
            client._run("some prompt")
        cmd = run_mock.call_args[0][0]
        assert cmd == ["gh", "copilot", "explain", "some prompt"]

    def test_stdin_is_devnull(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(stdout="ok")) as run_mock:
            client._run("prompt")
        assert run_mock.call_args.kwargs.get("stdin") is subprocess.DEVNULL

    def test_no_color_env_set(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(stdout="ok")) as run_mock:
            client._run("prompt")
        env = run_mock.call_args.kwargs.get("env", {})
        assert env.get("NO_COLOR") == "1"

    def test_timeout_passed(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(stdout="ok")) as run_mock:
            client._run("prompt")
        assert run_mock.call_args.kwargs.get("timeout") == 30

    def test_strips_ansi_from_output(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(stdout="\x1b[32mgreen output\x1b[0m")):
            result = client._run("prompt")
        assert "\x1b" not in result
        assert "green output" in result

    def test_strips_copilot_banner(self):
        client = _make_client()
        raw = "Welcome to GitHub Copilot in the CLI!\nversion 1.0.0\nExplanation:\nThe pipeline moves data."
        with patch("subprocess.run", return_value=_subprocess_result(stdout=raw)):
            result = client._run("prompt")
        assert "Welcome to" not in result
        assert "The pipeline moves data." in result

    def test_raises_on_nonzero_exit(self):
        client = _make_client()
        with patch("subprocess.run", return_value=_subprocess_result(returncode=1, stderr="auth error")):
            with pytest.raises(RuntimeError, match="code 1"):
                client._run("prompt")

    def test_raises_file_not_found(self):
        client = _make_client()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            with pytest.raises(RuntimeError, match="gh.*not found"):
                client._run("prompt")

    def test_raises_on_timeout(self):
        client = _make_client()
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="gh", timeout=30)):
            with pytest.raises(RuntimeError, match="timed out"):
                client._run("prompt")


# ---------------------------------------------------------------------------
# _call
# ---------------------------------------------------------------------------

class TestCall:
    def test_prepends_system_prompt(self):
        client = _make_client()
        with patch.object(client, "_run", return_value="Response text.") as run_mock:
            client._call("User message.")
        prompt = run_mock.call_args[0][0]
        assert "User message." in prompt
        assert client._system_prompt in prompt

    def test_system_prompt_before_user_message(self):
        client = _make_client()
        with patch.object(client, "_run", return_value="ok") as run_mock:
            client._call("User message.")
        prompt = run_mock.call_args[0][0]
        sys_idx = prompt.index(client._system_prompt)
        user_idx = prompt.index("User message.")
        assert sys_idx < user_idx

    def test_cleans_output(self):
        client = _make_client()
        with patch.object(client, "_run", return_value="note: ignore\nReal content here."):
            result = client._call("prompt")
        assert "note:" not in result.lower()
        assert "Real content here." in result

    def test_context_in_system_prompt(self, monkeypatch):
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "We are a fintech company.")
        from agent.ai.copilot_client import CopilotCLIClient
        client = CopilotCLIClient()
        with patch.object(client, "_run", return_value="ok") as run_mock:
            client._call("Explain this.")
        prompt = run_mock.call_args[0][0]
        assert "We are a fintech company." in prompt


# ---------------------------------------------------------------------------
# _call_flow
# ---------------------------------------------------------------------------

class TestCallFlow:
    def test_preserves_mermaid_block(self):
        client = _make_client()
        raw = "Data flows from source to destination.\n\n```mermaid\nflowchart LR\n    A --> B\n```"
        with patch.object(client, "_run", return_value=raw):
            result = client._call_flow("flow prompt")
        assert "```mermaid" in result
        assert "A --> B" in result

    def test_cleans_prose_before_mermaid(self):
        client = _make_client()
        raw = "note: skip\nProper prose.\n\n```mermaid\nflowchart LR\n    A --> B\n```"
        with patch.object(client, "_run", return_value=raw):
            result = client._call_flow("flow prompt")
        assert "note:" not in result.lower()
        assert "Proper prose." in result


# ---------------------------------------------------------------------------
# _call_lineage
# ---------------------------------------------------------------------------

class TestCallLineage:
    def test_uses_lineage_system_prompt(self):
        client = _make_client()
        import agent.prompts as prompts_mod
        lineage_prompt = prompts_mod.get("lineage_system_prompt")
        with patch.object(client, "_run", return_value="| Col | Source |") as run_mock:
            client._call_lineage("Lineage request.")
        prompt = run_mock.call_args[0][0]
        assert lineage_prompt in prompt

    def test_preserves_markdown_table(self):
        client = _make_client()
        table = "| Column | Source | Transformation |\n|---|---|---|\n| id | raw.id | cast to int |"
        with patch.object(client, "_run", return_value=table):
            result = client._call_lineage("lineage prompt")
        assert "| Column |" in result
        assert "cast to int" in result


# ---------------------------------------------------------------------------
# Factory integration
# ---------------------------------------------------------------------------

class TestFactory:
    def test_factory_returns_copilot_client(self, monkeypatch):
        import agent.ai.client_factory as factory_mod
        monkeypatch.setattr(factory_mod, "LLM_PROVIDER", "copilot")
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
        from agent.ai.client_factory import create_client
        from agent.ai.copilot_client import CopilotCLIClient
        client = create_client()
        assert isinstance(client, CopilotCLIClient)

    def test_copilot_client_has_no_rag(self, monkeypatch):
        import agent.ai.client_factory as factory_mod
        monkeypatch.setattr(factory_mod, "LLM_PROVIDER", "copilot")
        monkeypatch.setattr(config_mod, "CONTEXT_TEXT", "")
        from agent.ai.client_factory import create_client
        client = create_client()
        assert client.supports_rag is False
        assert client.embedding_model is None

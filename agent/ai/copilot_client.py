"""
GitHub Copilot CLI client — invokes `gh copilot explain` via subprocess.

Requires an authenticated `gh` CLI with an active GitHub Copilot subscription.
Set LLM_PROVIDER=copilot in .env.  No additional API key is needed.
RAG is skipped; the full content summary is passed directly to Copilot.

Integration notes
-----------------
* `gh copilot explain <prompt>` is used rather than `suggest` because explain
  is non-interactive and produces natural-language prose output.
* stdout is captured with NO_COLOR=1 to avoid ANSI escape sequences.
* stdin is bound to DEVNULL so any unexpected interactive prompt fails fast
  instead of hanging the process.
* The Copilot CLI emits a welcome banner on first run; _strip_copilot_header()
  removes it along with "Explanation:" section labels.
* Prompts are passed as a single positional argument.  OS ARG_MAX on Linux is
  ~2 MB; the longest prompt this agent produces is well under 10 KB.
"""

from __future__ import annotations

import os
import re
import subprocess

import agent.prompts as prompts
from agent.ai.base_client import BaseLLMClient
from agent.ai.utils import (
    _clean_flow_output,
    _clean_lineage_output,
    _clean_output,
    build_system_prompt,
)

# Matches all ANSI CSI escape sequences (colours, cursor movement, etc.)
_ANSI_RE = re.compile(r"\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# Lines that are purely Copilot CLI chrome, not model output
_HEADER_PREFIXES = (
    "welcome to github copilot",
    "version ",
    "tip:",
    "feedback:",
)
_LABEL_LINES = {"explanation:", "suggestion:", "command:", "answer:"}


def _strip_ansi(text: str) -> str:
    """Remove ANSI terminal escape sequences."""
    return _ANSI_RE.sub("", text)


def _strip_copilot_header(text: str) -> str:
    """Remove GitHub Copilot CLI chrome: welcome banner, version line, labels."""
    out = []
    for line in text.splitlines():
        stripped = line.strip()
        lower = stripped.lower()
        if any(lower.startswith(p) for p in _HEADER_PREFIXES):
            continue
        if lower in _LABEL_LINES:
            continue
        out.append(line)
    return "\n".join(out)


def _clean_copilot_raw(text: str) -> str:
    """Strip ANSI codes and Copilot chrome from raw subprocess output."""
    text = _strip_ansi(text)
    text = _strip_copilot_header(text)
    return text.strip()


class CopilotCLIClient(BaseLLMClient):
    """
    Calls `gh copilot explain <prompt>` in a subprocess.

    Prerequisites:
      - GitHub CLI installed: https://cli.github.com
      - Copilot extension installed: gh extension install github/gh-copilot
      - Authenticated: gh auth login
      - Active GitHub Copilot subscription
    """

    def __init__(self, timeout: int = 120) -> None:
        self._timeout = timeout
        self._system_prompt = build_system_prompt()

    @property
    def provider(self) -> str:
        return "copilot"

    @property
    def model(self) -> str:
        return "copilot (gh CLI)"

    @property
    def embedding_model(self) -> str | None:
        return None

    @property
    def supports_rag(self) -> bool:
        return False

    def set_retriever(self, retriever) -> None:
        pass

    def embed(self, texts: list[str]) -> list[list[float]] | None:
        return None

    # ------------------------------------------------------------------
    # Internal subprocess helper
    # ------------------------------------------------------------------

    def _run(self, prompt: str) -> str:
        """
        Invoke `gh copilot explain <prompt>` and return cleaned output.

        Raises
        ------
        RuntimeError
            If the CLI is not found, times out, or exits with a non-zero code.
        """
        env = {
            **os.environ,
            "NO_COLOR": "1",           # suppress ANSI colour codes
            "GH_NO_UPDATE_NOTIFIER": "1",  # suppress update nag
        }
        try:
            result = subprocess.run(
                ["gh", "copilot", "explain", prompt],
                capture_output=True,
                text=True,
                timeout=self._timeout,
                stdin=subprocess.DEVNULL,  # never block waiting for input
                env=env,
            )
        except FileNotFoundError:
            raise RuntimeError(
                "GitHub CLI ('gh') not found. "
                "Install from https://cli.github.com and then run: "
                "gh extension install github/gh-copilot"
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"gh copilot explain timed out after {self._timeout}s. "
                "Increase COPILOT_TIMEOUT in .env or check your network connection."
            )

        if result.returncode != 0:
            stderr = result.stderr.strip()
            raise RuntimeError(
                f"gh copilot explain exited with code {result.returncode}"
                + (f": {stderr}" if stderr else "")
            )

        return _clean_copilot_raw(result.stdout)

    # ------------------------------------------------------------------
    # LLM call primitives
    # ------------------------------------------------------------------

    def _call(self, user_message: str, max_tokens: int = 1024) -> str:
        full_prompt = f"{self._system_prompt}\n\n{user_message}"
        return _clean_output(self._run(full_prompt))

    def _call_flow(self, user_message: str) -> str:
        """Like _call but preserves the mermaid diagram block in the output."""
        full_prompt = f"{self._system_prompt}\n\n{user_message}"
        return _clean_flow_output(self._run(full_prompt))

    def _call_lineage(self, user_message: str) -> str:
        """Uses the lineage system prompt and preserves table output."""
        full_prompt = f"{prompts.get('lineage_system_prompt')}\n\n{user_message}"
        return _clean_lineage_output(self._run(full_prompt))

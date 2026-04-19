from agent.ai.base_client import BaseLLMClient
from agent.config import LLM_PROVIDER

_KNOWN_PROVIDERS = {"anthropic", "openai", "ollama", "local", "copilot"}


def create_client() -> BaseLLMClient:
    """Return the appropriate LLM client based on LLM_PROVIDER in .env."""
    provider = LLM_PROVIDER.lower()
    if provider not in _KNOWN_PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. "
            f"Choose one of: {', '.join(sorted(_KNOWN_PROVIDERS))}"
        )
    if provider == "local":
        from agent.ai.local_claude_client import LocalClaudeClient
        return LocalClaudeClient()
    if provider == "copilot":
        from agent.ai.copilot_client import CopilotCLIClient
        return CopilotCLIClient()
    from agent.ai.llm_client import LLMClient
    return LLMClient()

from agent.ai.base_client import BaseLLMClient
from agent.config import LLM_PROVIDER


def create_client() -> BaseLLMClient:
    """Return the appropriate LLM client based on LLM_PROVIDER in .env."""
    provider = LLM_PROVIDER.lower()
    if provider == "local":
        from agent.ai.local_claude_client import LocalClaudeClient
        return LocalClaudeClient()
    from agent.ai.llm_client import LLMClient
    return LLMClient()

"""
Provider factory — returns the correct BaseLLMProvider for the configured provider.
One call site: BaseAgent.__init__. Everything else uses the abstract interface.
"""
from __future__ import annotations

from dri.llm.base import BaseLLMProvider


def create_provider() -> BaseLLMProvider:
    """Instantiate and return the active LLM provider from settings."""
    from dri.config.settings import get_settings
    s = get_settings()

    if s.llm_provider == "gemini":
        from dri.llm.gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=s.google_api_key,
            vertex_ai=s.use_vertex_ai,
            project=s.vertex_project,
            location=s.vertex_location,
            credentials_file=s.google_application_credentials,
        )

    if s.llm_provider == "openai_compatible":
        from dri.llm.openai_compatible_provider import OpenAICompatibleProvider
        return OpenAICompatibleProvider(
            api_key=s.openai_compatible_api_key,
            base_url=s.openai_compatible_base_url,
        )

    from dri.llm.anthropic_provider import AnthropicProvider
    return AnthropicProvider(api_key=s.anthropic_api_key)

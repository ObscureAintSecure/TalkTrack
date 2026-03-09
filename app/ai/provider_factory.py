"""Factory for creating AI providers from config."""

from app.ai.provider import AIProvider


def create_provider(config: dict) -> AIProvider | None:
    provider_type = config.get("provider", "none")

    if provider_type == "none":
        return None

    if provider_type == "claude":
        from app.ai.claude_provider import ClaudeProvider
        return ClaudeProvider(
            api_key=config["api_key"],
            model=config.get("model", "claude-sonnet-4-6"),
        )

    if provider_type == "openai":
        from app.ai.openai_provider import OpenAIProvider
        return OpenAIProvider(
            api_key=config["api_key"],
            model=config.get("model", "gpt-4o"),
        )

    if provider_type == "grok":
        from app.ai.grok_provider import GrokProvider
        return GrokProvider(
            api_key=config["api_key"],
            model=config.get("model", "grok-3"),
        )

    if provider_type == "gemini":
        from app.ai.gemini_provider import GeminiProvider
        return GeminiProvider(
            api_key=config["api_key"],
            model=config.get("model", "gemini-2.5-flash"),
        )

    if provider_type == "mistral":
        from app.ai.mistral_provider import MistralProvider
        return MistralProvider(
            api_key=config["api_key"],
            model=config.get("model", "mistral-large-latest"),
        )

    if provider_type == "local":
        from app.ai.local_provider import LocalProvider
        return LocalProvider(
            model_path=config.get("model", ""),
            embed_model=config.get("embed_model", "all-MiniLM-L6-v2"),
        )

    raise ValueError(f"Unknown AI provider: {provider_type}")

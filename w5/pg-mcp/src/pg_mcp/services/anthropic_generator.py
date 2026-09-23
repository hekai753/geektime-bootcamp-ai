"""Anthropic Claude implementation of the SQL generation pipeline.

``AnthropicSQLGenerator`` reuses the entire prompt/extraction/retry pipeline
from :class:`~pg_mcp.services.sql_generator.SQLGenerator` and only swaps the
LLM call itself, following the provider-subclassing pattern sketched in the
project's CLAUDE.md.
"""

from anthropic import AsyncAnthropic

from pg_mcp.config.settings import AnthropicConfig, OpenAIConfig
from pg_mcp.models.errors import LLMError
from pg_mcp.services.sql_generator import SQLGenerator


def build_anthropic_client(config: AnthropicConfig) -> AsyncAnthropic:
    """Build an AsyncAnthropic honoring api_key/auth_token/base_url config.

    Args:
        config: AnthropicConfig instance.

    Returns:
        AsyncAnthropic: Configured SDK client.
    """
    kwargs: dict = {"timeout": config.timeout}
    if config.base_url:
        kwargs["base_url"] = config.base_url
    if config.auth_token.get_secret_value():
        kwargs["auth_token"] = config.auth_token.get_secret_value()
    else:
        kwargs["api_key"] = config.api_key.get_secret_value()
    return AsyncAnthropic(**kwargs)


class AnthropicSQLGenerator(SQLGenerator):
    """SQL generator backed by the Anthropic Claude API."""

    def __init__(self, anthropic_config: AnthropicConfig, openai_config: OpenAIConfig) -> None:
        """Initialize the Claude-backed generator.

        Args:
            anthropic_config: Anthropic API settings (key, model, timeout).
            openai_config: Kept as the generation-parameter source
                (temperature/max_tokens) so prompt budgets stay identical
                across providers.
        """
        super().__init__(openai_config)
        self.anthropic_config = anthropic_config
        self.client = build_anthropic_client(anthropic_config)

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Send a messages request to the Anthropic API.

        Args:
            system_prompt: System instruction prompt.
            user_prompt: User message containing question and schema.

        Returns:
            str: Raw text content from the model.

        Raises:
            LLMError: If the response contains no text content.
        """
        response = await self.client.messages.create(
            model=self.anthropic_config.model,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=self.config.max_tokens,
        )
        for block in response.content:
            if getattr(block, "type", None) == "text" and block.text:
                return block.text
        raise LLMError(
            message="Anthropic returned empty message content",
            details={"model": self.anthropic_config.model},
        )

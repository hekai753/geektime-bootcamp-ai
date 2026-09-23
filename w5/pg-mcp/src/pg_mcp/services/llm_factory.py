"""Factory for building the LLM-backed services from configuration.

Selects the concrete generator/validator implementation based on
``Settings.llm.provider`` so that switching between OpenAI and Anthropic
is a pure configuration change (AC6).
"""

from pg_mcp.config.settings import Settings
from pg_mcp.services.anthropic_generator import AnthropicSQLGenerator
from pg_mcp.services.anthropic_result_validator import AnthropicResultValidator
from pg_mcp.services.result_validator import ResultValidator
from pg_mcp.services.sql_generator import SQLGenerator


def create_sql_generator(settings: Settings) -> SQLGenerator:
    """Build the SQL generator for the configured provider.

    Args:
        settings: Application settings (reads ``llm.provider``).

    Returns:
        SQLGenerator: Provider-specific generator instance.

    Raises:
        ValueError: If the configured provider is unknown.
    """
    provider = settings.llm.provider
    if provider == "anthropic":
        return AnthropicSQLGenerator(settings.anthropic, settings.openai)
    if provider == "openai":
        return SQLGenerator(settings.openai)
    raise ValueError(f"Unknown LLM provider: {provider}")


def create_result_validator(settings: Settings) -> ResultValidator:
    """Build the result validator for the configured provider.

    Args:
        settings: Application settings (reads ``llm.provider``).

    Returns:
        ResultValidator: Provider-specific validator instance.

    Raises:
        ValueError: If the configured provider is unknown.
    """
    provider = settings.llm.provider
    if provider == "anthropic":
        return AnthropicResultValidator(settings.anthropic, settings.openai, settings.validation)
    if provider == "openai":
        return ResultValidator(settings.openai, settings.validation)
    raise ValueError(f"Unknown LLM provider: {provider}")

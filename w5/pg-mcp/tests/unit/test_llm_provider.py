"""Unit tests for LLM provider selection (AC6).

Covers the factory wiring and the Anthropic implementations of the SQL
generator and result validator, using mocked Anthropic SDK clients.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import SecretStr

from pg_mcp.config.settings import (
    AnthropicConfig,
    LLMProviderConfig,
    OpenAIConfig,
    Settings,
    ValidationConfig,
)
from pg_mcp.models.query import ResultValidationResult
from pg_mcp.models.schema import ColumnInfo, DatabaseSchema, TableInfo
from pg_mcp.prompts.result_validation import RESULT_VALIDATION_SYSTEM_PROMPT
from pg_mcp.services.anthropic_generator import AnthropicSQLGenerator
from pg_mcp.services.anthropic_result_validator import AnthropicResultValidator
from pg_mcp.services.llm_factory import create_result_validator, create_sql_generator
from pg_mcp.services.result_validator import ResultValidator
from pg_mcp.services.sql_generator import SQLGenerator


def _text_block(text: str) -> MagicMock:
    """Build a mock Anthropic content block."""
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _schema() -> DatabaseSchema:
    """Build a real minimal schema for prompt rendering."""

    return DatabaseSchema(
        database_name="test_db",
        tables=[
            TableInfo(
                schema_name="public",
                table_name="users",
                columns=[
                    ColumnInfo(name="id", data_type="integer", is_nullable=False),
                ],
            )
        ],
        version="15.0",
    )


def _settings(provider: str) -> Settings:
    """Settings with the given provider and dummy keys."""
    return Settings(
        llm=LLMProviderConfig(provider=provider),  # type: ignore[arg-type]
        openai=OpenAIConfig(api_key=SecretStr("sk-test")),
        anthropic=AnthropicConfig(api_key=SecretStr("ant-test"), model="claude-haiku-4-5"),
        validation=ValidationConfig(enabled=True),
        _env_file=None,
    )


class TestFactory:
    """Tests for provider-based factory selection."""

    def test_openai_provider_builds_openai_services(self) -> None:
        settings = _settings("openai")
        assert type(create_sql_generator(settings)) is SQLGenerator
        assert type(create_result_validator(settings)) is ResultValidator

    def test_anthropic_provider_builds_anthropic_services(self) -> None:
        settings = _settings("anthropic")
        assert isinstance(create_sql_generator(settings), AnthropicSQLGenerator)
        assert isinstance(create_result_validator(settings), AnthropicResultValidator)

    def test_unknown_provider_rejected(self) -> None:
        settings = _settings("openai")
        settings.llm.provider = "unknown"  # type: ignore[assignment]
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            create_sql_generator(settings)


class TestAnthropicSQLGenerator:
    """Tests for the Claude-backed SQL generator."""

    def _generator(self) -> AnthropicSQLGenerator:
        settings = _settings("anthropic")
        return AnthropicSQLGenerator(settings.anthropic, settings.openai)

    @pytest.mark.asyncio
    async def test_generate_extracts_sql_from_text_block(self) -> None:
        generator = self._generator()

        response = MagicMock(content=[_text_block("```sql\nSELECT COUNT(*) FROM users;\n```")])
        generator.client.messages.create = AsyncMock(return_value=response)

        sql = await generator.generate(question="how many users?", schema=_schema())

        assert sql == "SELECT COUNT(*) FROM users;"
        generator.client.messages.create.assert_awaited_once()
        kwargs = generator.client.messages.create.await_args.kwargs
        assert kwargs["model"] == "claude-haiku-4-5"
        assert kwargs["max_tokens"] == 2000

    @pytest.mark.asyncio
    async def test_generate_raises_on_empty_content(self) -> None:
        from pg_mcp.models.errors import LLMError

        generator = self._generator()
        generator.client.messages.create = AsyncMock(
            return_value=MagicMock(content=[_text_block("")])
        )

        with pytest.raises(LLMError, match="empty message content"):
            await generator.generate(question="q", schema=_schema())


class TestAnthropicResultValidator:
    """Tests for the Claude-backed result validator."""

    def _validator(self) -> AnthropicResultValidator:
        settings = _settings("anthropic")
        return AnthropicResultValidator(settings.anthropic, settings.openai, settings.validation)

    @pytest.mark.asyncio
    async def test_validate_parses_json_response(self) -> None:
        validator = self._validator()

        validator.client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[_text_block('{"confidence": 88, "explanation": "matches"}')]
            )
        )

        result = await validator.validate(
            question="how many users?",
            sql="SELECT COUNT(*) FROM users",
            results=[{"count": 5}],
            row_count=1,
        )

        assert isinstance(result, ResultValidationResult)
        assert result.confidence == 88
        assert result.is_acceptable is True
        # System prompt must instruct JSON-only output (replaces OpenAI
        # response_format={"type": "json_object"})
        sent_system = validator.client.messages.create.await_args.kwargs["system"]
        assert "JSON" in sent_system
        assert sent_system.startswith(RESULT_VALIDATION_SYSTEM_PROMPT[:20])

    @pytest.mark.asyncio
    async def test_validate_handles_fenced_json(self) -> None:
        validator = self._validator()

        validator.client.messages.create = AsyncMock(
            return_value=MagicMock(
                content=[_text_block('```json\n{"confidence": 40, "explanation": "mismatch"}\n```')]
            )
        )

        result = await validator.validate(
            question="q",
            sql="SELECT 1",
            results=[{"a": 1}],
            row_count=1,
        )
        assert result.confidence == 40
        assert result.is_acceptable is False

"""Anthropic Claude implementation of LLM-based result validation.

Mirrors :mod:`pg_mcp.services.anthropic_generator`: the prompt, JSON
parsing, and confidence-thresholding pipeline is shared with the OpenAI
implementation; only the provider call differs.
"""

import json
from typing import Any

from pg_mcp.config.settings import AnthropicConfig, OpenAIConfig
from pg_mcp.services.anthropic_generator import build_anthropic_client
from pg_mcp.services.result_validator import ResultValidator


class AnthropicResultValidator(ResultValidator):
    """Result validator backed by the Anthropic Claude API."""

    def __init__(
        self,
        anthropic_config: AnthropicConfig,
        openai_config: OpenAIConfig,
        validation_config: Any,
    ) -> None:
        """Initialize the Claude-backed result validator.

        Args:
            anthropic_config: Anthropic API settings (key, model, timeout).
            openai_config: Retained for interface compatibility; the
                validation pipeline reads thresholds from validation_config.
            validation_config: Validation settings (thresholds, timeouts).
        """
        super().__init__(openai_config, validation_config)
        self.anthropic_config = anthropic_config
        self.client = build_anthropic_client(anthropic_config)

    async def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """Send a messages request to the Anthropic API.

        The system prompt instructs the model to answer with a JSON object,
        which replaces OpenAI's ``response_format={"type": "json_object"}``.

        Args:
            system_prompt: System instruction prompt.
            user_prompt: Validation prompt with question/sql/results.

        Returns:
            str: Raw text content from the model.
        """
        response = await self.client.messages.create(
            model=self.anthropic_config.model,
            system=system_prompt + "\nRespond with ONLY a JSON object.",
            messages=[{"role": "user", "content": user_prompt}],
            max_tokens=500,
        )
        for block in response.content:
            if getattr(block, "type", None) == "text" and block.text:
                # Guard against fenced JSON (```json ... ```)
                text = block.text.strip()
                if text.startswith("```"):
                    text = text.strip("`")
                    if text.startswith("json"):
                        text = text[4:]
                    text = text.strip()
                json.loads(text)  # fail fast on invalid JSON
                return text
        raise ValueError("Anthropic returned empty message content for result validation")

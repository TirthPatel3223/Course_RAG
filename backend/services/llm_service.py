"""
LLM Service — Claude (primary) + OpenAI (fallback).
Provides a unified interface for LLM calls with automatic failover.
"""

import logging
from typing import Optional

from anthropic import AsyncAnthropic, APIError as AnthropicAPIError
from openai import AsyncOpenAI, APIError as OpenAIAPIError

from backend.config import get_settings

logger = logging.getLogger(__name__)


class LLMService:
    """
    Unified LLM service with Claude as primary and OpenAI as fallback.

    Usage:
        llm = LLMService()
        response = await llm.chat(messages=[{"role": "user", "content": "Hello"}])
        response = await llm.chat_structured(messages, response_format=MyModel)
    """

    def __init__(self):
        settings = get_settings()
        self._anthropic: Optional[AsyncAnthropic] = None
        self._openai: Optional[AsyncOpenAI] = None

        # Initialize Anthropic client if key is available
        if settings.anthropic_api_key:
            self._anthropic = AsyncAnthropic(api_key=settings.anthropic_api_key)
            logger.info("Anthropic client initialized (Claude primary)")
        else:
            logger.warning("No Anthropic API key — Claude unavailable")

        # Initialize OpenAI client if key is available
        if settings.openai_api_key:
            self._openai = AsyncOpenAI(api_key=settings.openai_api_key)
            logger.info("OpenAI client initialized (fallback)")
        else:
            logger.warning("No OpenAI API key — fallback unavailable")

        self._claude_model = settings.claude_model
        self._openai_model = settings.openai_chat_model

    async def chat(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> dict:
        """
        Send a chat completion request. Tries Claude first, falls back to OpenAI.

        Args:
            messages: List of message dicts [{"role": "user", "content": "..."}]
            system_prompt: Optional system prompt (handled differently per provider)
            max_tokens: Maximum tokens in response
            temperature: Sampling temperature

        Returns:
            dict with keys:
                - "content": str — The response text
                - "provider": str — "claude" or "openai"
                - "model": str — The model used
                - "usage": dict — Token usage info
        """
        # Try Claude first
        if self._anthropic:
            try:
                return await self._call_claude(
                    messages, system_prompt, max_tokens, temperature
                )
            except Exception as e:
                logger.warning(f"Claude failed: {e}. Falling back to OpenAI.")

        # Fallback to OpenAI
        if self._openai:
            try:
                return await self._call_openai(
                    messages, system_prompt, max_tokens, temperature
                )
            except Exception as e:
                logger.error(f"OpenAI also failed: {e}")
                raise RuntimeError(f"Both LLM providers failed. Last error: {e}")

        raise RuntimeError("No LLM provider available. Check your API keys in .env")

    async def _call_claude(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """Call Claude API."""
        kwargs = {
            "model": self._claude_model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = await self._anthropic.messages.create(**kwargs)

        # Extract text from content blocks
        content = ""
        for block in response.content:
            if block.type == "text":
                content += block.text

        return {
            "content": content,
            "provider": "claude",
            "model": response.model,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
        }

    async def _call_openai(
        self,
        messages: list[dict],
        system_prompt: Optional[str],
        max_tokens: int,
        temperature: float,
    ) -> dict:
        """Call OpenAI API."""
        # Prepend system message if provided
        full_messages = []
        if system_prompt:
            full_messages.append({"role": "system", "content": system_prompt})
        full_messages.extend(messages)

        response = await self._openai.chat.completions.create(
            model=self._openai_model,
            messages=full_messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )

        choice = response.choices[0]
        return {
            "content": choice.message.content or "",
            "provider": "openai",
            "model": response.model,
            "usage": {
                "input_tokens": response.usage.prompt_tokens,
                "output_tokens": response.usage.completion_tokens,
            },
        }

    async def chat_with_json(
        self,
        messages: list[dict],
        system_prompt: Optional[str] = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> dict:
        """
        Same as chat(), but instructs the LLM to respond in JSON format.
        Appends JSON instruction to the system prompt.
        """
        json_instruction = (
            "\n\nYou MUST respond with valid JSON only. "
            "Do not include any text outside the JSON object."
        )
        effective_system = (system_prompt or "") + json_instruction

        response = await self.chat(
            messages=messages,
            system_prompt=effective_system,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        
        content = response.get("content", "").strip()
        if content.startswith("```json"):
            content = content[7:]
        elif content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
            
        response["content"] = content.strip()
        return response

    @property
    def has_claude(self) -> bool:
        return self._anthropic is not None

    @property
    def has_openai(self) -> bool:
        return self._openai is not None

    @property
    def available_providers(self) -> list[str]:
        providers = []
        if self.has_claude:
            providers.append("claude")
        if self.has_openai:
            providers.append("openai")
        return providers


# ──────────────────────────────────────────────
# Module-level singleton
# ──────────────────────────────────────────────
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get or create the singleton LLMService instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service

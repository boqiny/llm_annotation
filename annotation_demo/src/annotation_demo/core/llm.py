"""
Core LLM interface for annotation_demo.

This module defines a reusable LLM abstraction used by prompt generation,
annotation, reflection agents, and future optimization modules.

Design goals:
- Keep provider-specific logic behind a common interface.
- Support both synchronous and asynchronous calls.
- Keep prompts external to the LLM class; callers pass messages explicitly.
- Provide optional JSON parsing for structured LLM outputs.
- Return consistent metadata such as provider, model, raw output, and usage.

# TODO(v1): Replace best-effort parsed_json handling with strict annotation
# schema validation once the frontend/backend response contract is finalized.
"""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from anthropic import Anthropic, AsyncAnthropic
from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

load_dotenv()


Message = dict[str, str]


@dataclass
class LLMUsage:
    """Token usage metadata returned by an LLM provider.

    Fields may be None when the provider does not report token usage or when usage
    information is unavailable for a specific request.
    """
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMResponse:
    """Normalized response object returned by all LLM clients.

    Attributes:
        text: Raw text returned by the provider.
        parsed_json: Parsed JSON object when JSON parsing succeeds; otherwise None.
        usage: Optional token usage metadata.
        raw: Provider-specific raw metadata useful for debugging.
    """
    raw: str
    parsed: Optional[dict[str, Any]] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    usage: Optional[LLMUsage] = None


class BaseLLM(ABC):
    """Abstract interface for asynchronous LLM clients.

    Implementations should accept role-based messages and return an LLMResponse.
    The interface is intentionally small so annotation components can remain
    provider-independent.
    """

    provider: str

    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        seed: Optional[int] = 42,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.seed = seed

    @abstractmethod
    def generate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        """Synchronous LLM call."""
        raise NotImplementedError

    @abstractmethod
    async def agenerate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        """Asynchronous LLM call."""
        raise NotImplementedError

    def generate_json(self, messages: list[Message]) -> dict[str, Any]:
        response = self.generate(messages, json_mode=True)
        if response.parsed is None:
            response.parsed = extract_json(response.raw)
        return response.parsed

    async def agenerate_json(self, messages: list[Message]) -> dict[str, Any]:
        response = await self.agenerate(messages, json_mode=True)
        if response.parsed is None:
            response.parsed = extract_json(response.raw)
        return response.parsed


class OpenAILLM(BaseLLM):
    provider = "openai"

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        seed: Optional[int] = 42,
        client: Optional[OpenAI] = None,
        async_client: Optional[AsyncOpenAI] = None,
    ) -> None:
        super().__init__(
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
        )
        self.client = client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        self.async_client = async_client or AsyncOpenAI(
            api_key=os.getenv("OPENAI_API_KEY")
        )

    def generate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, json_mode=json_mode)
        response = self.client.chat.completions.create(**kwargs)
        return self._parse_response(response, json_mode=json_mode)

    async def agenerate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        kwargs = self._build_kwargs(messages, json_mode=json_mode)
        response = await self.async_client.chat.completions.create(**kwargs)
        return self._parse_response(response, json_mode=json_mode)

    def _build_kwargs(
        self,
        messages: list[Message],
        json_mode: bool,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }

        if self.seed is not None:
            kwargs["seed"] = self.seed

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        return kwargs

    def _parse_response(self, response: Any, json_mode: bool) -> LLMResponse:
        raw = response.choices[0].message.content or ""

        usage = None
        if getattr(response, "usage", None) is not None:
            usage = LLMUsage(
                input_tokens=getattr(response.usage, "prompt_tokens", 0) or 0,
                output_tokens=getattr(response.usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(response.usage, "total_tokens", 0) or 0,
            )

        return LLMResponse(
            raw=raw,
            parsed=extract_json(raw) if json_mode else None,
            provider=self.provider,
            model=self.model,
            usage=usage,
        )


class AnthropicLLM(BaseLLM):
    provider = "anthropic"

    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        client: Optional[Anthropic] = None,
        async_client: Optional[AsyncAnthropic] = None,
    ) -> None:
        super().__init__(
            model=model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            temperature=temperature,
            max_tokens=max_tokens,
            seed=None,
        )
        self.client = client or Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
        self.async_client = async_client or AsyncAnthropic(
            api_key=os.getenv("ANTHROPIC_API_KEY")
        )

    def generate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        system_prompt, non_system_messages = split_system_messages(messages)

        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt if system_prompt else None,
            messages=non_system_messages,
        )

        return self._parse_response(response, json_mode=json_mode)

    async def agenerate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        system_prompt, non_system_messages = split_system_messages(messages)

        response = await self.async_client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt if system_prompt else None,
            messages=non_system_messages,
        )

        return self._parse_response(response, json_mode=json_mode)

    def _parse_response(self, response: Any, json_mode: bool) -> LLMResponse:
        raw = "".join(getattr(block, "text", "") for block in response.content)

        usage = None
        if getattr(response, "usage", None) is not None:
            input_tokens = getattr(response.usage, "input_tokens", 0) or 0
            output_tokens = getattr(response.usage, "output_tokens", 0) or 0
            usage = LLMUsage(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=input_tokens + output_tokens,
            )

        return LLMResponse(
            raw=raw,
            parsed=extract_json(raw) if json_mode else None,
            provider=self.provider,
            model=self.model,
            usage=usage,
        )


def make_llm(
    provider: str = "openai",
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> BaseLLM:
    """Create an LLM client from provider and model configuration.

    Args:
        provider: Provider name, such as "openai" or "anthropic".
        model: Model name. If None, the provider default is used.
        temperature: Sampling temperature.
        max_tokens: Maximum number of output tokens.

    Returns:
        A provider-specific LLM client implementing the shared async interface.

    Raises:
        ValueError: If the provider is unsupported.
    """
    provider = provider.lower()

    if provider == "openai":
        return OpenAILLM(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    if provider == "anthropic":
        return AnthropicLLM(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

    raise ValueError(f"Unknown LLM provider: {provider!r}")


def extract_json(text: str) -> dict[str, Any]:
    """Best-effort extraction of a JSON object from model text.

    This helper is intended for providers or model settings that do not enforce
    native JSON output. It first attempts to parse the full response as JSON and
    then falls back to extracting the largest JSON-looking object.

    This is not a full schema validator. Downstream code should validate the parsed
    object against the expected annotation schema.
    """

    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in LLM output: {text[:200]!r}")

    return json.loads(match.group(0))


def split_system_messages(messages: list[Message]) -> tuple[str, list[Message]]:
    system_parts: list[str] = []
    non_system_messages: list[Message] = []

    for message in messages:
        role = (message.get("role") or "").strip()
        content = message.get("content") or ""

        if role == "system":
            system_parts.append(content)
        else:
            non_system_messages.append({"role": role, "content": content})

    return "\n\n".join(system_parts).strip(), non_system_messages

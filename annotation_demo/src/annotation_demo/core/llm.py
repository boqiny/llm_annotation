from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Optional

from dotenv import load_dotenv
from openai import OpenAI
from anthropic import Anthropic

load_dotenv()


Message = dict[str, str]


@dataclass
class LLMResponse:
    raw: str
    parsed: Optional[dict[str, Any]] = None
    model: Optional[str] = None
    provider: Optional[str] = None


class BaseLLM(ABC):
    def __init__(
        self,
        model: str,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        seed: Optional[int] = 42,
    ):
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
        pass

    def generate_json(self, messages: list[Message]) -> dict[str, Any]:
        response = self.generate(messages, json_mode=True)
        if response.parsed is None:
            response.parsed = extract_json(response.raw)
        return response.parsed


class OpenAILLM(BaseLLM):
    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        seed: Optional[int] = 42,
        client: Optional[OpenAI] = None,
    ):
        super().__init__(
            model=model or os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
            temperature=temperature,
            max_tokens=max_tokens,
            seed=seed,
        )
        self.client = client or OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    def generate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
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

        resp = self.client.chat.completions.create(**kwargs)
        raw = resp.choices[0].message.content or ""

        parsed = extract_json(raw) if json_mode else None

        return LLMResponse(
            raw=raw,
            parsed=parsed,
            model=self.model,
            provider="openai",
        )


class AnthropicLLM(BaseLLM):
    def __init__(
        self,
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: int = 1024,
        client: Optional[Anthropic] = None,
    ):
        super().__init__(
            model=model or os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5"),
            temperature=temperature,
            max_tokens=max_tokens,
            seed=None,
        )
        self.client = client or Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    def generate(
        self,
        messages: list[Message],
        json_mode: bool = False,
    ) -> LLMResponse:
        system_prompt, non_system_messages = split_system_messages(messages)

        resp = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt if system_prompt else None,
            messages=non_system_messages,
        )

        raw = "".join(getattr(block, "text", "") for block in resp.content)
        parsed = extract_json(raw) if json_mode else None

        return LLMResponse(
            raw=raw,
            parsed=parsed,
            model=self.model,
            provider="anthropic",
        )


def make_llm(
    provider: str = "openai",
    model: Optional[str] = None,
    temperature: float = 0.0,
    max_tokens: int = 1024,
) -> BaseLLM:
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
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError(f"No JSON found in output: {text[:200]!r}")

    return json.loads(match.group(0))


def split_system_messages(messages: list[Message]) -> tuple[str, list[Message]]:
    system_parts: list[str] = []
    non_system: list[Message] = []

    for message in messages:
        role = (message.get("role") or "").strip()
        content = message.get("content") or ""

        if role == "system":
            system_parts.append(content)
        else:
            non_system.append({"role": role, "content": content})

    return "\n\n".join(system_parts).strip(), non_system

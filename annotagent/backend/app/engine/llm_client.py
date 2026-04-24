"""Thin async wrapper around OpenAI and Anthropic APIs."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import openai
import anthropic

from app.utils.cost_tracker import estimate_cost

logger = logging.getLogger(__name__)

# Errors worth retrying: transient network / rate limit / 5xx. Auth/400 are not.
_RETRYABLE = (
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


@dataclass
class LLMResponse:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    model: str = ""
    cost_usd: float = 0.0


def _uses_new_params(model: str) -> bool:
    """New OpenAI families (gpt-5.*, o1.*, o3.*, o4.*) use max_completion_tokens
    and don't accept a custom temperature. Older families (gpt-4*, gpt-3.5*) use
    max_tokens and accept temperature."""
    m = (model or "").lower()
    return m.startswith(("gpt-5", "o1", "o3", "o4"))


async def call_openai(
    messages: list[dict[str, str]],
    model: str = "gpt-5.4-mini",
    api_key: str = "",
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> LLMResponse:
    client = openai.AsyncOpenAI(api_key=api_key)
    kwargs: dict = {"model": model, "messages": messages}
    if _uses_new_params(model):
        kwargs["max_completion_tokens"] = max_tokens
        # temperature intentionally omitted — new reasoning models reject non-default values
    else:
        kwargs["max_tokens"] = max_tokens
        kwargs["temperature"] = temperature
    resp = await client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    usage = resp.usage
    in_tok = usage.prompt_tokens if usage else 0
    out_tok = usage.completion_tokens if usage else 0
    return LLMResponse(
        text=choice.message.content or "",
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=model,
        cost_usd=estimate_cost(model, in_tok, out_tok),
    )


async def call_anthropic(
    messages: list[dict[str, str]],
    model: str = "claude-sonnet-4-5-20250929",
    api_key: str = "",
    temperature: float = 0.0,
    max_tokens: int = 512,
    system: str = "",
) -> LLMResponse:
    client = anthropic.AsyncAnthropic(api_key=api_key)
    user_messages = [m for m in messages if m["role"] != "system"]
    sys_content = system
    if not sys_content:
        sys_msgs = [m for m in messages if m["role"] == "system"]
        if sys_msgs:
            sys_content = sys_msgs[0]["content"]

    resp = await client.messages.create(
        model=model,
        system=sys_content,
        messages=user_messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    text = resp.content[0].text if resp.content else ""
    in_tok = resp.usage.input_tokens
    out_tok = resp.usage.output_tokens
    return LLMResponse(
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=model,
        cost_usd=estimate_cost(model, in_tok, out_tok),
    )


async def call_llm(
    messages: list[dict[str, str]],
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
    temperature: float = 0.0,
    max_tokens: int = 512,
    max_retries: int = 3,
) -> LLMResponse:
    """Unified LLM call dispatcher with exponential backoff on transient failures."""
    delay = 1.0
    last_err: Exception | None = None
    for attempt in range(max_retries + 1):
        try:
            if provider == "anthropic":
                return await call_anthropic(
                    messages=messages, model=model, api_key=api_key,
                    temperature=temperature, max_tokens=max_tokens,
                )
            return await call_openai(
                messages=messages, model=model, api_key=api_key,
                temperature=temperature, max_tokens=max_tokens,
            )
        except _RETRYABLE as e:
            last_err = e
            if attempt == max_retries:
                break
            logger.warning(f"LLM call failed (attempt {attempt + 1}/{max_retries + 1}): {e}. Retrying in {delay:.1f}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30.0)
    raise last_err if last_err else RuntimeError("LLM call failed with no captured error")

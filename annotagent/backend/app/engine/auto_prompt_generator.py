"""LLM-driven annotation-prompt generation from a codebook.

Ported from ``annotation_demo/src/annotation_demo/tasks/prompt_generator.py`` —
adapted to use the project's existing ``call_llm`` async dispatcher (with retry
+ cost tracking) instead of introducing a parallel BaseLLM hierarchy.

Use case (per project notes): the deterministic Jinja prompts in
``prompt_generator.py`` are the "gallery" / preset prompts. This module
generates prompts for a user's *custom* codebook by asking an LLM to write a
fit-for-purpose annotation prompt from the codebook structure.
"""
from __future__ import annotations

import json
from typing import Any

from app.engine.llm_client import call_llm
from app.engine.prompt_renderer import render_template


async def agenerate_prompt_from_codebook(
    codebook: dict[str, Any],
    task_type: str,
    *,
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
    max_tokens: int = 2048,
) -> str:
    """Generate one annotation prompt for the whole codebook (single-step task).

    Mirrors annotation_demo's ``generate_annotation_prompt`` design: feeds
    ``task_type`` + serialized codebook into ``auto_prompt_generator.jinja`` and
    returns the LLM's response verbatim.
    """
    system_prompt = render_template(
        "auto_prompt_generator.jinja",
        task_type=task_type,
        codebook=json.dumps(codebook, indent=2, ensure_ascii=False),
    )
    response = await call_llm(
        messages=[{"role": "system", "content": system_prompt}],
        provider=provider,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
    )
    return response.text.strip()

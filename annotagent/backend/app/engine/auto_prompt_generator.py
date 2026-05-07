"""LLM-driven annotation-prompt generation from a codebook.

Ported from ``annotation_demo/src/annotation_demo/tasks/prompt_generator.py`` —
adapted to use the project's existing ``call_llm`` async dispatcher (with retry
+ cost tracking) instead of introducing a parallel BaseLLM hierarchy.

Use case (per project notes): the deterministic Jinja prompts in
``prompt_generator.py`` are the "gallery" / preset prompts. This module
generates prompts for a user's *custom* codebook by asking an LLM to write a
fit-for-purpose annotation prompt for *each dimension* of the codebook. Per-
dimension generation matches the existing pipeline architecture (multi-step
runner, per-dimension optimizer) and lets each prompt be optimized
independently.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from app.engine.codebook_parser import DimensionDef
from app.engine.llm_client import call_llm
from app.engine.prompt_renderer import render_template


def _dimension_payload(dim: DimensionDef) -> dict[str, Any]:
    """Convert a DimensionDef into the JSON shape fed to the meta-prompt."""
    return {
        "dimension_name": dim.name,
        "type": dim.dim_type,
        "instructions": dim.instructions or "",
        "labels": [
            {
                "name": lbl.name,
                "definition": lbl.definition,
                "examples": lbl.examples,
            }
            for lbl in dim.labels
        ],
    }


async def agenerate_prompt_from_dimension(
    dim: DimensionDef,
    task_type: str,
    *,
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
    max_tokens: int = 2048,
) -> str:
    """Generate one annotation prompt for a single dimension."""
    system_prompt = render_template(
        "auto_prompt_generator.jinja",
        task_type=f"{task_type} — single dimension: {dim.name}",
        codebook=json.dumps(_dimension_payload(dim), indent=2, ensure_ascii=False),
    )
    response = await call_llm(
        messages=[{"role": "system", "content": system_prompt}],
        provider=provider,
        model=model,
        api_key=api_key,
        max_tokens=max_tokens,
    )
    return response.text.strip()


async def agenerate_prompts_per_dimension(
    dimensions: list[DimensionDef],
    task_type: str,
    *,
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
    max_tokens: int = 2048,
) -> list[tuple[str, str | Exception]]:
    """Generate per-dimension prompts in parallel.

    Returns a list of ``(dimension_name, prompt_or_exception)`` so callers can
    surface partial failures without aborting the whole batch.
    """
    coros = [
        agenerate_prompt_from_dimension(
            dim, task_type,
            provider=provider, model=model, api_key=api_key, max_tokens=max_tokens,
        )
        for dim in dimensions
    ]
    results = await asyncio.gather(*coros, return_exceptions=True)
    return [(dim.name, res) for dim, res in zip(dimensions, results)]

"""
Annotation task.

This module applies a versioned annotation prompt to input items and produces
LLM-based annotation results.

Responsibilities:
- Render annotator prompts for each item.
- Call the shared LLM interface.
- Parse structured annotation outputs.
- Support batch annotation logic.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from annotation_demo.core.llm import BaseLLM
from annotation_demo.prompts.renderer import render_template


def annotate_items(
    items: list[dict[str, Any]],
    annotation_prompt: str,
    llm: BaseLLM,
) -> list[dict[str, Any]]:
    """Annotate a batch of items with the configured LLM.

    Args:
        llm: Provider-agnostic async LLM client.
        codebook: Codebook used to render annotation instructions.
        items: Items to annotate.
        task_config: Task configuration controlling prompt and decoding behavior.

    Returns:
        A list of per-item annotation records containing the original item,
        raw model output, and parsed prediction when available.
    """
    results = []

    for item in items:
        system_prompt = render_template(
            "annotator.jinja",
            annotation_prompt=annotation_prompt,
            item=item,
        )

        response = llm.generate(
            messages=[
                {"role": "system", "content": system_prompt},
            ],
            json_mode=True,
        )

        results.append(
            {
                "item": item,
                "prediction": response.parsed,
                "raw_output": response.raw,
            }
        )

    return results


async def annotate_items_async(
    items: list[dict[str, Any]],
    annotation_prompt: str,
    llm: BaseLLM,
    concurrency: int = 5,
    max_retries: int = 2,
    on_progress: Callable[[float], None] | None = None,
) -> list[dict[str, Any]]:
    """Annotate items concurrently with bounded parallelism and per-item retry.

    Failed items (after all retries) are recorded with prediction=None and an
    "error" key rather than raising, so one bad item never aborts the batch.
    Retries use exponential backoff: 1 s, 2 s, 4 s, …
    """
    semaphore = asyncio.Semaphore(concurrency)
    results: list[dict[str, Any] | None] = [None] * len(items)
    completed = 0

    async def _annotate_one(i: int, item: dict[str, Any]) -> None:
        nonlocal completed
        async with semaphore:
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    system_prompt = render_template(
                        "annotator.jinja",
                        annotation_prompt=annotation_prompt,
                        item=item,
                    )
                    response = await llm.agenerate(
                        messages=[{"role": "system", "content": system_prompt}],
                        json_mode=True,
                    )
                    results[i] = {
                        "item": item,
                        "prediction": response.parsed,
                        "raw_output": response.raw,
                    }
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        await asyncio.sleep(2 ** attempt)
            else:
                results[i] = {
                    "item": item,
                    "prediction": None,
                    "raw_output": None,
                    "error": repr(last_exc),
                }
            completed += 1
            if on_progress is not None:
                on_progress(completed / len(items))

    await asyncio.gather(*[_annotate_one(i, item) for i, item in enumerate(items)])
    return results  # type: ignore[return-value]

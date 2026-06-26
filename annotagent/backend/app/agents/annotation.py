"""Annotation Agent -- per-item annotation through pipeline steps."""
from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Optional

from app.engine.llm_client import call_llm
from app.engine.label_parser import parse_answer


def _norm(s: str) -> str:
    """Casefold + de-plural for matching a predicted gate value to a gate key."""
    t = re.sub(r"[^0-9a-z]+", " ", str(s or "").casefold()).strip()
    return " ".join(re.sub(r"s\b", "", w) or w for w in t.split())


def _match_gate_key(value: str, keys: dict[str, Any]) -> Optional[str]:
    """Find the conditional key matching a predicted gate value (case/plural-insensitive)."""
    nv = _norm(value)
    for k in keys:
        if _norm(k) == nv:
            return k
    return None


@dataclass
class AnnotationItemResult:
    item_index: int
    content: str
    labels: dict[str, str] = field(default_factory=dict)
    reasoning: dict[str, str] = field(default_factory=dict)
    tokens_used: int = 0
    skipped_steps: list[str] = field(default_factory=list)


async def annotate_item(
    content: str,
    context: str,
    item_index: int,
    steps: list[dict[str, Any]],
    codebook_dims: dict[str, list[str]],
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
) -> AnnotationItemResult:
    """Annotate a single item through all pipeline steps."""
    result = AnnotationItemResult(item_index=item_index, content=content)
    total_tokens = 0
    gated_out = False

    for step in steps:
        if gated_out:
            result.skipped_steps.append(step["name"])
            continue

        prompt = step.get("prompt", "")
        # Conditional cascade: if this step is gated by an already-predicted
        # dimension, swap in the gate-value-specific prompt and narrow the valid
        # label set so only that gate value's labels can be chosen.
        narrowed_labels: Optional[list[str]] = None
        gate_by = step.get("gate_by")
        if gate_by and gate_by in result.labels:
            gate_val = result.labels[gate_by]
            cond_prompts = step.get("conditional_prompts") or {}
            key = _match_gate_key(gate_val, cond_prompts)
            if key is not None:
                prompt = cond_prompts[key]
                narrowed_labels = (step.get("conditional_labels") or {}).get(key)

        user_msg = f"Sentence: {content}"
        if context:
            user_msg = f"Context: {context}\n\n{user_msg}"

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ]

        resp = await call_llm(
            messages=messages,
            provider=provider,
            model=model,
            api_key=api_key,
            max_tokens=512,
        )

        total_tokens += resp.input_tokens + resp.output_tokens

        for dim_name in step.get("dimensions", []):
            valid_labels = narrowed_labels if narrowed_labels is not None else codebook_dims.get(dim_name, [])
            is_binary = len(valid_labels) == 2 and any("yes" in l.lower() for l in valid_labels)
            label = parse_answer(resp.text, valid_labels, is_binary=is_binary)
            result.labels[dim_name] = label
            result.reasoning[dim_name] = resp.text

        # Derived outputs: a value computed from another dimension's prediction
        # (e.g. the topic's parent thematic category), not a separate LLM call.
        for derived in step.get("derived_dimensions", []):
            src = result.labels.get(derived.get("from", ""), "")
            mapping = derived.get("map") or {}
            value = mapping.get(src, "")
            if not value:  # tolerate case/spacing drift in the predicted leaf
                value = next((v for k, v in mapping.items() if k.lower() == src.lower()), "")
            result.labels[derived["name"]] = value
            result.reasoning[derived["name"]] = f"Derived from {derived.get('from','')} = {src!r}"

        gate_dim = step.get("gate")
        if gate_dim and gate_dim in result.labels:
            gate_val = result.labels[gate_dim].lower()
            if gate_val in ("no", "n/a", "none"):
                gated_out = True

    result.tokens_used = total_tokens
    return result


async def annotate_batch(
    items: list[dict[str, Any]],
    steps: list[dict[str, Any]],
    codebook_dims: dict[str, list[str]],
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
    max_concurrency: int = 10,
    progress_callback: Optional[Any] = None,
) -> list[AnnotationItemResult]:
    """Annotate a batch of items with concurrency control."""
    semaphore = asyncio.Semaphore(max_concurrency)

    async def _process(item: dict[str, Any], idx: int) -> AnnotationItemResult:
        async with semaphore:
            res = await annotate_item(
                content=item.get("content", ""),
                context=item.get("context", ""),
                item_index=idx,
                steps=steps,
                codebook_dims=codebook_dims,
                provider=provider,
                model=model,
                api_key=api_key,
            )
            if progress_callback:
                await progress_callback(idx, res)
            return res

    tasks = [_process(item, i) for i, item in enumerate(items)]
    results = await asyncio.gather(*tasks)
    return list(results)

"""Decomposition Agent -- splits codebook dimensions into pipeline steps."""
from __future__ import annotations

import json
from typing import Any

from app.engine.codebook_parser import CodebookDef
from app.engine.llm_client import call_llm
from app.engine.prompt_generator import generate_step_prompt


async def decompose_codebook(
    codebook: CodebookDef,
    provider: str = "openai",
    model: str = "gpt-5.4-mini",
    api_key: str = "",
) -> list[dict[str, Any]]:
    """Decompose a codebook into ordered pipeline steps.

    If the codebook includes decomposition_hints, use those directly.
    Otherwise, ask the LLM to group dimensions to minimize interference.
    """
    if codebook.decomposition_hints:
        return _steps_from_hints(codebook)

    if len(codebook.dimensions) <= 1:
        dim = codebook.dimensions[0] if codebook.dimensions else None
        if dim is None:
            return []
        prompt = generate_step_prompt([dim], step_name=dim.name)
        return [{
            "name": dim.name,
            "dimensions": [dim.name],
            "prompt": prompt,
            "gate": None,
        }]

    return await _llm_decompose(codebook, provider, model, api_key)


def _steps_from_hints(codebook: CodebookDef) -> list[dict[str, Any]]:
    """Build steps from codebook.decomposition_hints."""
    hints = codebook.decomposition_hints
    groups = hints.get("groups", [])
    order = hints.get("order", [])
    dim_map = {d.name: d for d in codebook.dimensions}

    steps = []
    for i, group in enumerate(groups):
        dims = [dim_map[name] for name in group if name in dim_map]
        if not dims:
            continue
        step_name = order[i] if i < len(order) else "+".join(group)
        prompt = generate_step_prompt(dims, step_name=step_name)
        steps.append({
            "name": step_name,
            "dimensions": [d.name for d in dims],
            "prompt": prompt,
            "gate": None,
        })
    return steps


async def _llm_decompose(
    codebook: CodebookDef,
    provider: str,
    model: str,
    api_key: str,
) -> list[dict[str, Any]]:
    """Use LLM meta-prompt to detect dimension interference and create groups."""
    dim_summaries = "\n".join(
        f"- {d.name} ({d.dim_type}): {len(d.labels)} labels"
        for d in codebook.dimensions
    )

    meta_prompt = (
        "You are an expert at designing multi-step annotation pipelines.\n\n"
        f"Given these annotation dimensions:\n{dim_summaries}\n\n"
        "Group them into pipeline steps to minimize cross-dimensional interference.\n"
        "Dimensions that might confuse each other should be in separate steps.\n"
        "Dimensions that are conceptually related and benefit from joint context can be grouped.\n\n"
        "Return a JSON array of steps, where each step has:\n"
        '- "name": step name\n'
        '- "dimensions": list of dimension names in that step\n'
        '- "gate": null or a dimension name whose "No"/"N/A" answer should skip later steps\n\n'
        "Return ONLY the JSON array, no explanation."
    )

    resp = await call_llm(
        messages=[
            {"role": "system", "content": "You are an annotation pipeline designer."},
            {"role": "user", "content": meta_prompt},
        ],
        provider=provider, model=model, api_key=api_key, max_tokens=1024,
    )

    try:
        raw_steps = json.loads(resp.text)
    except json.JSONDecodeError:
        raw_steps = [{"name": d.name, "dimensions": [d.name], "gate": None} for d in codebook.dimensions]

    dim_map = {d.name: d for d in codebook.dimensions}
    steps = []
    for raw in raw_steps:
        dims = [dim_map[n] for n in raw.get("dimensions", []) if n in dim_map]
        if not dims:
            continue
        prompt = generate_step_prompt(dims, step_name=raw.get("name", ""))
        steps.append({
            "name": raw.get("name", "+".join(d.name for d in dims)),
            "dimensions": [d.name for d in dims],
            "prompt": prompt,
            "gate": raw.get("gate"),
        })
    return steps

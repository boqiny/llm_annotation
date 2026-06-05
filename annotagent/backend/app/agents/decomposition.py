"""Build one annotation prompt per codebook dimension."""
from __future__ import annotations

from typing import Any

from app.engine.codebook_parser import CodebookDef
from app.engine.prompt_generator import generate_step_prompt


async def decompose_codebook(codebook: CodebookDef) -> list[dict[str, Any]]:
    """Return the active pipeline shape: one independent prompt per dimension."""
    if not codebook.dimensions:
        return []
    return _per_dimension(codebook)


def _per_dimension(codebook: CodebookDef) -> list[dict[str, Any]]:
    return [
        {
            "name": dim.name,
            "dimensions": [dim.name],
            "prompt": generate_step_prompt([dim], step_name=dim.name),
            "gate": None,
        }
        for dim in codebook.dimensions
    ]

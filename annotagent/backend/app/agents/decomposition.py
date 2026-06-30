"""Build one annotation prompt per codebook dimension."""
from __future__ import annotations

from typing import Any

from app.engine.codebook_parser import CodebookDef, DimensionDef, LabelDef
from app.engine.prompt_generator import generate_step_prompt


async def decompose_codebook(codebook: CodebookDef, few_shot: bool = False) -> list[dict[str, Any]]:
    """Return the active pipeline shape: one independent prompt per dimension.

    A dimension marked ``gated_by`` another dimension is ordered AFTER its gate and
    carries per-gate-value conditional prompts, so at runtime the gated step only
    offers the labels allowed for the predicted gate value (a conditional cascade).

    ``few_shot`` appends a '## Examples' block built from each label's examples.
    """
    if not codebook.dimensions:
        return []
    return _order_by_gate(_per_dimension(codebook, few_shot))


def _per_dimension(codebook: CodebookDef, few_shot: bool = False) -> list[dict[str, Any]]:
    # A derived dimension (e.g. a thematic-category rollup) is not predicted on its
    # own — its value is filled from the source dimension's chosen leaf, surfaced as
    # a `derived_dimensions` output of that source step. Skip it here.
    return [_step_for_dim(dim, few_shot) for dim in codebook.dimensions if not dim.derived_from]


def _step_for_dim(dim: DimensionDef, few_shot: bool = False) -> dict[str, Any]:
    step: dict[str, Any] = {
        "name": dim.name,
        "dimensions": [dim.name],
        "prompt": generate_step_prompt([dim], step_name=dim.name, few_shot=few_shot),
        "gate": None,
    }
    if dim.gated_by:
        step["gate_by"] = dim.gated_by
        cond_prompts, cond_labels = _conditional_views(dim, few_shot)
        step["conditional_prompts"] = cond_prompts
        step["conditional_labels"] = cond_labels
    # Already-predicted dimensions whose values are injected as context at runtime
    # (e.g. the chosen Topic when predicting its thematic category).
    if dim.context_dims:
        step["context_from"] = list(dim.context_dims)
    # Surface the parent thematic category (path[-1]) as a derived output, so the
    # category the user picks "after the topic" is shown, not buried in the path.
    if dim.category_dimension and any(len(l.path) > 1 for l in dim.labels):
        leaf_to_cat = {l.name: l.path[-1] for l in dim.labels if len(l.path) > 1}
        step["derived_dimensions"] = [{
            "name": dim.category_dimension,
            "from": dim.name,
            "map": leaf_to_cat,
        }]
    return step


def _conditional_views(dim: DimensionDef, few_shot: bool = False) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Group a gated dimension's leaves by gate value (path[0]) and build, per gate
    value, a narrowed prompt (showing only that value's category->topic subtree) and
    the list of valid leaf names."""
    groups: dict[str, list[LabelDef]] = {}
    for lbl in dim.labels:
        gate_val = lbl.path[0] if lbl.path else ""
        groups.setdefault(gate_val, []).append(lbl)

    cond_prompts: dict[str, str] = {}
    cond_labels: dict[str, list[str]] = {}
    for gate_val, labels in groups.items():
        if not gate_val:
            continue
        # Strip the gate level from each leaf's path so the per-value prompt renders
        # only the category->topic tree (the gate value is already fixed/known).
        sub_labels = [
            LabelDef(name=l.name, definition=l.definition, examples=l.examples,
                     path=l.path[1:])
            for l in labels
        ]
        sub_dim = DimensionDef(
            name=dim.name, dim_type=dim.dim_type, labels=sub_labels,
            instructions=(
                f"You already determined {dim.gated_by} = \"{gate_val}\". "
                f"Choose the single best label below; only these apply at this "
                f"{dim.gated_by} value." + (f" {dim.instructions}" if dim.instructions else "")
            ),
        )
        cond_prompts[gate_val] = generate_step_prompt(
            [sub_dim], step_name=f"{dim.name} (given {dim.gated_by} = {gate_val})",
            few_shot=few_shot,
        )
        cond_labels[gate_val] = [l.name for l in labels]
    return cond_prompts, cond_labels


def _order_by_gate(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Topologically order so every step follows the steps it depends on: its gate
    (``gate_by``) and any context sources (``context_from``). Any unsatisfiable
    remainder (cycle / missing dep) is appended in original order."""
    names = {s["name"] for s in steps}
    deps_of: dict[str, list[str]] = {}
    for s in steps:
        deps = [s["gate_by"]] if s.get("gate_by") else []
        deps += [c for c in (s.get("context_from") or [])]
        # only depend on names that are real steps (a derived context source may not be one)
        deps_of[s["name"]] = [d for d in deps if d in names]
    placed: set[str] = set()
    out: list[dict[str, Any]] = []
    remaining = list(steps)
    progress = True
    while remaining and progress:
        progress = False
        still: list[dict[str, Any]] = []
        for s in remaining:
            if all(d in placed for d in deps_of[s["name"]]):
                out.append(s)
                placed.add(s["name"])
                progress = True
            else:
                still.append(s)
        remaining = still
    out.extend(remaining)
    return out

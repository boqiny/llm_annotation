"""Generate LLM system prompts from codebook dimension definitions.

Templates live in ``app/engine/templates/`` and are rendered with Jinja2 via
``prompt_renderer.render_template``. Conditional/loop logic stays in Python so
that template files remain simple substitutions (matching the pattern used in
``annotation_demo/src/annotation_demo/prompts/templates/``).
"""
from __future__ import annotations

from app.engine.codebook_parser import DimensionDef
from app.engine.prompt_renderer import render_template


def _is_binary(dim: DimensionDef) -> bool:
    return dim.dim_type == "binary" or (
        len(dim.labels) == 2 and any("yes" in l.name.lower() for l in dim.labels)
    )


def _label_names(dim: DimensionDef) -> str:
    # Dedup by name: a gated dimension repeats the same leaf under each gate value
    # (different `path`), so the flat answer list would otherwise list duplicates.
    seen: set[str] = set()
    names: list[str] = []
    for lbl in dim.labels:
        if lbl.name not in seen:
            seen.add(lbl.name)
            names.append(lbl.name)
    return ", ".join(f'"{n}"' for n in names)


def _has_no_label(dim: DimensionDef) -> bool:
    return any(lbl.name.strip().lower() in {"no label", "none", "n/a", "not applicable"} for lbl in dim.labels)


def _is_hierarchical(dim: DimensionDef) -> bool:
    return any(getattr(lbl, "path", None) for lbl in dim.labels)


def _label_block(dim: DimensionDef) -> str:
    if _is_hierarchical(dim):
        return _hierarchical_label_block(dim)
    return "\n".join(
        f"- **{lbl.name}**: {lbl.definition}"
        for lbl in dim.labels
    )


def _hierarchical_label_block(dim: DimensionDef) -> str:
    """Render leaves grouped under their `path` ancestors as an indented tree.

    Path ancestors (Function, Code) are non-selectable grouping headers; only the
    leaf bullets are valid answers. The model sees the taxonomy, picks one leaf.
    """
    lines: list[str] = []
    prev: list[str] = []
    for lbl in dim.labels:
        path = list(getattr(lbl, "path", []) or [])
        # Emit any path ancestors not already printed at this position.
        for depth, node in enumerate(path):
            if depth >= len(prev) or prev[depth] != node:
                lines.append(f"{'  ' * depth}- {node}:")
        prev = path
        indent = "  " * len(path)
        lines.append(f"{indent}- **{lbl.name}**: {lbl.definition}".rstrip())
    return "\n".join(lines)


def _examples_of(dim: DimensionDef, per_label: int = 2) -> list[tuple[str, str]]:
    """(example sentence, label) pairs from a dimension's labels, capped per label
    so few-shot demos stay balanced and the prompt doesn't balloon."""
    out: list[tuple[str, str]] = []
    for lbl in dim.labels:
        for ex in (lbl.examples or [])[:per_label]:
            ex = str(ex).strip()
            if ex:
                out.append((ex, lbl.name))
    return out


def _few_shot_block(dimensions: list[DimensionDef]) -> str:
    """A '## Examples' few-shot section built from label examples. '' if none."""
    multi = len(dimensions) > 1
    demos: list[str] = []
    for dim in dimensions:
        for ex, label in _examples_of(dim):
            answer = f"{dim.name}: {label}" if multi else f"Answer: {label}"
            demos.append(f'Sentence: "{ex}"\n{answer}')
    if not demos:
        return ""
    return "\n## Examples\n" + "\n\n".join(demos) + "\n"


def _with_few_shot(prompt: str, dimensions: list[DimensionDef], few_shot: bool) -> str:
    if not few_shot:
        return prompt
    block = _few_shot_block(dimensions)
    return prompt.rstrip() + "\n" + block if block else prompt


def generate_dimension_prompt(dim: DimensionDef, few_shot: bool = False) -> str:
    """Generate a system prompt for annotating a single dimension."""
    label_names = _label_names(dim)
    instructions_block = (
        f"\n## Additional Instructions\n{dim.instructions}\n" if dim.instructions else ""
    )
    if _has_no_label(dim):
        no_label_instruction = (
            'If none of the substantive labels apply to the input, use "No label". '
            'Do not force a substantive label just because the output format requires an answer.'
        )
        instructions_block = (
            f"\n## Additional Instructions\n{dim.instructions}\n{no_label_instruction}\n"
            if dim.instructions else f"\n## Additional Instructions\n{no_label_instruction}\n"
        )
    if _is_binary(dim):
        output_format_block = (
            "\n## Output Format\n"
            "Think step-by-step, then write your final answer as:\n"
            "Answer: <Yes label or No label>\n"
        )
    else:
        output_format_block = (
            "\n## Output Format\n"
            "Think step-by-step, then write your final answer as:\n"
            f"Answer: <one of {label_names}>\n"
        )

    prompt = render_template(
        "dimension.jinja",
        dim_name=dim.name,
        label_names=label_names,
        label_block=_label_block(dim),
        instructions_block=instructions_block,
        output_format_block=output_format_block,
    )
    return _with_few_shot(prompt, [dim], few_shot)


def generate_step_prompt(dimensions: list[DimensionDef], step_name: str = "",
                         few_shot: bool = False) -> str:
    """Generate a combined prompt for a pipeline step covering multiple dimensions."""
    if len(dimensions) == 1:
        return generate_dimension_prompt(dimensions[0], few_shot=few_shot)

    header = f'You are an expert annotator. Classify the input text on the following {len(dimensions)} dimensions.'
    if step_name:
        header = f'You are an expert annotator performing step "{step_name}". Classify the input text on the following {len(dimensions)} dimensions.'

    dim_blocks = []
    for dim in dimensions:
        if _is_hierarchical(dim):
            # Indent the tree one level so it nests under the "### {dim}" header.
            label_block = "\n".join(
                "  " + line for line in _hierarchical_label_block(dim).split("\n")
            )
        else:
            label_block = "\n".join(
                f"  - **{lbl.name}**: {lbl.definition}"
                for lbl in dim.labels
            )
        block = f"### {dim.name}\nLabels: {_label_names(dim)}\n{label_block}"
        if dim.instructions:
            block += f"\n  Instructions: {dim.instructions}"
        dim_blocks.append(block)

    output_lines = "\n".join(f"{dim.name}: <label>" for dim in dimensions)

    prompt = render_template(
        "step.jinja",
        header=header,
        dim_blocks_text="\n".join(dim_blocks),
        output_lines=output_lines,
    )
    return _with_few_shot(prompt, dimensions, few_shot)

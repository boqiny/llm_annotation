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
    return ", ".join(f'"{lbl.name}"' for lbl in dim.labels)


def _has_no_label(dim: DimensionDef) -> bool:
    return any(lbl.name.strip().lower() in {"no label", "none", "n/a", "not applicable"} for lbl in dim.labels)


def _label_block(dim: DimensionDef) -> str:
    return "\n".join(
        f"- **{lbl.name}**: {lbl.definition}"
        + (f"\n  Examples: {', '.join(repr(e) for e in lbl.examples)}" if lbl.examples else "")
        for lbl in dim.labels
    )


def generate_dimension_prompt(dim: DimensionDef) -> str:
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

    return render_template(
        "dimension.jinja",
        dim_name=dim.name,
        label_names=label_names,
        label_block=_label_block(dim),
        instructions_block=instructions_block,
        output_format_block=output_format_block,
    )


def generate_step_prompt(dimensions: list[DimensionDef], step_name: str = "") -> str:
    """Generate a combined prompt for a pipeline step covering multiple dimensions."""
    if len(dimensions) == 1:
        return generate_dimension_prompt(dimensions[0])

    header = f'You are an expert annotator. Classify the input text on the following {len(dimensions)} dimensions.'
    if step_name:
        header = f'You are an expert annotator performing step "{step_name}". Classify the input text on the following {len(dimensions)} dimensions.'

    dim_blocks = []
    for dim in dimensions:
        label_block = "\n".join(
            f"  - **{lbl.name}**: {lbl.definition}"
            for lbl in dim.labels
        )
        block = f"### {dim.name}\nLabels: {_label_names(dim)}\n{label_block}"
        if dim.instructions:
            block += f"\n  Instructions: {dim.instructions}"
        dim_blocks.append(block)

    output_lines = "\n".join(f"{dim.name}: <label>" for dim in dimensions)

    return render_template(
        "step.jinja",
        header=header,
        dim_blocks_text="\n".join(dim_blocks),
        output_lines=output_lines,
    )

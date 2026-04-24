"""Generate LLM system prompts from codebook dimension definitions."""
from __future__ import annotations

from app.engine.codebook_parser import DimensionDef


def generate_dimension_prompt(dim: DimensionDef) -> str:
    """Generate a system prompt for annotating a single dimension."""
    label_block = "\n".join(
        f"- **{lbl.name}**: {lbl.definition}"
        + (f"\n  Examples: {', '.join(repr(e) for e in lbl.examples)}" if lbl.examples else "")
        for lbl in dim.labels
    )
    label_names = ", ".join(f'"{lbl.name}"' for lbl in dim.labels)
    is_binary = dim.dim_type == "binary" or (
        len(dim.labels) == 2 and any("yes" in l.name.lower() for l in dim.labels)
    )

    prompt = f"""You are an expert annotator classifying text on the dimension "{dim.name}".

You will receive a sentence (and optional context). Classify it using EXACTLY ONE of these labels:
{label_names}

## Label Definitions
{label_block}
"""

    if dim.instructions:
        prompt += f"\n## Additional Instructions\n{dim.instructions}\n"

    if is_binary:
        prompt += """
## Output Format
Think step-by-step, then write your final answer as:
Answer: <Yes label or No label>
"""
    else:
        prompt += f"""
## Output Format
Think step-by-step, then write your final answer as:
Answer: <one of {label_names}>
"""
    return prompt


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
        label_names = ", ".join(f'"{lbl.name}"' for lbl in dim.labels)
        block = f"""### {dim.name}
Labels: {label_names}
{label_block}"""
        if dim.instructions:
            block += f"\n  Instructions: {dim.instructions}"
        dim_blocks.append(block)

    output_lines = "\n".join(
        f'{dim.name}: <label>'
        for dim in dimensions
    )

    return f"""{header}

{chr(10).join(dim_blocks)}

## Output Format
For each dimension, think step-by-step, then provide your answers in this format:

{output_lines}
"""

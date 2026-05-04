"""
Prompt generation task.

This module generates an initial annotation prompt from a task type and codebook.
The generated prompt becomes a project-local, versioned prompt artifact.

Responsibilities:
- Render the prompt-generator system prompt.
- Call the shared LLM interface.
- Return the generated annotation prompt text.
"""

from typing import Any
from annotation_demo.core.llm import BaseLLM
from annotation_demo.prompts.renderer import render_template


def generate_annotation_prompt(
    codebook: dict[str, Any],
    task_type: str,
    llm: BaseLLM,
) -> str:
    system_prompt = render_template(
        "prompt_generator.jinja",
        task_type=task_type,
        codebook=codebook,
    )

    response = llm.generate(
        messages=[
            {"role": "system", "content": system_prompt},
        ],
        json_mode=False,
    )

    return response.raw.strip()


async def agenerate_annotation_prompt(
    codebook: dict[str, Any],
    task_type: str,
    llm: BaseLLM,
) -> str:
    system_prompt = render_template(
        "prompt_generator.jinja",
        task_type=task_type,
        codebook=codebook,
    )

    response = await llm.agenerate(
        messages=[
            {"role": "system", "content": system_prompt},
        ],
        json_mode=False,
    )

    return response.raw.strip()

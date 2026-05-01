# tasks/prompt_generator.py

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

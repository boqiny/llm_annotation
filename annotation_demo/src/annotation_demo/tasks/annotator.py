# tasks/annotator.py

from typing import Any
from annotation_demo.core.llm import BaseLLM
from annotation_demo.prompts.renderer import render_template


def annotate_items(
    items: list[dict[str, Any]],
    annotation_prompt: str,
    llm: BaseLLM,
) -> list[dict[str, Any]]:
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

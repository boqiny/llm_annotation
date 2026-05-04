"""
Prompt rendering utilities.

This module renders reusable Jinja prompt templates used by prompt generation,
annotation, and reflection agents.

Responsibilities:
- Load templates from the global prompt template directory.
- Render templates with strict variable checking.
- Support rendering project-local prompt strings.
- Keep prompt text separate from task and agent logic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateNotFound


DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


class PromptTemplateError(RuntimeError):
    """Raised when a prompt template cannot be loaded or rendered."""


def create_environment(template_dir: str | Path = DEFAULT_TEMPLATE_DIR) -> Environment:
    template_dir = Path(template_dir)

    if not template_dir.exists():
        raise PromptTemplateError(f"Template directory does not exist: {template_dir}")

    return Environment(
        loader=FileSystemLoader(str(template_dir)),
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )


def render_template(
    template_name: str,
    template_dir: str | Path = DEFAULT_TEMPLATE_DIR,
    **kwargs: Any,
) -> str:
    """
    Render a Jinja template with the provided variables.

    Example:
        render_template(
            "annotator.jinja",
            annotation_prompt="...",
            item={"text": "..."},
        )
    """
    env = create_environment(template_dir)

    try:
        template = env.get_template(template_name)
    except TemplateNotFound as exc:
        raise PromptTemplateError(
            f"Template not found: {template_name} in {template_dir}"
        ) from exc

    try:
        return template.render(**kwargs).strip()
    except Exception as exc:
        raise PromptTemplateError(
            f"Failed to render template {template_name}: {exc}"
        ) from exc


def render_template_from_string(template_text: str, **kwargs: Any) -> str:
    """
    Render a Jinja template from a raw string.

    Useful for project-local prompt versions stored under workspace/.
    """
    env = Environment(
        undefined=StrictUndefined,
        autoescape=False,
        trim_blocks=True,
        lstrip_blocks=True,
    )

    try:
        return env.from_string(template_text).render(**kwargs).strip()
    except Exception as exc:
        raise PromptTemplateError(
            f"Failed to render template string: {exc}"
        ) from exc

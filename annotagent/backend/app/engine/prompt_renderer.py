"""Jinja2 prompt rendering with strict undefined checking.

Mirrors the pattern from `annotation_demo/src/annotation_demo/prompts/renderer.py`:
- Templates live in a sibling ``templates/`` directory.
- Strict undefined → typos in template variables raise instead of silently rendering empty.
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
    env = create_environment(template_dir)
    try:
        template = env.get_template(template_name)
    except TemplateNotFound as exc:
        raise PromptTemplateError(
            f"Template not found: {template_name} in {template_dir}"
        ) from exc
    try:
        return template.render(**kwargs)
    except Exception as exc:
        raise PromptTemplateError(
            f"Failed to render template {template_name}: {exc}"
        ) from exc

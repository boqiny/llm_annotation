"""
Project workflow orchestration.

This module defines the end-to-end backend workflow for a single annotation
project. It connects storage, prompt generation, annotation, and run tracking.

Responsibilities:
- Save uploaded project inputs.
- Generate and save versioned prompts.
- Run annotation over project items.
- Save outputs and run metadata.
- Return a stable workflow result for API or script callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from annotation_demo.core.llm import BaseLLM
from annotation_demo.tasks.prompt_generator import generate_annotation_prompt
from annotation_demo.tasks.annotator import annotate_items
from annotation_demo.utils.storage import (
    append_jsonl,
    create_run_dir,
    ensure_project_dirs,
    next_version,
    save_json,
    save_text,
    save_yaml,
    utc_now_iso,
)


@dataclass
class WorkflowResult:
    project_id: str
    prompt_version: str
    run_id: str
    prompt_path: str
    annotations_path: str
    run_meta_path: str


class ProjectWorkflow:
    def __init__(
        self,
        project_id: str,
        llm: BaseLLM,
        workspace_dir: str | Path = "workspace",
    ):
        self.project_id = project_id
        self.llm = llm
        self.workspace_dir = Path(workspace_dir)
        self.project_dir = ensure_project_dirs(project_id, self.workspace_dir)

    def run(
        self,
        codebook: dict[str, Any],
        items: list[dict[str, Any]],
        task_config: dict[str, Any],
    ) -> WorkflowResult:
        created_at = utc_now_iso()

        # 1. Save uploaded / provided inputs.
        input_versions = self._save_inputs(
            codebook=codebook,
            items=items,
            task_config=task_config,
        )

        # 2. Generate versioned annotation prompt.
        prompt_version = next_version(
            self.project_dir / "prompts",
            suffix=".jinja",
            prefix="v",
        )

        annotation_prompt = generate_annotation_prompt(
            codebook=codebook,
            task_type=task_config["task_type"],
            llm=self.llm,
        )

        prompt_path = self.project_dir / "prompts" / f"{prompt_version}.jinja"
        prompt_meta_path = self.project_dir / "prompts" / f"{prompt_version}.meta.yaml"

        save_text(prompt_path, annotation_prompt)
        save_yaml(
            prompt_meta_path,
            {
                "version": prompt_version,
                "created_at": created_at,
                "source": "prompt_generator",
                "task_type": task_config["task_type"],
                "llm": self._llm_meta(),
                "inputs": input_versions,
            },
        )

        # 3. Create run directory.
        run_id, run_dir = create_run_dir(self.project_dir)

        # 4. Run annotator.
        annotations = annotate_items(
            items=items,
            annotation_prompt=annotation_prompt,
            llm=self.llm,
        )

        # 5. Save outputs.
        annotations_path = run_dir / "annotations.json"
        run_meta_path = run_dir / "meta.yaml"

        save_json(annotations_path, annotations)
        save_yaml(
            run_meta_path,
            {
                "run_id": run_id,
                "created_at": utc_now_iso(),
                "status": "success",
                "task": "annotation",
                "project_id": self.project_id,
                "inputs": input_versions,
                "prompt": {
                    "version": prompt_version,
                    "path": str(prompt_path),
                },
                "llm": self._llm_meta(),
                "output": {
                    "annotations_path": str(annotations_path),
                    "num_items": len(items),
                },
            },
        )

        # 6. Append lightweight run index.
        append_jsonl(
            self.project_dir / "logs" / "runs.jsonl",
            {
                "run_id": run_id,
                "created_at": utc_now_iso(),
                "status": "success",
                "task": "annotation",
                "project_id": self.project_id,
                "prompt_version": prompt_version,
                "num_items": len(items),
                "annotations_path": str(annotations_path),
                "meta_path": str(run_meta_path),
            },
        )

        return WorkflowResult(
            project_id=self.project_id,
            prompt_version=prompt_version,
            run_id=run_id,
            prompt_path=str(prompt_path),
            annotations_path=str(annotations_path),
            run_meta_path=str(run_meta_path),
        )

    def _save_inputs(
        self,
        codebook: dict[str, Any],
        items: list[dict[str, Any]],
        task_config: dict[str, Any],
    ) -> dict[str, str]:
        inputs_dir = self.project_dir / "inputs"

        codebook_version = next_version(inputs_dir, suffix=".json", prefix="codebook.v")
        items_version = next_version(inputs_dir, suffix=".json", prefix="items.v")
        task_config_version = next_version(inputs_dir, suffix=".yaml", prefix="task_config.v")

        save_json(inputs_dir / f"{codebook_version}.json", codebook)
        save_json(inputs_dir / f"{items_version}.json", items)
        save_yaml(inputs_dir / f"{task_config_version}.yaml", task_config)

        return {
            "codebook_version": codebook_version,
            "items_version": items_version,
            "task_config_version": task_config_version,
        }

    def _llm_meta(self) -> dict[str, Any]:
        return {
            "provider": getattr(self.llm, "provider", None),
            "model": getattr(self.llm, "model", None),
            "temperature": getattr(self.llm, "temperature", None),
            "max_tokens": getattr(self.llm, "max_tokens", None),
        }
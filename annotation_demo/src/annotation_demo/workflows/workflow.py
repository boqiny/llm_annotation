"""
Project workflow orchestration.

This module defines the end-to-end backend workflow for a single annotation
project. It connects storage, prompt generation, annotation, reflection, and
run tracking.

Responsibilities:
- Save uploaded project inputs.
- Generate and save versioned prompts.
- Run async concurrent annotation over project items.
- Optionally evaluate against gold labels.
- Run the reflection loop: induce memory rules from feedback, persist memory,
  and return a memory-enhanced prompt for the next annotation run.
- Save outputs and run metadata.
- Return a stable workflow result for API or script callers.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from annotation_demo.agents.reflect_agent import (
    ReflectAgent,
    ReflectMemory,
    memory_from_dict,
    memory_to_dict,
)
from annotation_demo.core.evaluation import evaluate_classification, result_to_dict
from annotation_demo.core.llm import BaseLLM
from annotation_demo.tasks.annotator import annotate_items_async
from annotation_demo.tasks.prompt_generator import agenerate_annotation_prompt
from annotation_demo.utils.storage import (
    append_jsonl,
    create_run_dir,
    ensure_dir,
    ensure_project_dirs,
    list_versions,
    load_json,
    next_version,
    save_json,
    save_text,
    save_yaml,
    utc_now_iso,
)


@dataclass
class WorkflowResult:
    """Summary metadata for a completed workflow run.

    Attributes:
        project_id: Project identifier.
        run_id: Generated run identifier.
        run_dir: Directory where run artifacts were written.
        annotation_path: Path to saved annotation outputs.
        evaluation_path: Optional path to saved evaluation results.
        reflection_path: Optional path to saved reflection-memory results.
    """
    project_id: str
    prompt_version: str
    run_id: str
    prompt_path: str
    annotations_path: str
    run_meta_path: str
    eval_result: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclass
class ReflectionResult:
    memory_version: str
    memory_path: str
    num_new_rules: int
    enhanced_prompt: str


class ProjectWorkflow:
    def __init__(
        self,
        project_id: str,
        llm: BaseLLM,
        workspace_dir: str | Path = "workspace",
    ):
        """Orchestrates annotation, evaluation, and reflection for a project.

        The workflow owns project-level file layout and artifact writing, while task
        modules own prompt construction and LLM annotation logic.
        """
        self.project_id = project_id
        self.llm = llm
        self.workspace_dir = Path(workspace_dir)
        self.project_dir = ensure_project_dirs(project_id, self.workspace_dir)

    async def run(
        self,
        codebook: dict[str, Any],
        items: list[dict[str, Any]],
        task_config: dict[str, Any],
        gold_labels: list[dict[str, Any]] | None = None,
        concurrency: int = 5,
        on_progress: Callable[[float], None] | None = None,
    ) -> WorkflowResult:
        """Run the project annotation workflow asynchronously.

        Args:
            codebook: Codebook definition used for annotation.
            items: Input items to annotate.
            task_config: Task settings, including provider/model options and optional
                evaluation or reflection settings.

        Returns:
            WorkflowResult describing the generated artifacts.

        Notes:
            This method is async because LLM calls are async. Callers from synchronous
            scripts should use asyncio.run(...).
        """
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

        annotation_prompt = await agenerate_annotation_prompt(
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

        # 4. Run annotator (async, concurrent).
        annotations = await annotate_items_async(
            items=items,
            annotation_prompt=annotation_prompt,
            llm=self.llm,
            concurrency=concurrency,
            on_progress=on_progress,
        )

        # 5. Optionally evaluate against gold labels.
        eval_result = None
        if gold_labels is not None:
            pred_items = [
                {
                    "item_id": a["item"].get("item_id", str(i)),
                    "prediction": (a["prediction"] or {}).get("label"),
                }
                for i, a in enumerate(annotations)
                if a.get("prediction")
            ]
            eval_result = result_to_dict(
                evaluate_classification(
                    gold_items=gold_labels,
                    pred_items=pred_items,
                )
            )

        # 6. Save outputs.
        annotations_path = run_dir / "annotations.json"
        run_meta_path = run_dir / "meta.yaml"

        save_json(annotations_path, annotations)

        meta: dict[str, Any] = {
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
        }
        if eval_result is not None:
            meta["evaluation"] = eval_result
            save_json(run_dir / "eval.json", eval_result)

        save_yaml(run_meta_path, meta)

        # 7. Append lightweight run index.
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
            eval_result=eval_result,
        )

    def run_reflection(
        self,
        annotation_prompt: str,
        feedback_examples: list[dict[str, Any]],
        memory_version: str | None = None,
    ) -> ReflectionResult:
        """Induce new memory rules from feedback, persist memory, and return an
        enhanced prompt that injects all accumulated rules."""
        existing_memory = self._load_memory(memory_version)

        agent = ReflectAgent(self.llm)
        new_rules = agent.induce_rules(annotation_prompt, feedback_examples, existing_memory)

        new_version = next_version(
            self.project_dir / "memory",
            suffix=".json",
            prefix="memory.v",
        )
        updated_memory = agent.update_memory(existing_memory, new_rules, new_version)
        memory_path = self._save_memory(updated_memory, new_version)

        enhanced_prompt = agent.build_prompt_with_memory(annotation_prompt, updated_memory)

        return ReflectionResult(
            memory_version=new_version,
            memory_path=str(memory_path),
            num_new_rules=len(new_rules),
            enhanced_prompt=enhanced_prompt,
        )

    def _load_memory(self, version: str | None = None) -> ReflectMemory | None:
        memory_dir = self.project_dir / "memory"
        if version is None:
            versions = list_versions(memory_dir, suffix=".json", prefix="memory.v")
            if not versions:
                return None
            version = versions[-1]
        path = memory_dir / f"{version}.json"
        if not path.exists():
            return None
        return memory_from_dict(load_json(path))

    def _save_memory(self, memory: ReflectMemory, version: str) -> Path:
        memory_dir = self.project_dir / "memory"
        ensure_dir(memory_dir)
        path = memory_dir / f"{version}.json"
        save_json(path, memory_to_dict(memory))
        return path

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

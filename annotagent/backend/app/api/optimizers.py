"""Optimizer API — list available optimizers, launch runs, view results."""
from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pydantic import BaseModel as _BaseModel
from app.agents.reflect_memory import apply_human_feedback, apply_rules_to_prompt
from app.config import resolve_api_key
from app.database import get_db, async_session
from app.engine.codebook_parser import parse_codebook
from app.engine.metrics import compute_metrics
from app.engine.prompt_generator import generate_dimension_prompt
from app.utils.storage import next_version, project_paths, save_text, save_yaml, utc_now_iso
from app.models.tables import Codebook, DataItem, Dataset, OptimizerRun, Pipeline, Project, ReflectMemoryVersion
from app.optimizers import Example, evaluate_prompt, get_optimizer, list_optimizers
from app.optimizers.base import audit_prompt_for_leakage
from app.schemas.schemas import OptimizerInfo, OptimizerRunCreate, OptimizerRunOut

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects/{project_id}/optimizer-runs", tags=["optimizers"])
memory_router = APIRouter(prefix="/api/projects/{project_id}/memory", tags=["memory"])

# In-process registry of in-flight optimizer tasks so we can cooperatively
# cancel them. Keyed by run_id. Entries are removed by a done-callback when
# the task finishes for any reason (success / failure / cancellation).
_RUNNING_TASKS: dict[int, asyncio.Task] = {}


@memory_router.get("")
async def list_memory_versions(
    project_id: int,
    dimension: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List reflection-memory versions for a project (newest first).

    Optional ``?dimension=`` filter restricts to a single dimension.
    """
    q = select(ReflectMemoryVersion).where(ReflectMemoryVersion.project_id == project_id)
    if dimension:
        q = q.where(ReflectMemoryVersion.dimension_name == dimension)
    q = q.order_by(
        ReflectMemoryVersion.dimension_name,
        ReflectMemoryVersion.version.desc(),
    )
    rows = (await db.execute(q)).scalars().all()
    return [
        {
            "id": r.id,
            "dimension_name": r.dimension_name,
            "version": r.version,
            "n_rules": len(r.rules_json or []),
            "new_rules_count": r.new_rules_count,
            "source_optimizer_run_id": r.source_optimizer_run_id,
            "rules": r.rules_json or [],
            "feedback_text": r.feedback_text,
            "created_at": r.created_at.isoformat() + "Z" if r.created_at else None,
        }
        for r in rows
    ]


class _FeedbackRequest(_BaseModel):
    dimension_name: str
    feedback: str


@memory_router.post("/feedback")
async def apply_feedback(
    project_id: int,
    body: _FeedbackRequest,
    db: AsyncSession = Depends(get_db),
):
    """Convert plain-English human feedback to structured rules and save as a new memory version."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Load latest memory version for this dimension
    latest = (await db.execute(
        select(ReflectMemoryVersion)
        .where(
            ReflectMemoryVersion.project_id == project_id,
            ReflectMemoryVersion.dimension_name == body.dimension_name,
        )
        .order_by(ReflectMemoryVersion.version.desc())
        .limit(1)
    )).scalars().first()
    existing_rules: list[dict] = list(latest.rules_json or []) if latest else []
    last_v: int = latest.version if latest else 0

    # Load label definitions from the latest codebook
    label_defs = ""
    codebook = (await db.execute(
        select(Codebook).where(Codebook.project_id == project_id).order_by(Codebook.id.desc()).limit(1)
    )).scalars().first()
    if codebook:
        try:
            parsed = parse_codebook(codebook.raw_json)
            dim_def = next((d for d in parsed.dimensions if d.name == body.dimension_name), None)
            if dim_def:
                label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim_def.labels)
        except Exception:
            logger.warning("Failed to parse codebook for feedback labels", exc_info=True)

    merged_rules = await apply_human_feedback(
        feedback_text=body.feedback,
        dimension_name=body.dimension_name,
        label_defs=label_defs,
        existing_rules=existing_rules,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    )

    new_count = max(0, len(merged_rules) - len(existing_rules))
    row = ReflectMemoryVersion(
        project_id=project_id,
        dimension_name=body.dimension_name,
        version=last_v + 1,
        rules_json=merged_rules,
        new_rules_count=new_count,
        source_optimizer_run_id=None,
        feedback_text=body.feedback,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)

    return {
        "id": row.id,
        "dimension_name": row.dimension_name,
        "version": row.version,
        "n_rules": len(row.rules_json or []),
        "new_rules_count": row.new_rules_count,
        "source_optimizer_run_id": row.source_optimizer_run_id,
        "rules": row.rules_json or [],
        "feedback_text": row.feedback_text,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
    }


class _PreviewRequest(_BaseModel):
    dimension_name: str


class _CommitRequest(_BaseModel):
    dimension_name: str
    new_prompt: str


class _FeedbackBatchPreviewRequest(_BaseModel):
    dimension_name: str
    feedbacks: list[str]


class _FeedbackBatchCommitRequest(_BaseModel):
    dimension_name: str
    feedbacks: list[str]
    rules: list[dict[str, Any]]
    new_prompt: str


def _find_pipeline_step(steps: list[dict], dimension_name: str) -> dict | None:
    """Return the first step that covers dimension_name."""
    target = _norm_dimension_name(dimension_name)
    for step in steps:
        step_name = _norm_dimension_name(step.get("name", ""))
        step_dims = [_norm_dimension_name(d) for d in step.get("dimensions", [])]
        if target in step_dims or step_name == target:
            return step
    return None


async def _per_dimension_steps_for_prompt_commit(
    db: AsyncSession,
    project_id: int,
    existing_steps: list[dict],
    dimension_name: str,
    new_prompt: str,
) -> list[dict]:
    """Build one prompt per dimension and preserve known optimized prompts.

    A dimension-level prompt should never replace a multi-dimension step prompt.
    If the active pipeline is grouped/combined, split it before committing.
    """
    codebook = (await db.execute(
        select(Codebook).where(Codebook.project_id == project_id).order_by(Codebook.id.desc()).limit(1)
    )).scalars().first()
    if not codebook:
        raise HTTPException(400, "No codebook uploaded for this project")

    parsed = parse_codebook(codebook.raw_json)
    existing_by_dim: dict[str, str] = {}
    for step in existing_steps:
        dims = step.get("dimensions") or []
        if len(dims) == 1 and step.get("prompt"):
            existing_by_dim[_norm_dimension_name(dims[0])] = str(step["prompt"])

    latest_runs = (await db.execute(
        select(OptimizerRun)
        .where(
            OptimizerRun.project_id == project_id,
            OptimizerRun.status == "completed",
            OptimizerRun.optimized_prompt.is_not(None),
        )
        .order_by(OptimizerRun.id.desc())
    )).scalars().all()
    optimized_by_dim: dict[str, str] = {}
    for run in latest_runs:
        if not run.optimized_prompt:
            continue
        key = _norm_dimension_name(run.dimension_name)
        if key not in optimized_by_dim:
            optimized_by_dim[key] = run.optimized_prompt

    target = _norm_dimension_name(dimension_name)
    steps: list[dict] = []
    for dim in parsed.dimensions:
        key = _norm_dimension_name(dim.name)
        steps.append({
            "name": dim.name,
            "dimensions": [dim.name],
            "prompt": new_prompt if key == target else optimized_by_dim.get(key) or existing_by_dim.get(key) or generate_dimension_prompt(dim),
            "gate": None,
        })
    return steps


def _norm_dimension_name(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"\([^)]*\)", " ", text)
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    return " ".join(text.split()).casefold()


def _label_for_dimension(labels: dict, dimension_name: str):
    if dimension_name in labels:
        return labels[dimension_name]
    target = _norm_dimension_name(dimension_name)
    for key, value in labels.items():
        if _norm_dimension_name(key) == target:
            return value
    return None


def _norm_label_name(value: str) -> str:
    text = str(value or "")
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    return " ".join(text.split()).casefold()


def _canonical_gold_labels(value: Any, valid_labels: list[str]) -> list[str]:
    raw_values = value if isinstance(value, list) else [value]
    by_norm = {_norm_label_name(label): label for label in valid_labels}
    canonical: list[str] = []
    for raw in raw_values:
        key = _norm_label_name(str(raw))
        label = by_norm.get(key)
        if label and label not in canonical:
            canonical.append(label)
    return canonical


async def _latest_memory(
    db: AsyncSession,
    project_id: int,
    dimension_name: str,
) -> ReflectMemoryVersion | None:
    return (await db.execute(
        select(ReflectMemoryVersion)
        .where(
            ReflectMemoryVersion.project_id == project_id,
            ReflectMemoryVersion.dimension_name == dimension_name,
        )
        .order_by(ReflectMemoryVersion.version.desc())
        .limit(1)
    )).scalars().first()


async def _latest_pipeline(db: AsyncSession, project_id: int) -> Pipeline | None:
    return (await db.execute(
        select(Pipeline)
        .where(Pipeline.project_id == project_id)
        .order_by(Pipeline.id.desc())
        .limit(1)
    )).scalars().first()


async def _label_defs_for_dimension(
    db: AsyncSession,
    project_id: int,
    dimension_name: str,
) -> str:
    codebook = (await db.execute(
        select(Codebook).where(Codebook.project_id == project_id).order_by(Codebook.id.desc()).limit(1)
    )).scalars().first()
    if not codebook:
        return ""
    try:
        parsed = parse_codebook(codebook.raw_json)
        dim_def = next((d for d in parsed.dimensions if d.name == dimension_name), None)
        if dim_def:
            return "\n".join(f"- {l.name}: {l.definition}" for l in dim_def.labels)
    except Exception:
        logger.warning("Failed to parse codebook for feedback labels", exc_info=True)
    return ""


def _clean_feedbacks(feedbacks: list[str]) -> list[str]:
    return [f.strip() for f in feedbacks if f.strip()]


def _join_feedbacks(feedbacks: list[str]) -> str:
    return "\n\n".join(f"{i}. {text}" for i, text in enumerate(feedbacks, 1))


@memory_router.post("/preview-prompt")
async def preview_prompt(
    project_id: int,
    body: _PreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate a preview of the updated prompt with memory rules applied.

    Returns {old_prompt, new_prompt} so the frontend can show a diff.
    Does NOT persist anything.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Latest memory version for this dimension
    latest_mem = (await db.execute(
        select(ReflectMemoryVersion)
        .where(
            ReflectMemoryVersion.project_id == project_id,
            ReflectMemoryVersion.dimension_name == body.dimension_name,
        )
        .order_by(ReflectMemoryVersion.version.desc())
        .limit(1)
    )).scalars().first()

    if not latest_mem or not latest_mem.rules_json:
        raise HTTPException(400, "No memory rules found for this dimension. Add feedback first.")

    # Latest pipeline for this project
    pipeline = (await db.execute(
        select(Pipeline)
        .where(Pipeline.project_id == project_id)
        .order_by(Pipeline.id.desc())
        .limit(1)
    )).scalars().first()

    if not pipeline:
        raise HTTPException(400, "No pipeline found. Generate a pipeline first.")

    step = _find_pipeline_step(pipeline.steps or [], body.dimension_name)
    if not step:
        raise HTTPException(400, f"No pipeline step found for dimension '{body.dimension_name}'.")

    old_prompt = step.get("prompt", "")
    new_prompt = await apply_rules_to_prompt(
        base_prompt=old_prompt,
        rules=list(latest_mem.rules_json),
        dimension_name=body.dimension_name,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    )

    return {
        "dimension_name": body.dimension_name,
        "pipeline_id": pipeline.id,
        "memory_version": latest_mem.version,
        "old_prompt": old_prompt,
        "new_prompt": new_prompt,
    }


@memory_router.post("/preview-feedback-batch")
async def preview_feedback_batch(
    project_id: int,
    body: _FeedbackBatchPreviewRequest,
    db: AsyncSession = Depends(get_db),
):
    """Preview a prompt update from a batch of draft human feedback.

    This performs the two LLM steps — feedback-to-rules, then rules-to-prompt —
    but does not persist either memory or prompt changes.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    feedbacks = _clean_feedbacks(body.feedbacks)
    if not feedbacks:
        raise HTTPException(400, "Add at least one feedback item before generating a prompt.")

    latest_mem = await _latest_memory(db, project_id, body.dimension_name)
    existing_rules: list[dict] = list(latest_mem.rules_json or []) if latest_mem else []
    feedback_text = _join_feedbacks(feedbacks)
    label_defs = await _label_defs_for_dimension(db, project_id, body.dimension_name)

    merged_rules = await apply_human_feedback(
        feedback_text=feedback_text,
        dimension_name=body.dimension_name,
        label_defs=label_defs,
        existing_rules=existing_rules,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    )

    pipeline = await _latest_pipeline(db, project_id)
    if not pipeline:
        raise HTTPException(400, "No pipeline found. Generate a pipeline first.")

    step = _find_pipeline_step(pipeline.steps or [], body.dimension_name)
    if not step:
        raise HTTPException(400, f"No pipeline step found for dimension '{body.dimension_name}'.")

    old_prompt = step.get("prompt", "")
    new_prompt = await apply_rules_to_prompt(
        base_prompt=old_prompt,
        rules=merged_rules,
        dimension_name=body.dimension_name,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    )

    return {
        "dimension_name": body.dimension_name,
        "pipeline_id": pipeline.id,
        "memory_version": (latest_mem.version if latest_mem else 0) + 1,
        "old_prompt": old_prompt,
        "new_prompt": new_prompt,
        "rules": merged_rules,
        "feedback_text": feedback_text,
    }


@memory_router.post("/commit-prompt")
async def commit_prompt(
    project_id: int,
    body: _CommitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Commit a previewed prompt update to Pipeline.steps and the filesystem audit trail.

    Caller provides the new_prompt text (from a prior /preview-prompt call).
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    pipeline = (await db.execute(
        select(Pipeline)
        .where(Pipeline.project_id == project_id)
        .order_by(Pipeline.id.desc())
        .limit(1)
    )).scalars().first()

    if not pipeline:
        raise HTTPException(400, "No pipeline found.")

    steps = [dict(s) for s in (pipeline.steps or [])]
    updated = False
    step = _find_pipeline_step(steps, body.dimension_name)
    if step:
        if len(step.get("dimensions") or []) > 1:
            steps = await _per_dimension_steps_for_prompt_commit(
                db, project_id, steps, body.dimension_name, body.new_prompt
            )
        else:
            step["prompt"] = body.new_prompt
        updated = True

    if not updated:
        steps = await _per_dimension_steps_for_prompt_commit(
            db, project_id, steps, body.dimension_name, body.new_prompt
        )
        updated = True

    pipeline.steps = steps
    await db.commit()

    # Filesystem audit trail: workspace/project_{id}/prompts/{dimension}/human_memory/vNNN.txt
    try:
        paths = project_paths(str(project_id))
        prompt_dir = paths["prompts"] / body.dimension_name / "human_memory"
        version = next_version(prompt_dir)
        save_text(prompt_dir / f"{version}.txt", body.new_prompt)
        save_yaml(prompt_dir / f"{version}.meta.yaml", {
            "version": version,
            "dimension": body.dimension_name,
            "pipeline_id": pipeline.id,
            "source": "human_memory",
            "updated_at": utc_now_iso(),
        })
    except Exception:
        logger.warning("Filesystem prompt version write failed", exc_info=True)

    return {"ok": True, "pipeline_id": pipeline.id, "dimension_name": body.dimension_name}


@memory_router.post("/commit-feedback-batch")
async def commit_feedback_batch(
    project_id: int,
    body: _FeedbackBatchCommitRequest,
    db: AsyncSession = Depends(get_db),
):
    """Commit a reviewed feedback batch and its generated prompt in one transaction."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    feedbacks = _clean_feedbacks(body.feedbacks)
    if not feedbacks:
        raise HTTPException(400, "Add at least one feedback item before applying.")
    if not body.rules:
        raise HTTPException(400, "No generated rules supplied. Generate a preview first.")

    latest_mem = await _latest_memory(db, project_id, body.dimension_name)
    last_v = latest_mem.version if latest_mem else 0
    existing_rules: list[dict] = list(latest_mem.rules_json or []) if latest_mem else []
    feedback_text = _join_feedbacks(feedbacks)

    row = ReflectMemoryVersion(
        project_id=project_id,
        dimension_name=body.dimension_name,
        version=last_v + 1,
        rules_json=body.rules,
        new_rules_count=max(0, len(body.rules) - len(existing_rules)),
        source_optimizer_run_id=None,
        feedback_text=feedback_text,
    )
    db.add(row)

    pipeline = await _latest_pipeline(db, project_id)
    if not pipeline:
        raise HTTPException(400, "No pipeline found.")

    steps = [dict(s) for s in (pipeline.steps or [])]
    updated = False
    step = _find_pipeline_step(steps, body.dimension_name)
    if step:
        if len(step.get("dimensions") or []) > 1:
            steps = await _per_dimension_steps_for_prompt_commit(
                db, project_id, steps, body.dimension_name, body.new_prompt
            )
        else:
            step["prompt"] = body.new_prompt
        updated = True

    if not updated:
        steps = await _per_dimension_steps_for_prompt_commit(
            db, project_id, steps, body.dimension_name, body.new_prompt
        )
        updated = True

    pipeline.steps = steps
    await db.commit()
    await db.refresh(row)

    try:
        paths = project_paths(str(project_id))
        prompt_dir = paths["prompts"] / body.dimension_name / "human_memory"
        version = next_version(prompt_dir)
        save_text(prompt_dir / f"{version}.txt", body.new_prompt)
        save_yaml(prompt_dir / f"{version}.meta.yaml", {
            "version": version,
            "dimension": body.dimension_name,
            "pipeline_id": pipeline.id,
            "memory_version": row.version,
            "source": "human_memory_batch",
            "updated_at": utc_now_iso(),
        })
    except Exception:
        logger.warning("Filesystem prompt version write failed", exc_info=True)

    return {
        "ok": True,
        "pipeline_id": pipeline.id,
        "dimension_name": body.dimension_name,
        "memory": {
            "id": row.id,
            "dimension_name": row.dimension_name,
            "version": row.version,
            "n_rules": len(row.rules_json or []),
            "new_rules_count": row.new_rules_count,
            "source_optimizer_run_id": row.source_optimizer_run_id,
            "rules": row.rules_json or [],
            "feedback_text": row.feedback_text,
            "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        },
    }


@memory_router.delete("/{version_id}", status_code=204)
async def delete_memory_version(
    project_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a single memory version."""
    row = await db.get(ReflectMemoryVersion, version_id)
    if not row or row.project_id != project_id:
        raise HTTPException(404, "Memory version not found")
    await db.delete(row)
    await db.commit()


@router.get("/available", response_model=list[OptimizerInfo])
async def get_available_optimizers(project_id: int):
    """List registered optimizers with their role labels."""
    return list_optimizers()


@router.get("", response_model=list[OptimizerRunOut])
async def list_runs(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(OptimizerRun)
        .where(OptimizerRun.project_id == project_id)
        .order_by(OptimizerRun.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{run_id}", response_model=OptimizerRunOut)
async def get_run(project_id: int, run_id: int, db: AsyncSession = Depends(get_db)):
    run = await db.get(OptimizerRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    return run


class OptimizerRunPatch(_BaseModel):
    """Whitelisted fields the user can edit after a run completes."""
    optimized_prompt: str | None = None


@router.delete("/{run_id}", status_code=204)
async def delete_run(project_id: int, run_id: int, db: AsyncSession = Depends(get_db)):
    """Delete an optimizer run row. Refuses to delete in-flight runs.

    Memory versions that reference this run via ``source_optimizer_run_id``
    keep their rules; the FK is nulled so the rule library survives even
    when its source run is deleted.
    """
    run = await db.get(OptimizerRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    if run.status in ("running", "pending"):
        raise HTTPException(409, f"Run is {run.status}; wait for it to finish or fail first.")

    # Null out the FK on any memory versions sourced from this run so the
    # cumulative rule library isn't orphaned to a missing FK.
    from sqlalchemy import update
    await db.execute(
        update(ReflectMemoryVersion)
        .where(ReflectMemoryVersion.source_optimizer_run_id == run_id)
        .values(source_optimizer_run_id=None)
    )
    await db.delete(run)
    await db.commit()


@router.patch("/{run_id}", response_model=OptimizerRunOut)
async def patch_run(
    project_id: int, run_id: int,
    body: OptimizerRunPatch,
    db: AsyncSession = Depends(get_db),
):
    """Edit a completed run's user-visible fields (currently: ``optimized_prompt``).

    The optimizer's trajectory and artifact are preserved as the run record;
    edits here represent the user's manual override of the final prompt.
    """
    run = await db.get(OptimizerRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    if run.status not in ("completed", "failed"):
        raise HTTPException(409, f"Run is {run.status}; wait until it finishes before editing.")

    if body.optimized_prompt is not None:
        run.optimized_prompt = body.optimized_prompt
    await db.commit()
    await db.refresh(run)
    return run


@router.post("", response_model=OptimizerRunOut, status_code=201)
async def start_run(
    project_id: int,
    body: OptimizerRunCreate,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Validate optimizer name
    available = {o["name"] for o in list_optimizers()}
    if body.optimizer_name not in available:
        raise HTTPException(400, f"Unknown optimizer. Available: {sorted(available)}")

    # Validate labeled-examples dataset (any annotated set is acceptable —
    # is_gold just flags the canonical "ground truth" for the demo's split,
    # but Fiona/Chang per-annotator labels are equally valid as a learning
    # source for the rule library).
    gold_dataset = await db.get(Dataset, body.gold_dataset_id)
    if not gold_dataset or gold_dataset.project_id != project_id:
        raise HTTPException(404, "Labeled dataset not found for this project")

    # Validate dimension exists in active codebook (latest = highest id).
    cb_res = await db.execute(
        select(Codebook).where(Codebook.project_id == project_id)
        .order_by(Codebook.id.desc()).limit(1)
    )
    codebook_row = cb_res.scalars().first()
    if not codebook_row:
        raise HTTPException(400, "No codebook loaded for this project")
    parsed = parse_codebook(codebook_row.raw_json)
    dim_def = next((d for d in parsed.dimensions if d.name == body.dimension_name), None)
    if dim_def is None:
        raise HTTPException(
            400,
            f"Dimension '{body.dimension_name}' not in codebook. "
            f"Available: {[d.name for d in parsed.dimensions]}"
        )

    # Validate split fractions — they must sum to ~1.0 and each be in (0, 1)
    total_frac = body.train_frac + body.val_frac + body.test_frac
    if abs(total_frac - 1.0) > 0.01:
        raise HTTPException(
            400,
            f"train_frac + val_frac + test_frac must sum to 1.0 "
            f"(got {total_frac:.3f}: {body.train_frac:.2f}/{body.val_frac:.2f}/{body.test_frac:.2f})"
        )
    for name, frac in [("train_frac", body.train_frac), ("val_frac", body.val_frac), ("test_frac", body.test_frac)]:
        if not (0.0 < frac < 1.0):
            raise HTTPException(400, f"{name}={frac} must be in (0, 1)")

    run = OptimizerRun(
        project_id=project_id,
        gold_dataset_id=body.gold_dataset_id,
        optimizer_name=body.optimizer_name,
        dimension_name=body.dimension_name,
        status="pending",
        budget=body.budget,
        train_frac=body.train_frac,
        # Val/test fractions live in artifact JSON to avoid a schema migration.
        artifact={
            "requested_splits": {
                "train_frac": body.train_frac,
                "val_frac": body.val_frac,
                "test_frac": body.test_frac,
            },
        },
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)

    task = asyncio.create_task(_execute_run(
        run_id=run.id,
        project_id=project_id,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    ))
    _RUNNING_TASKS[run.id] = task
    task.add_done_callback(lambda _t, rid=run.id: _RUNNING_TASKS.pop(rid, None))

    return run


@router.post("/{run_id}/cancel", status_code=202)
async def cancel_run(project_id: int, run_id: int, db: AsyncSession = Depends(get_db)):
    """Cooperatively cancel an in-flight optimizer run.

    Calls ``task.cancel()``. The next ``await`` inside the optimizer raises
    ``asyncio.CancelledError``, which ``_execute_run`` catches to mark the
    run ``cancelled`` in the DB. Returns 202 because cancellation is async.
    """
    run = await db.get(OptimizerRun, run_id)
    if not run or run.project_id != project_id:
        raise HTTPException(404, "Run not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(409, f"Run is {run.status}; nothing to cancel.")

    task = _RUNNING_TASKS.get(run_id)
    if task is None:
        # Task disappeared (server restart?). Mark cancelled so the UI clears.
        run.status = "cancelled"
        await db.commit()
        return {"status": "cancelled", "note": "task not in registry"}

    task.cancel()
    return {"status": "cancelling"}


def _stratified_split(
    examples: list[Example], *, train_frac: float, val_frac: float, seed: int,
) -> tuple[list[Example], list[Example], list[Example], dict[str, dict[str, int]]]:
    """Group by gold label, deterministic-shuffle each group, slice proportionally.

    Returns (train, val, test, per_class) where per_class maps each label to
    {n, train, val, test} counts. Tiny classes (<3 items) all go to train so
    the optimizer can see them in failure mining; they won't appear in val/test.
    """
    by_class: dict[str, list[Example]] = {}
    for ex in examples:
        by_class.setdefault(ex.gold, []).append(ex)

    rng = random.Random(seed)
    train: list[Example] = []
    val: list[Example] = []
    test: list[Example] = []
    per_class: dict[str, dict[str, int]] = {}

    for cls in sorted(by_class):                 # sorted for determinism
        items = list(by_class[cls])
        rng.shuffle(items)
        n = len(items)
        if n < 3:
            train.extend(items)
            per_class[cls] = {"n": n, "train": n, "val": 0, "test": 0}
            continue
        nt = max(1, int(round(train_frac * n)))
        nv = max(1, int(round(val_frac * n)))
        if nt + nv > n - 1:                      # leave at least 1 for test
            nv = max(1, n - nt - 1)
        nx = n - nt - nv
        train.extend(items[:nt])
        val.extend(items[nt:nt + nv])
        test.extend(items[nt + nv:])
        per_class[cls] = {"n": n, "train": nt, "val": nv, "test": nx}

    rng.shuffle(train)                            # mix classes within each split
    rng.shuffle(val)
    rng.shuffle(test)
    return train, val, test, per_class


async def _execute_run(run_id: int, project_id: int, provider: str, model: str, api_key: str):
    """Background task: load gold subset, invoke optimizer, persist result."""
    try:
        async with async_session() as session:
            run = await session.get(OptimizerRun, run_id)
            if not run:
                return
            run.status = "running"
            await session.commit()

            # Load codebook + build initial prompt (latest = highest id).
            cb_res = await session.execute(
                select(Codebook).where(Codebook.project_id == project_id)
                .order_by(Codebook.id.desc()).limit(1)
            )
            codebook_row = cb_res.scalars().first()
            parsed = parse_codebook(codebook_row.raw_json)
            dim_def = next(d for d in parsed.dimensions if d.name == run.dimension_name)
            initial_prompt = generate_dimension_prompt(dim_def)
            valid_labels = [l.name for l in dim_def.labels]
            label_defs = "\n".join(f"- {l.name}: {l.definition}" for l in dim_def.labels)

            # Load gold examples for this dimension
            item_res = await session.execute(
                select(DataItem).where(DataItem.dataset_id == run.gold_dataset_id)
            )
            items = item_res.scalars().all()

        examples: list[Example] = []
        for it in items:
            labels = it.gold_labels or {}
            gold_label = _label_for_dimension(labels, run.dimension_name)
            if gold_label is None:
                continue
            for canonical_label in _canonical_gold_labels(gold_label, valid_labels):
                examples.append(Example(
                    sentence=it.content,
                    gold=canonical_label,
                    context=it.context or "",
                ))

        if len(examples) < 15:
            async with async_session() as session:
                run = await session.get(OptimizerRun, run_id)
                run.status = "failed"
                run.error = (
                    f"Only {len(examples)} gold examples available for "
                    f"'{run.dimension_name}'; need at least 15 for a 3-way split."
                )
                await session.commit()
            return

        # Deterministic seed — same (gold_dataset_id, dim) always produces the same split.
        rng_seed = hash((run.gold_dataset_id, run.dimension_name)) & 0xFFFF_FFFF

        # Read requested splits from artifact (set at create time); fall back to defaults.
        splits = (run.artifact or {}).get("requested_splits", {})
        train_frac = splits.get("train_frac", run.train_frac or 0.15)
        val_frac = splits.get("val_frac", 0.42)
        test_frac = splits.get("test_frac", max(0.0, 1.0 - train_frac - val_frac))

        # ─── Stratified split: proportional per gold class ───
        # Guarantees every class has ≥1 item in every split (when class size ≥ 3).
        # Tiny classes (<3 items) go entirely to train so the optimizer can at
        # least see them as failure-mining inputs.
        trainset, valset, testset, per_class = _stratified_split(
            examples, train_frac=train_frac, val_frac=val_frac,
            seed=rng_seed,
        )
        n_train, n_val, n_test = len(trainset), len(valset), len(testset)
        n_total = len(examples)

        if n_train < 5 or n_val < 5:
            async with async_session() as session:
                run = await session.get(OptimizerRun, run_id)
                run.status = "failed"
                run.error = (
                    f"After stratification: train={n_train}, val={n_val}, test={n_test} "
                    f"(per-class: {per_class}). Need ≥5 train and ≥5 val. "
                    f"Try a larger gold dataset or fewer/more-balanced classes."
                )
                await session.commit()
            return

        # LEAKAGE GUARD: assert sets are disjoint (cheap O(n) sanity check).
        assert len({id(x) for x in trainset} & {id(x) for x in valset}) == 0
        assert len({id(x) for x in valset}   & {id(x) for x in testset}) == 0
        assert len({id(x) for x in trainset} & {id(x) for x in testset}) == 0

        logger.info(
            f"Run {run_id} stratified split: total={n_total} train={n_train} val={n_val} "
            f"test={n_test} per_class={per_class} (seed={rng_seed})"
        )

        # For reflect_agent: seed rules from the latest memory version on this
        # (project, dimension) so we accumulate across sessions instead of
        # restarting the rule library every run.
        seed_rules: list[dict] = []
        if run.optimizer_name == "reflect_agent":
            async with async_session() as session:
                latest = await session.execute(
                    select(ReflectMemoryVersion)
                    .where(
                        ReflectMemoryVersion.project_id == project_id,
                        ReflectMemoryVersion.dimension_name == run.dimension_name,
                    )
                    .order_by(ReflectMemoryVersion.version.desc())
                    .limit(1)
                )
                latest_row = latest.scalars().first()
                if latest_row and latest_row.rules_json:
                    seed_rules = list(latest_row.rules_json)

        # Invoke optimizer, streaming partial progress to DB per round
        opt = get_optimizer(
            run.optimizer_name,
            provider=provider, model=model, api_key=api_key,
            budget=run.budget, label_defs=label_defs,
            seed_rules=seed_rules,
        )

        async def on_progress(payload: dict) -> None:
            # Persist partial state so the UI can poll and see live trajectory.
            # Never raise — progress failures must not kill the optimizer.
            try:
                async with async_session() as s:
                    r2 = await s.get(OptimizerRun, run_id)
                    if not r2:
                        return
                    if "trajectory" in payload:
                        r2.trajectory = payload["trajectory"]
                    if "total_tokens" in payload:
                        r2.total_tokens = payload["total_tokens"]
                    if "total_cost_usd" in payload:
                        r2.total_cost = round(float(payload["total_cost_usd"]), 6)
                    if "initial_score" in payload:
                        r2.initial_score = float(payload["initial_score"])
                    if "final_score" in payload:
                        r2.final_score = float(payload["final_score"])
                    if "artifact" in payload:
                        r2.artifact = payload["artifact"]
                    if "optimized_prompt" in payload:
                        r2.optimized_prompt = payload["optimized_prompt"]
                    await s.commit()
            except Exception:
                logger.warning(f"progress callback persist failed for run {run_id}", exc_info=True)

        result = await opt.optimize(
            initial_prompt=initial_prompt,
            dimension=run.dimension_name,
            valid_labels=valid_labels,
            trainset=trainset,
            valset=valset,
            on_progress=on_progress,
        )

        # ─── HELD-OUT TEST EVALUATION ───
        # The optimizer only saw train + val. Now we evaluate the final prompt
        # on the test set, which has never been touched by the loop. This is
        # the honest final score.
        test_initial_acc = 0.0
        test_final_acc = 0.0
        test_tokens = 0
        test_cost = 0.0
        test_initial_metrics: dict | None = None
        test_final_metrics: dict | None = None
        if testset:
            # Score the initial (unoptimized) prompt on test, so the user can see
            # the lift attributable to optimization, not just prompt quality.
            test_initial_acc, ti_preds, ti_tok, ti_cost = await evaluate_prompt(
                initial_prompt, testset, valid_labels,
                provider=provider, model=model, api_key=api_key,
            )
            test_final_acc, tf_preds, tf_tok, tf_cost = await evaluate_prompt(
                result.optimized_prompt, testset, valid_labels,
                provider=provider, model=model, api_key=api_key,
            )
            # Compute full P/R/F1 (macro / weighted / per-class) from predictions.
            y_true = [ex.gold for ex in testset]
            test_initial_metrics = compute_metrics(y_true, ti_preds)
            test_final_metrics   = compute_metrics(y_true, tf_preds)
            test_tokens = ti_tok + tf_tok
            test_cost = ti_cost + tf_cost
            logger.info(
                f"Run {run_id} held-out test: initial={test_initial_acc:.3f} "
                f"final={test_final_acc:.3f} n={len(testset)}"
            )

        # Enrich artifact with split info + honest test numbers
        enriched_artifact = dict(result.artifact or {})
        enriched_artifact["splits"] = {
            "n_train": n_train,
            "n_val":   n_val,
            "n_test":  n_test,
            "train_frac": train_frac,
            "val_frac":   val_frac,
            "test_frac":  test_frac,
            "seed": rng_seed,
            "stratified": True,
            "per_class": per_class,
        }
        enriched_artifact["test"] = {
            "initial_score": round(test_initial_acc, 4),
            "final_score":   round(test_final_acc, 4),
            "delta":         round(test_final_acc - test_initial_acc, 4),
            "n":             n_test,
            "tokens":        test_tokens,
            "cost_usd":      round(test_cost, 6),
            "leakage_guard": "test examples were never passed to the optimizer",
            # Full metrics: macro / weighted P/R/F1 + per-class breakdown.
            "initial_metrics": test_initial_metrics,
            "final_metrics":   test_final_metrics,
        }

        # Audit the final prompt for accidental val/test substring leakage.
        # Deterministic — checks that no val/test sentence appears verbatim
        # inside the prompt the model will run. ``clean: true`` means safe.
        enriched_artifact["audit"] = audit_prompt_for_leakage(
            result.optimized_prompt, valset, testset,
        )
        if not enriched_artifact["audit"]["clean"]:
            logger.warning(
                f"Run {run_id} prompt-leakage audit FAILED: "
                f"val={enriched_artifact['audit']['val_leak_count']} "
                f"test={enriched_artifact['audit']['test_leak_count']}"
            )

        async with async_session() as session:
            run = await session.get(OptimizerRun, run_id)
            run.status = "completed"
            run.initial_score = result.initial_score     # val baseline
            run.final_score   = result.final_score       # val after optimization (governor signal)
            run.trajectory    = result.trajectory
            run.artifact      = enriched_artifact
            run.optimized_prompt = result.optimized_prompt
            run.total_tokens  = result.total_tokens + test_tokens
            run.total_cost    = round(result.total_cost_usd + test_cost, 6)
            await session.commit()

        # Filesystem audit trail: write the optimized prompt as a versioned
        # artifact under workspace/project_<pid>/prompts/<dim>/<optimizer>/.
        # DB is still canonical; this is for human inspection / reproducibility.
        try:
            paths = project_paths(f"project_{project_id}")
            prompt_dir = paths["prompts"] / run.dimension_name / run.optimizer_name
            version = next_version(prompt_dir)
            save_text(prompt_dir / f"{version}.txt", result.optimized_prompt or "")
            save_yaml(prompt_dir / f"{version}.meta.yaml", {
                "version": version,
                "optimizer": run.optimizer_name,
                "dimension": run.dimension_name,
                "project_id": project_id,
                "optimizer_run_id": run_id,
                "initial_score_val": result.initial_score,
                "final_score_val": result.final_score,
                "test_initial_score": enriched_artifact.get("test", {}).get("initial_score"),
                "test_final_score": enriched_artifact.get("test", {}).get("final_score"),
                "n_rules": len((enriched_artifact or {}).get("rule_library") or []),
                "total_tokens": result.total_tokens + test_tokens,
                "total_cost_usd": round(result.total_cost_usd + test_cost, 6),
                "llm_provider": provider,
                "llm_model": model,
                "created_at": utc_now_iso(),
            })
        except Exception:
            logger.warning(f"Filesystem prompt version write failed for run {run_id}", exc_info=True)

        # Persist the final rule library as a new memory version (reflect_agent
        # only — other optimizers don't produce rule libraries).
        if run.optimizer_name == "reflect_agent":
            final_rules = list((result.artifact or {}).get("rule_library") or [])
            new_count = max(0, len(final_rules) - len(seed_rules))
            async with async_session() as session:
                last = await session.execute(
                    select(ReflectMemoryVersion.version)
                    .where(
                        ReflectMemoryVersion.project_id == project_id,
                        ReflectMemoryVersion.dimension_name == run.dimension_name,
                    )
                    .order_by(ReflectMemoryVersion.version.desc())
                    .limit(1)
                )
                last_v = last.scalar() or 0
                session.add(ReflectMemoryVersion(
                    project_id=project_id,
                    dimension_name=run.dimension_name,
                    version=last_v + 1,
                    rules_json=final_rules,
                    new_rules_count=new_count,
                    source_optimizer_run_id=run_id,
                ))
                await session.commit()

    except asyncio.CancelledError:
        logger.info(f"Optimizer run {run_id} cancelled by user")
        try:
            async with async_session() as session:
                run = await session.get(OptimizerRun, run_id)
                if run:
                    run.status = "cancelled"
                    await session.commit()
        except Exception:
            pass
        raise

    except Exception as e:
        logger.exception(f"Optimizer run {run_id} failed")
        try:
            async with async_session() as session:
                run = await session.get(OptimizerRun, run_id)
                if run:
                    run.status = "failed"
                    run.error = str(e)[:2000]
                    await session.commit()
        except Exception:
            pass

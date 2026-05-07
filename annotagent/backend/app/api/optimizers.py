"""Optimizer API — list available optimizers, launch runs, view results."""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import resolve_api_key
from app.database import get_db, async_session
from app.engine.codebook_parser import parse_codebook
from app.engine.prompt_generator import generate_dimension_prompt
from app.utils.storage import next_version, project_paths, save_text, save_yaml, utc_now_iso
from app.models.tables import Codebook, DataItem, Dataset, OptimizerRun, Project, ReflectMemoryVersion
from app.optimizers import Example, evaluate_prompt, get_optimizer, list_optimizers
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
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]


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


from pydantic import BaseModel as _BaseModel


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

    # Validate gold dataset
    gold_dataset = await db.get(Dataset, body.gold_dataset_id)
    if not gold_dataset or gold_dataset.project_id != project_id:
        raise HTTPException(404, "Gold dataset not found")
    if not gold_dataset.is_gold:
        raise HTTPException(400, "Dataset is not marked as gold")

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
            if run.dimension_name not in labels:
                continue
            examples.append(Example(
                sentence=it.content,
                gold=str(labels[run.dimension_name]).strip(),
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

        # Deterministic shuffle — same (gold_dataset_id, dim) always produces the same split.
        rng_seed = hash((run.gold_dataset_id, run.dimension_name)) & 0xFFFF_FFFF
        random.Random(rng_seed).shuffle(examples)

        # Read requested splits from artifact (set at create time); fall back to defaults.
        splits = (run.artifact or {}).get("requested_splits", {})
        train_frac = splits.get("train_frac", run.train_frac or 0.15)
        val_frac = splits.get("val_frac", 0.42)
        test_frac = splits.get("test_frac", max(0.0, 1.0 - train_frac - val_frac))

        n_total = len(examples)
        # Floor counts to respect user's intent, leave test as remainder so splits sum exactly
        n_train = max(5, int(round(train_frac * n_total)))
        n_val   = max(5, int(round(val_frac * n_total)))
        n_test  = max(0, n_total - n_train - n_val)
        # If test is too small (< 3), steal from train until test has 3
        if n_test < 3 and n_train > 5:
            steal = min(3 - n_test, n_train - 5)
            n_train -= steal
            n_test  += steal

        trainset = examples[:n_train]
        valset   = examples[n_train : n_train + n_val]
        testset  = examples[n_train + n_val : n_train + n_val + n_test]

        # LEAKAGE GUARD: assert sets are disjoint (cheap O(n) sanity check).
        assert len({id(x) for x in trainset} & {id(x) for x in valset}) == 0
        assert len({id(x) for x in valset}   & {id(x) for x in testset}) == 0
        assert len({id(x) for x in trainset} & {id(x) for x in testset}) == 0

        logger.info(
            f"Run {run_id} split: total={n_total} train={n_train} val={n_val} test={n_test} "
            f"(seed={rng_seed})"
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
        if testset:
            # Score the initial (unoptimized) prompt on test, so the user can see
            # the lift attributable to optimization, not just prompt quality.
            test_initial_acc, _, ti_tok, ti_cost = await evaluate_prompt(
                initial_prompt, testset, valid_labels,
                provider=provider, model=model, api_key=api_key,
            )
            test_final_acc, _, tf_tok, tf_cost = await evaluate_prompt(
                result.optimized_prompt, testset, valid_labels,
                provider=provider, model=model, api_key=api_key,
            )
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
        }
        enriched_artifact["test"] = {
            "initial_score": round(test_initial_acc, 4),
            "final_score":   round(test_final_acc, 4),
            "delta":         round(test_final_acc - test_initial_acc, 4),
            "n":             n_test,
            "tokens":        test_tokens,
            "cost_usd":      round(test_cost, 6),
            "leakage_guard": "test examples were never passed to the optimizer",
        }

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

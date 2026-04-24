"""Calibration API routes — run calibration loop, view report."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import resolve_api_key
from app.database import get_db
from app.models.tables import (
    AnnotationJob, AnnotationResult, CalibrationRun, Codebook,
    DataItem, Dataset, Dimension, Label as LabelModel, Pipeline, Project,
)
from app.schemas.schemas import CalibrationRequest, CalibrationOut
from app.agents.calibration import run_calibration

router = APIRouter(
    prefix="/api/projects/{project_id}/jobs/{job_id}/calibration",
    tags=["calibration"],
)


@router.post("", response_model=CalibrationOut, status_code=201)
async def create_calibration(
    project_id: int,
    job_id: int,
    body: CalibrationRequest,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    gold_dataset = await db.get(Dataset, body.gold_dataset_id)
    if not gold_dataset or not gold_dataset.is_gold:
        raise HTTPException(400, "Gold dataset not found or not marked as gold")

    # Predictions from the job, keyed by data_item_id
    ann_result = await db.execute(
        select(AnnotationResult).where(AnnotationResult.job_id == job_id)
    )
    annotations = ann_result.scalars().all()

    pred_map: dict[int, dict[str, str]] = {}
    for ann in annotations:
        pred_map.setdefault(ann.data_item_id, {})[ann.dimension_name] = ann.predicted_label

    # Gold items ordered by index
    gold_q = await db.execute(
        select(DataItem)
        .where(DataItem.dataset_id == body.gold_dataset_id)
        .order_by(DataItem.index)
    )
    gold_items = gold_q.scalars().all()

    # Align predictions to gold items by order (predictions were taken on the original
    # dataset; for the demo we assume the gold dataset mirrors the same items or is a subset).
    predictions = list(pred_map.values())
    gold_labels = [item.gold_labels or {} for item in gold_items[: len(predictions)]]

    dimensions = sorted({ann.dimension_name for ann in annotations})

    # Load pipeline steps + codebook_dims so the calibration loop can re-annotate
    pipeline = await db.get(Pipeline, job.pipeline_id)
    steps = pipeline.steps if pipeline else []

    codebook_dims: dict[str, list[str]] = {}
    cb_q = await db.execute(select(Codebook).where(Codebook.project_id == project_id))
    codebook = cb_q.scalars().first()
    if codebook:
        dim_q = await db.execute(
            select(Dimension).where(Dimension.codebook_id == codebook.id)
        )
        for d in dim_q.scalars().all():
            lbl_q = await db.execute(
                select(LabelModel).where(LabelModel.dimension_id == d.id)
            )
            codebook_dims[d.name] = [l.name for l in lbl_q.scalars().all()]

    gold_payload = [
        {"content": item.content, "context": item.context or ""}
        for item in gold_items
    ]

    cal_result = await run_calibration(
        predictions=predictions,
        gold_labels=gold_labels,
        dimensions=dimensions,
        gold_items=gold_payload,
        steps=steps,
        codebook_dims=codebook_dims,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    )

    # Stash before/after/delta/refined_steps in the existing metrics_json JSON column
    # to avoid a DB migration.
    metrics_blob = {
        "before": cal_result["before"],
        "after": cal_result["after"],
        "delta": cal_result["delta"],
        "refined_steps": cal_result["refined_steps"],
        "total_errors": cal_result["total_errors"],
        "total_items": cal_result["total_items"],
    }

    cal_run = CalibrationRun(
        project_id=project_id,
        job_id=job_id,
        gold_dataset_id=body.gold_dataset_id,
        metrics_json=metrics_blob,
        error_patterns=cal_result["error_patterns"],
        rules_generated=cal_result["rules_generated"],
    )
    db.add(cal_run)
    await db.commit()
    await db.refresh(cal_run)
    return cal_run


@router.get("", response_model=list[CalibrationOut])
async def list_calibrations(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(CalibrationRun).where(CalibrationRun.job_id == job_id)
    )
    return result.scalars().all()

"""Results API routes — paginated results, metrics, confusion matrix, export."""
from __future__ import annotations

import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import AnnotationJob, AnnotationResult, DataItem, Dataset
from app.schemas.schemas import AnnotationResultOut, DimensionMetrics
from app.engine.metrics import compute_metrics, confusion_matrix

router = APIRouter(prefix="/api/projects/{project_id}/jobs/{job_id}/results", tags=["results"])


def _norm_dimension_name(value: str) -> str:
    return " ".join(str(value or "").split()).casefold()


def _label_for_dimension(labels: dict, dimension: str):
    if dimension in labels:
        return labels[dimension]
    target = _norm_dimension_name(dimension)
    for key, value in labels.items():
        if _norm_dimension_name(key) == target:
            return value
    return None


def _metadata_value(metadata: dict, candidates: tuple[str, ...]) -> str:
    for key in candidates:
        value = metadata.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _gold_from_coding_metadata(metadata: dict, dimension: str) -> str:
    """Extract labels from coder CSV rows that store theme/level as metadata."""
    theme = _metadata_value(metadata, ("Coding theme", "coding theme", "Unnamed: 3"))
    label = _metadata_value(metadata, ("Level", "level", "Label", "label", "Unnamed: 4"))
    if _norm_dimension_name(theme) == _norm_dimension_name(dimension) and label:
        return label
    return ""


def _display_content(item: DataItem) -> str:
    """Prefer human-readable quote columns over row IDs in coder CSV uploads."""
    metadata = item.metadata_ or {}
    quote = _metadata_value(metadata, ("Relevant quotes", "Relevant quotes ", "quote", "Quote", "Unnamed: 6"))
    return quote or item.content


@router.get("", response_model=list[AnnotationResultOut])
async def get_results(
    project_id: int,
    job_id: int,
    limit: int = 50,
    offset: int = 0,
    dimension: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    query = select(AnnotationResult).where(AnnotationResult.job_id == job_id)
    if dimension:
        query = query.where(AnnotationResult.dimension_name == dimension)
    query = query.order_by(AnnotationResult.data_item_id, AnnotationResult.step_order)
    query = query.offset(offset).limit(limit)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/metrics", response_model=list[DimensionMetrics])
async def get_metrics(
    project_id: int,
    job_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Compute metrics per dimension (requires gold labels in dataset)."""
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    # Get all results
    result = await db.execute(
        select(AnnotationResult).where(AnnotationResult.job_id == job_id)
    )
    annotations = result.scalars().all()

    # Group by dimension
    dim_results: dict[str, list[AnnotationResult]] = {}
    for ann in annotations:
        dim_results.setdefault(ann.dimension_name, []).append(ann)

    # Get gold labels from data items
    item_ids = list({ann.data_item_id for ann in annotations})
    gold_map: dict[int, dict] = {}
    if item_ids:
        items_result = await db.execute(
            select(DataItem).where(DataItem.id.in_(item_ids))
        )
        for item in items_result.scalars().all():
            gold_map[item.id] = item.gold_labels or {}

    metrics_list = []
    for dim_name, anns in dim_results.items():
        y_true, y_pred = [], []
        for ann in anns:
            gold = gold_map.get(ann.data_item_id, {})
            gt = gold.get(dim_name, "")
            if gt:
                y_true.append(gt)
                y_pred.append(ann.predicted_label)

        if y_true:
            m = compute_metrics(y_true, y_pred)
            metrics_list.append(DimensionMetrics(dimension=dim_name, metrics=m))

    return metrics_list


@router.get("/confusion", response_model=dict)
async def get_confusion_matrix(
    project_id: int,
    job_id: int,
    dimension: str,
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    result = await db.execute(
        select(AnnotationResult)
        .where(AnnotationResult.job_id == job_id)
        .where(AnnotationResult.dimension_name == dimension)
    )
    annotations = result.scalars().all()

    item_ids = [ann.data_item_id for ann in annotations]
    gold_map: dict[int, dict] = {}
    if item_ids:
        items_result = await db.execute(
            select(DataItem).where(DataItem.id.in_(item_ids))
        )
        for item in items_result.scalars().all():
            gold_map[item.id] = item.gold_labels or {}

    y_true, y_pred = [], []
    for ann in annotations:
        gold = gold_map.get(ann.data_item_id, {})
        gt = gold.get(dimension, "")
        if gt:
            y_true.append(gt)
            y_pred.append(ann.predicted_label)

    if not y_true:
        return {"classes": [], "matrix": {}}

    return confusion_matrix(y_true, y_pred)


@router.get("/evidence", response_model=list[dict])
async def get_feedback_evidence(
    project_id: int,
    job_id: int,
    dimension: str,
    limit: int = 50,
    offset: int = 0,
    mismatches_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Return annotated examples enriched with source text and gold labels.

    This is shaped for the Human feedback tab, where annotators need to see
    what the model predicted before writing correction notes.
    """
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    result = await db.execute(
        select(AnnotationResult, DataItem)
        .join(DataItem, AnnotationResult.data_item_id == DataItem.id)
        .where(AnnotationResult.job_id == job_id)
        .order_by(AnnotationResult.data_item_id, AnnotationResult.step_order)
    )

    gold_by_content: dict[str, dict] = {}
    gold_items = await db.execute(
        select(DataItem)
        .join(Dataset, DataItem.dataset_id == Dataset.id)
        .where(Dataset.project_id == project_id)
        .where(Dataset.is_gold.is_(True))
    )
    for item in gold_items.scalars().all():
        if item.content and item.gold_labels:
            gold_by_content.setdefault(item.content, item.gold_labels or {})

    rows = []
    target_dimension = _norm_dimension_name(dimension)
    for ann, item in result.all():
        if _norm_dimension_name(ann.dimension_name) != target_dimension:
            continue
        labels = item.gold_labels or gold_by_content.get(item.content, {}) or {}
        gold = _label_for_dimension(labels, dimension)
        gold_label = ", ".join(map(str, gold)) if isinstance(gold, list) else (str(gold) if gold is not None else "")
        if not gold_label:
            gold_label = _gold_from_coding_metadata(item.metadata_ or {}, dimension)
        predicted = ann.predicted_label or ""
        is_mismatch = bool(gold_label) and predicted != gold_label
        if mismatches_only and not is_mismatch:
            continue
        rows.append({
            "result_id": ann.id,
            "item_id": item.id,
            "content": _display_content(item),
            "context": item.context or "",
            "gold_label": gold_label,
            "predicted_label": predicted,
            "reasoning": ann.reasoning or "",
            "is_mismatch": is_mismatch,
        })

    rows.sort(key=lambda r: (not r["is_mismatch"], r["item_id"]))
    return rows[offset:offset + limit]


@router.get("/export")
async def export_results(
    project_id: int,
    job_id: int,
    format: str = "csv",
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    result = await db.execute(
        select(AnnotationResult)
        .where(AnnotationResult.job_id == job_id)
        .order_by(AnnotationResult.data_item_id, AnnotationResult.step_order)
    )
    annotations = result.scalars().all()

    # Get data items for content
    item_ids = list({ann.data_item_id for ann in annotations})
    item_map: dict[int, DataItem] = {}
    if item_ids:
        items_result = await db.execute(
            select(DataItem).where(DataItem.id.in_(item_ids))
        )
        for item in items_result.scalars().all():
            item_map[item.id] = item

    # Pivot: one row per data item with dimension columns
    rows: dict[int, dict] = {}
    for ann in annotations:
        if ann.data_item_id not in rows:
            item = item_map.get(ann.data_item_id)
            rows[ann.data_item_id] = {
                "item_id": ann.data_item_id,
                "content": item.content if item else "",
            }
        rows[ann.data_item_id][ann.dimension_name] = ann.predicted_label

    if format == "json":
        return list(rows.values())

    # CSV
    all_dims = sorted({ann.dimension_name for ann in annotations})
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["item_id", "content"] + all_dims)
    for row in rows.values():
        writer.writerow([row.get("item_id", ""), row.get("content", "")] + [row.get(d, "") for d in all_dims])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=job_{job_id}_results.csv"},
    )

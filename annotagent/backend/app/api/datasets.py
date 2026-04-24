"""Dataset API routes — upload CSV/JSON, parse into data_items; preview; load seeds."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models.tables import Dataset, DataItem, Project
from app.schemas.schemas import DatasetOut, DatasetPreview, DataItemOut
from app.utils.file_parsers import parse_json_dataset, parse_csv_dataset

router = APIRouter(prefix="/api/projects/{project_id}/datasets", tags=["datasets"])


# Known seed files ship with the repo under SEED_DATA_DIR (project-root /data).
# `relpath` is relative to SEED_DATA_DIR so entries can reference any subfolder.
# `role` tells the frontend how to suggest gold-vs-regular-vs-test defaults.
SEED_FILES = [
    {
        "id": "sd_agreed",
        "label": "Self-disclosure · Agreed (Fiona ∩ Chang)",
        "relpath": "cleaned/agreed_self_disclosure_ground_truth.json",
        "role": "gold",
        "description": "169 items on which both annotators agreed on at least one dimension.",
    },
    {
        "id": "sd_fiona",
        "label": "Self-disclosure · Fiona",
        "relpath": "cleaned/fiona_self_disclosure_ground_truth.json",
        "role": "reference",
        "description": "Annotator 1 (Fiona) full set, 333 unique quotes.",
    },
    {
        "id": "sd_chang",
        "label": "Self-disclosure · Chang",
        "relpath": "cleaned/chang_self_disclosure_ground_truth.json",
        "role": "reference",
        "description": "Annotator 2 (Chang) full set, 331 unique quotes.",
    },
    {
        "id": "test_v1",
        "label": "Test set · v1 (unseen)",
        "relpath": "test/cleaned/test_data_v1.json",
        "role": "test",
        "description": "58 unlabeled sentences from held-out companion dialogues. Default target for the annotator to predict on.",
    },
    {
        "id": "test_v2",
        "label": "Test set · v2 (unseen)",
        "relpath": "test/cleaned/test_data_v2.json",
        "role": "test",
        "description": "206 unlabeled sentences, expanded test set for evaluation.",
    },
    {
        "id": "goemotions_sample",
        "label": "GoEmotions · reproducibility sample (public)",
        "relpath": "cleaned/goemotions_sample.json",
        "role": "gold",
        "description": "30 items with multi-label emotion gold labels. Open-data reproducibility substrate — pair with the 'goemotions' preset.",
    },
]


class SeedLoadRequest(BaseModel):
    seed_id: str
    is_gold: bool | None = None   # overrides the seed's default role when set


@router.post("", response_model=DatasetOut, status_code=201)
async def upload_dataset(
    project_id: int,
    file: UploadFile = File(...),
    is_gold: bool = Form(False),
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    content = (await file.read()).decode("utf-8")
    filename = file.filename or "dataset"

    if filename.endswith(".csv"):
        items = parse_csv_dataset(content)
        file_type = "csv"
    else:
        items = parse_json_dataset(content)
        file_type = "json"

    dataset = Dataset(
        project_id=project_id,
        name=filename,
        file_type=file_type,
        total_items=len(items),
        is_gold=is_gold,
    )
    db.add(dataset)
    await db.flush()

    for item in items:
        data_item = DataItem(
            dataset_id=dataset.id,
            index=item["index"],
            content=item["content"],
            context=item.get("context", ""),
            metadata_=item.get("metadata", {}),
            gold_labels=item.get("gold_labels", {}),
        )
        db.add(data_item)

    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("", response_model=list[DatasetOut])
async def list_datasets(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Dataset).where(Dataset.project_id == project_id)
    )
    return result.scalars().all()


@router.get("/{dataset_id}", response_model=DatasetPreview)
async def preview_dataset(
    project_id: int,
    dataset_id: int,
    limit: int = 20,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    dataset = await db.get(Dataset, dataset_id)
    if not dataset or dataset.project_id != project_id:
        raise HTTPException(404, "Dataset not found")

    result = await db.execute(
        select(DataItem)
        .where(DataItem.dataset_id == dataset_id)
        .order_by(DataItem.index)
        .offset(offset)
        .limit(limit)
    )
    items = result.scalars().all()
    return DatasetPreview(dataset=dataset, items=items)


@router.delete("/{dataset_id}", status_code=204)
async def delete_dataset(
    project_id: int,
    dataset_id: int,
    db: AsyncSession = Depends(get_db),
):
    dataset = await db.get(Dataset, dataset_id)
    if not dataset or dataset.project_id != project_id:
        raise HTTPException(404, "Dataset not found")
    await db.delete(dataset)
    await db.commit()


@router.get("/seeds/available")
async def list_seed_datasets(project_id: int):
    """List seed datasets that can be loaded into this project in one click."""
    seed_dir = Path(settings.SEED_DATA_DIR)
    out = []
    for spec in SEED_FILES:
        path = seed_dir / spec["relpath"]
        out.append({**spec, "available": path.exists(), "path": str(path)})
    return out


@router.post("/seeds/load", response_model=DatasetOut, status_code=201)
async def load_seed_dataset(
    project_id: int,
    body: SeedLoadRequest,
    db: AsyncSession = Depends(get_db),
):
    """Load a known seed JSON from SEED_DATA_DIR into this project as a Dataset."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    spec = next((s for s in SEED_FILES if s["id"] == body.seed_id), None)
    if not spec:
        raise HTTPException(404, f"Unknown seed id: {body.seed_id}")

    seed_path = Path(settings.SEED_DATA_DIR) / spec["relpath"]
    if not seed_path.exists():
        raise HTTPException(
            404,
            f"Seed file not found at {seed_path}. Set SEED_DATA_DIR env var or place the file there.",
        )

    content = seed_path.read_text(encoding="utf-8")
    items = parse_json_dataset(content)

    is_gold = body.is_gold if body.is_gold is not None else (spec["role"] == "gold")

    dataset = Dataset(
        project_id=project_id,
        name=spec["label"],
        file_type="json",
        total_items=len(items),
        is_gold=is_gold,
    )
    db.add(dataset)
    await db.flush()

    for item in items:
        data_item = DataItem(
            dataset_id=dataset.id,
            index=item["index"],
            content=item["content"],
            context=item.get("context", ""),
            metadata_=item.get("metadata", {}),
            gold_labels=item.get("gold_labels", {}),
        )
        db.add(data_item)

    await db.commit()
    await db.refresh(dataset)
    return dataset

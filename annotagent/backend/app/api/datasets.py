"""Dataset API routes — upload CSV/JSON, parse into data_items; preview; load seeds."""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import resolve_api_key, settings
from app.database import get_db
from app.engine.codebook_parser import parse_codebook
from app.engine.gold_align import (
    apply_transform, autofix_items, build_gold_schema, canonicalize_items,
    schema_for_ui, validate_items,
)
from app.models.tables import (
    AnnotationJob, AnnotationResult, CalibrationRun, Codebook, Dataset, DataItem,
    OptimizerRun, Project,
)
from app.schemas.schemas import DatasetOut, DatasetPreview, DataItemOut
from app.utils.file_parsers import parse_json_dataset, parse_csv_dataset

router = APIRouter(prefix="/api/projects/{project_id}/datasets", tags=["datasets"])


def _norm_dim(value: str) -> str:
    """Normalize a dimension name for matching (mirrors optimizers._norm_dimension_name)."""
    text = re.sub(r"\([^)]*\)", " ", str(value or ""))
    text = re.sub(r"[^0-9a-zA-Z]+", " ", text)
    return " ".join(text.split()).casefold()


async def _codebook_dim_map(db: AsyncSession, project_id: int) -> dict[str, str] | None:
    """norm-name -> canonical dimension name for the project's active (latest) codebook.

    Returns None when the project has no codebook yet, in which case gold labels are
    stored unfiltered.
    """
    codebook = (await db.execute(
        select(Codebook).where(Codebook.project_id == project_id)
        .order_by(Codebook.id.desc()).limit(1)
    )).scalars().first()
    if not codebook:
        return None
    parsed = parse_codebook(codebook.raw_json)
    return {_norm_dim(d.name): d.name for d in parsed.dimensions}


def _filter_gold_labels(labels: dict, dim_map: dict[str, str] | None) -> dict:
    """Keep only gold labels whose dimension exists in the codebook; drop the rest.

    The codebook is the schema of record, so a gold file carrying extra dimensions
    (for example Topic or Temporality) contributes only the dimensions the codebook
    actually defines. Keys are canonicalized to the codebook's spelling.
    """
    if not dim_map:
        return labels or {}
    out: dict = {}
    for key, value in (labels or {}).items():
        canonical = dim_map.get(_norm_dim(key))
        if canonical is not None:
            out[canonical] = value
    return out


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

    # Gold labels follow the codebook schema: drop any dimension the codebook does
    # not define so a richer gold file only contributes the active dimensions.
    dim_map = await _codebook_dim_map(db, project_id) if is_gold else None

    for item in items:
        data_item = DataItem(
            dataset_id=dataset.id,
            index=item["index"],
            content=item["content"],
            context=item.get("context", ""),
            metadata_=item.get("metadata", {}),
            gold_labels=_filter_gold_labels(item.get("gold_labels", {}), dim_map),
        )
        db.add(data_item)

    await db.commit()
    await db.refresh(dataset)
    return dataset


# ─── schema-aware validation + LLM auto-fix for labeled (gold) uploads ───────

async def _active_codebook_raw(db: AsyncSession, project_id: int) -> dict | None:
    codebook = (await db.execute(
        select(Codebook).where(Codebook.project_id == project_id)
        .order_by(Codebook.id.desc()).limit(1)
    )).scalars().first()
    return codebook.raw_json if codebook else None


async def _project_llm(db: AsyncSession, project: Project) -> tuple[str, str, str]:
    provider = project.llm_provider or "openai"
    model = project.llm_model or ("claude-sonnet-4-5-20250929" if provider == "anthropic" else "gpt-5.4-mini")
    api_key = resolve_api_key(provider, project.api_key_encrypted)
    if not api_key:
        raise HTTPException(400, f"No {provider} API key available for the auto-fix LLM.")
    return provider, model, api_key


def _parse_upload(content: str, filename: str) -> tuple[list[dict], str]:
    if filename.endswith(".csv"):
        return parse_csv_dataset(content), "csv"
    return parse_json_dataset(content), "json"


async def _persist_items(db: AsyncSession, project_id: int, name: str, file_type: str,
                         is_gold: bool, items: list[dict]) -> Dataset:
    dataset = Dataset(project_id=project_id, name=name, file_type=file_type,
                      total_items=len(items), is_gold=is_gold)
    db.add(dataset)
    await db.flush()
    for i, item in enumerate(items):
        db.add(DataItem(
            dataset_id=dataset.id,
            index=item.get("index", i),
            content=item.get("content", ""),
            context=item.get("context", ""),
            metadata_=item.get("metadata", {}),
            gold_labels=item.get("gold_labels", {}),
        ))
    await db.commit()
    await db.refresh(dataset)
    return dataset


@router.get("/schema")
async def get_expected_schema(project_id: int, db: AsyncSession = Depends(get_db)):
    """The codebook schema labeled data must match (for the UI to display)."""
    raw = await _active_codebook_raw(db, project_id)
    if raw is None:
        raise HTTPException(400, "No codebook yet — accept a codebook before uploading labeled data.")
    return schema_for_ui(raw)


@router.post("/validate")
async def validate_labeled_upload(
    project_id: int,
    file: UploadFile = File(...),
    is_gold: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """Dry run: parse + validate labeled data against the codebook. Persists nothing.
    Returns the parsed items (echoed back for the auto-fix / commit steps) and a report."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    raw = await _active_codebook_raw(db, project_id)
    if raw is None:
        raise HTTPException(400, "Accept a codebook before uploading labeled data.")

    content = (await file.read()).decode("utf-8")
    filename = file.filename or "dataset"
    items, file_type = _parse_upload(content, filename)
    schema = build_gold_schema(raw)
    report = validate_items(items, schema)
    return {"filename": filename, "file_type": file_type, "is_gold": is_gold,
            "items": items, "report": report, "schema": schema_for_ui(raw)}


class _ItemsBody(BaseModel):
    items: list[dict]


@router.post("/autofix")
async def autofix_labeled_upload(
    project_id: int,
    body: _ItemsBody,
    db: AsyncSession = Depends(get_db),
):
    """Run the structured-mapping ReAct loop to align items to the codebook.
    Returns {items, trace, report} — still persists nothing."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    raw = await _active_codebook_raw(db, project_id)
    if raw is None:
        raise HTTPException(400, "Accept a codebook before auto-fixing labeled data.")
    provider, model, api_key = await _project_llm(db, project)
    schema = build_gold_schema(raw)
    return await autofix_items(body.items, schema, provider=provider, model=model, api_key=api_key)


class _ApplyFixBody(BaseModel):
    items: list[dict]
    spec: dict   # {dimension_map, label_map, multi_split, drop_dimensions, content_from}


@router.post("/apply-fix")
async def apply_fix_labeled_upload(
    project_id: int,
    body: _ApplyFixBody,
    db: AsyncSession = Depends(get_db),
):
    """Apply a user-built transform spec (manual mismatch fixes) deterministically
    and re-validate. Same spec shape the LLM auto-fix produces — no LLM here."""
    raw = await _active_codebook_raw(db, project_id)
    if raw is None:
        raise HTTPException(400, "Accept a codebook before fixing labeled data.")
    schema = build_gold_schema(raw)
    fixed = apply_transform(body.items, body.spec or {}, schema)
    return {"items": fixed, "report": validate_items(fixed, schema)}


class _CommitBody(BaseModel):
    name: str = "labeled_data"
    is_gold: bool = True
    file_type: str = "json"
    items: list[dict]


@router.post("/commit", response_model=DatasetOut, status_code=201)
async def commit_labeled_dataset(
    project_id: int,
    body: _CommitBody,
    db: AsyncSession = Depends(get_db),
):
    """Persist already-validated items. Gold labels are snapped to the codebook's
    canonical spelling (and unknown dimensions dropped) before storing."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    items = body.items
    if body.is_gold:
        raw = await _active_codebook_raw(db, project_id)
        if raw is not None:
            items = canonicalize_items(items, build_gold_schema(raw))
    return await _persist_items(db, project_id, body.name, body.file_type, body.is_gold, items)


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

    # Walk the subtree explicitly: the live SQLite FKs predate the ondelete=CASCADE
    # migration, so a bare delete on a dataset with data_items / jobs / runs fails.
    job_ids = select(AnnotationJob.id).where(AnnotationJob.dataset_id == dataset_id)
    di_ids = select(DataItem.id).where(DataItem.dataset_id == dataset_id)

    await db.execute(delete(AnnotationResult).where(AnnotationResult.job_id.in_(job_ids)))
    await db.execute(delete(AnnotationResult).where(AnnotationResult.data_item_id.in_(di_ids)))
    await db.execute(delete(CalibrationRun).where(CalibrationRun.job_id.in_(job_ids)))
    await db.execute(delete(CalibrationRun).where(CalibrationRun.gold_dataset_id == dataset_id))
    await db.execute(delete(AnnotationJob).where(AnnotationJob.dataset_id == dataset_id))
    # Optimizer runs keep their history; just drop the gold link (model: SET NULL).
    await db.execute(update(OptimizerRun).where(OptimizerRun.gold_dataset_id == dataset_id)
                     .values(gold_dataset_id=None))
    await db.execute(delete(DataItem).where(DataItem.dataset_id == dataset_id))
    await db.execute(delete(Dataset).where(Dataset.id == dataset_id))
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

    # Gold labels follow the codebook schema (see _filter_gold_labels). A seed like
    # the self-disclosure agreed set ships more dimensions than a trimmed codebook;
    # only the codebook's dimensions are loaded.
    dim_map = await _codebook_dim_map(db, project_id) if is_gold else None

    for item in items:
        data_item = DataItem(
            dataset_id=dataset.id,
            index=item["index"],
            content=item["content"],
            context=item.get("context", ""),
            metadata_=item.get("metadata", {}),
            gold_labels=_filter_gold_labels(item.get("gold_labels", {}), dim_map),
        )
        db.add(data_item)

    await db.commit()
    await db.refresh(dataset)
    return dataset

"""Codebook API routes — upload JSON, parse, validate; list presets."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models.tables import Codebook, CodebookDraft, Dimension, Label, Project, DimensionType
from app.schemas.schemas import (
    AcceptDraftRequest, CodebookOut, CodebookUpload, PresetInfo,
)
from app.config import resolve_api_key
from app.engine.codebook_parser import parse_codebook, validate_codebook
from app.engine.auto_prompt_generator import agenerate_prompts_per_dimension
from app.utils.storage import next_version, project_paths, save_text, save_yaml, utc_now_iso

router = APIRouter(prefix="/api/projects/{project_id}/codebooks", tags=["codebooks"])

PRESETS_DIR = Path(__file__).parent.parent / "presets"

# Display order for the wizard's preset list. Anything not listed here
# falls to the back, alphabetized.
_PRESET_ORDER = ["ai_behavior", "self_disclosure", "harm"]


@router.get("/presets", response_model=list[PresetInfo])
async def list_presets(project_id: int):
    """List available codebook presets, ordered for the wizard."""
    presets = []
    for f in PRESETS_DIR.glob("*.json"):
        with open(f) as fp:
            data = json.load(fp)
        presets.append(PresetInfo(
            name=f.stem,
            description=data.get("description", ""),
            dimensions=len(data.get("dimensions", [])),
        ))
    rank = {n: i for i, n in enumerate(_PRESET_ORDER)}
    presets.sort(key=lambda p: (rank.get(p.name, len(_PRESET_ORDER)), p.name))
    return presets


@router.post("", response_model=CodebookOut, status_code=201)
async def upload_codebook(
    project_id: int,
    body: CodebookUpload,
    db: AsyncSession = Depends(get_db),
):
    """Upload a codebook JSON or load from preset."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    if body.preset_name:
        preset_path = PRESETS_DIR / f"{body.preset_name}.json"
        if not preset_path.exists():
            raise HTTPException(404, f"Preset '{body.preset_name}' not found")
        with open(preset_path) as fp:
            raw_json = json.load(fp)
    elif body.raw_json:
        raw_json = body.raw_json
    else:
        raise HTTPException(400, "Provide either preset_name or raw_json")

    errors = validate_codebook(raw_json)
    if errors:
        raise HTTPException(422, detail=errors)

    parsed = parse_codebook(raw_json)

    codebook = Codebook(
        project_id=project_id,
        name=parsed.name,
        description=parsed.description,
        raw_json=raw_json,
    )
    db.add(codebook)
    await db.flush()

    for i, dim_def in enumerate(parsed.dimensions):
        dim = Dimension(
            codebook_id=codebook.id,
            name=dim_def.name,
            dim_type=DimensionType(dim_def.dim_type),
            instructions=dim_def.instructions,
            sort_order=i,
        )
        db.add(dim)
        await db.flush()

        for j, lbl_def in enumerate(dim_def.labels):
            label = Label(
                dimension_id=dim.id,
                name=lbl_def.name,
                definition=lbl_def.definition,
                examples=lbl_def.examples,
                sort_order=j,
            )
            db.add(label)

    await db.commit()

    # Reload with eagerly-loaded relationships to avoid async lazy-load.
    result = await db.execute(
        select(Codebook)
        .where(Codebook.id == codebook.id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
    )
    return result.scalars().first()


class AutoPromptRequest(BaseModel):
    task_type: str = "text_annotation"


class DimensionPrompt(BaseModel):
    dimension_name: str
    prompt: str
    version: str
    path: str
    error: str | None = None


class AutoPromptResponse(BaseModel):
    prompts: list[DimensionPrompt]


@router.post("/{codebook_id}/auto-prompt", response_model=AutoPromptResponse)
async def auto_generate_prompt(
    project_id: int,
    codebook_id: int,
    body: AutoPromptRequest,
    db: AsyncSession = Depends(get_db),
):
    """LLM-generate one annotation prompt per dimension, in parallel.

    Each dimension's prompt is saved as
    ``workspace/project_<id>/prompts/<dim_name>/auto_vNNN.txt`` with a sibling
    ``.meta.yaml``. Per-dimension matches the multi-step pipeline + per-
    dimension optimizer architecture; the deterministic Jinja generator in
    ``engine/prompt_generator.py`` remains the path for preset/gallery prompts.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    api_key = resolve_api_key(project.llm_provider, project.api_key_encrypted)
    if not api_key:
        raise HTTPException(
            400,
            f"No {project.llm_provider} API key available. Set one in Setup or add it to the backend .env.",
        )

    cb = await db.get(Codebook, codebook_id)
    if not cb or cb.project_id != project_id:
        raise HTTPException(404, "Codebook not found for this project")

    parsed = parse_codebook(cb.raw_json or {})
    if not parsed.dimensions:
        raise HTTPException(400, "Codebook has no dimensions")

    results = await agenerate_prompts_per_dimension(
        parsed.dimensions,
        task_type=body.task_type,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=api_key,
    )

    paths = project_paths(f"project_{project_id}")
    out: list[DimensionPrompt] = []
    for dim_name, res in results:
        # Sanitize dim name for filesystem (spaces / slashes happen in real codebooks).
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in dim_name)
        dim_dir = paths["prompts"] / safe
        version = next_version(dim_dir, prefix="auto_v")

        if isinstance(res, Exception):
            out.append(DimensionPrompt(
                dimension_name=dim_name, prompt="", version=version,
                path=str(dim_dir / f"{version}.txt"), error=repr(res),
            ))
            continue

        prompt_path = dim_dir / f"{version}.txt"
        save_text(prompt_path, res)
        save_yaml(dim_dir / f"{version}.meta.yaml", {
            "version": version,
            "source": "auto_prompt_generator",
            "codebook_id": codebook_id,
            "codebook_name": cb.name,
            "dimension_name": dim_name,
            "task_type": body.task_type,
            "llm_provider": project.llm_provider,
            "llm_model": project.llm_model,
            "created_at": utc_now_iso(),
        })
        out.append(DimensionPrompt(
            dimension_name=dim_name, prompt=res, version=version,
            path=str(prompt_path), error=None,
        ))

    return AutoPromptResponse(prompts=out)


@router.get("", response_model=list[CodebookOut])
async def list_codebooks(project_id: int, db: AsyncSession = Depends(get_db)):
    # Oldest → newest. Frontend treats codebooks[length-1] as the active one,
    # so this ordering must match every backend lookup that uses
    # ``order_by(Codebook.id.desc()).limit(1)`` to pick the latest.
    result = await db.execute(
        select(Codebook)
        .where(Codebook.project_id == project_id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
        .order_by(Codebook.id.asc())
    )
    return result.scalars().all()


@router.post("/accept-draft", response_model=CodebookOut, status_code=201)
async def accept_draft(
    project_id: int,
    body: AcceptDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """Commit a CodebookDraft to this project. Strips _meta / _rationale,
    validates, and hydrates Dimension/Label rows."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    draft = await db.get(CodebookDraft, body.draft_id)
    if not draft:
        raise HTTPException(404, "Draft not found")
    if draft.status != "ready":
        raise HTTPException(409, f"Draft status is {draft.status!r}; only 'ready' drafts can be accepted.")

    raw_json = dict(draft.draft_json or {})
    # Strip non-persistent metadata
    for k in list(raw_json.keys()):
        if k.startswith("_"):
            raw_json.pop(k)
    for dim in raw_json.get("dimensions", []):
        if isinstance(dim, dict):
            for k in list(dim.keys()):
                if k.startswith("_"):
                    dim.pop(k)

    errors = validate_codebook(raw_json)
    if errors:
        raise HTTPException(422, detail={"errors": errors,
                                          "message": "Draft failed validation on accept"})

    parsed = parse_codebook(raw_json)

    codebook = Codebook(
        project_id=project_id,
        name=parsed.name,
        description=parsed.description,
        raw_json=raw_json,
    )
    db.add(codebook)
    await db.flush()

    for i, dim_def in enumerate(parsed.dimensions):
        dim = Dimension(
            codebook_id=codebook.id,
            name=dim_def.name,
            dim_type=DimensionType(dim_def.dim_type),
            instructions=dim_def.instructions,
            sort_order=i,
        )
        db.add(dim)
        await db.flush()
        for j, lbl_def in enumerate(dim_def.labels):
            label = Label(
                dimension_id=dim.id,
                name=lbl_def.name,
                definition=lbl_def.definition,
                examples=lbl_def.examples,
                sort_order=j,
            )
            db.add(label)

    # Mark the draft as accepted (but don't delete — user may want history)
    draft.accepted_for_project_id = project_id
    await db.commit()

    # Eager-loaded return
    result = await db.execute(
        select(Codebook)
        .where(Codebook.id == codebook.id)
        .options(selectinload(Codebook.dimensions).selectinload(Dimension.labels))
    )
    return result.scalars().first()

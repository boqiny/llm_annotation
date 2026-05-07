"""Pipeline API routes — decompose, view, edit steps/prompts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import resolve_api_key
from app.database import get_db
from app.models.tables import Pipeline, Codebook, Dimension, Label, Project
from app.schemas.schemas import PipelineOut, PipelineUpdate
from app.engine.codebook_parser import parse_codebook
from app.agents.decomposition import decompose_codebook

router = APIRouter(prefix="/api/projects/{project_id}/pipelines", tags=["pipelines"])


@router.post("/decompose", response_model=PipelineOut, status_code=201)
async def decompose(project_id: int, db: AsyncSession = Depends(get_db)):
    """Trigger DecompositionAgent to generate a pipeline from the project's codebook."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Get codebook (latest = highest id).
    result = await db.execute(
        select(Codebook).where(Codebook.project_id == project_id)
        .order_by(Codebook.id.desc()).limit(1)
    )
    codebook = result.scalars().first()
    if not codebook:
        raise HTTPException(400, "No codebook uploaded for this project")

    parsed = parse_codebook(codebook.raw_json)
    steps = await decompose_codebook(
        codebook=parsed,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
    )

    pipeline = Pipeline(
        project_id=project_id,
        steps=steps,
        auto_generated=True,
    )
    db.add(pipeline)
    await db.commit()
    await db.refresh(pipeline)
    return pipeline


@router.get("", response_model=list[PipelineOut])
async def list_pipelines(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Pipeline).where(Pipeline.project_id == project_id)
    )
    return result.scalars().all()


@router.get("/{pipeline_id}", response_model=PipelineOut)
async def get_pipeline(project_id: int, pipeline_id: int, db: AsyncSession = Depends(get_db)):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.project_id != project_id:
        raise HTTPException(404, "Pipeline not found")
    return pipeline


@router.put("/{pipeline_id}", response_model=PipelineOut)
async def update_pipeline(
    project_id: int,
    pipeline_id: int,
    body: PipelineUpdate,
    db: AsyncSession = Depends(get_db),
):
    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.project_id != project_id:
        raise HTTPException(404, "Pipeline not found")
    pipeline.steps = body.steps
    pipeline.auto_generated = False
    await db.commit()
    await db.refresh(pipeline)
    return pipeline

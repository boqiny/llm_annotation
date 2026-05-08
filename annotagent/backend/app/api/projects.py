"""Project CRUD API routes."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import (
    AnnotationJob, AnnotationResult, CalibrationRun, Codebook, CodebookDraft,
    DataItem, Dataset, Dimension, Label, OptimizerRun, Pipeline, Project,
    ReflectMemoryVersion,
)
from app.schemas.schemas import ProjectCreate, ProjectUpdate, ProjectOut

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("", response_model=list[ProjectOut])
async def list_projects(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Project).order_by(Project.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=ProjectOut, status_code=201)
async def create_project(body: ProjectCreate, db: AsyncSession = Depends(get_db)):
    project = Project(
        name=body.name,
        description=body.description,
        llm_provider=body.llm_provider,
        llm_model=body.llm_model,
        api_key_encrypted=body.api_key,
    )
    db.add(project)
    await db.commit()
    await db.refresh(project)
    return project


@router.get("/{project_id}", response_model=ProjectOut)
async def get_project(project_id: int, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    return project


@router.patch("/{project_id}", response_model=ProjectOut)
async def update_project(project_id: int, body: ProjectUpdate, db: AsyncSession = Depends(get_db)):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")
    update_data = body.model_dump(exclude_unset=True)
    if "api_key" in update_data:
        project.api_key_encrypted = update_data.pop("api_key")
    for key, value in update_data.items():
        setattr(project, key, value)
    await db.commit()
    await db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=204)
async def delete_project(project_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a project and everything that belongs to it.

    The model declares ``ondelete=CASCADE/SET NULL`` on every FK that points
    at a project's tree, but ``create_all`` doesn't run a migration on
    pre-existing tables — so the live DB still has several un-guarded FKs.
    Rather than rely on the schema-level cascade, we walk the tree explicitly
    in dependency order. Idempotent: running on an already-empty tree is a
    no-op.
    """
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    # Codebook drafts outlive the project they were accepted to.
    await db.execute(
        update(CodebookDraft)
        .where(CodebookDraft.accepted_for_project_id == project_id)
        .values(accepted_for_project_id=None)
    )

    # Subqueries we need repeatedly.
    job_ids   = select(AnnotationJob.id).where(AnnotationJob.project_id == project_id)
    ds_ids    = select(Dataset.id).where(Dataset.project_id == project_id)
    cb_ids    = select(Codebook.id).where(Codebook.project_id == project_id)
    di_ids    = select(DataItem.id).where(DataItem.dataset_id.in_(ds_ids))
    dim_ids   = select(Dimension.id).where(Dimension.codebook_id.in_(cb_ids))

    # Leaf rows first; walk inward toward the project row.
    await db.execute(delete(AnnotationResult).where(AnnotationResult.job_id.in_(job_ids)))
    await db.execute(delete(AnnotationResult).where(AnnotationResult.data_item_id.in_(di_ids)))
    await db.execute(delete(CalibrationRun).where(CalibrationRun.project_id == project_id))
    await db.execute(delete(CalibrationRun).where(CalibrationRun.job_id.in_(job_ids)))
    await db.execute(delete(CalibrationRun).where(CalibrationRun.gold_dataset_id.in_(ds_ids)))
    await db.execute(delete(AnnotationJob).where(AnnotationJob.project_id == project_id))
    await db.execute(delete(AnnotationJob).where(AnnotationJob.dataset_id.in_(ds_ids)))
    # Memory: delete project's rows and any sourced from this project's runs.
    await db.execute(delete(ReflectMemoryVersion).where(ReflectMemoryVersion.project_id == project_id))
    await db.execute(delete(OptimizerRun).where(OptimizerRun.project_id == project_id))
    await db.execute(delete(OptimizerRun).where(OptimizerRun.gold_dataset_id.in_(ds_ids)))
    await db.execute(delete(DataItem).where(DataItem.dataset_id.in_(ds_ids)))
    await db.execute(delete(Dataset).where(Dataset.project_id == project_id))
    await db.execute(delete(Pipeline).where(Pipeline.project_id == project_id))
    await db.execute(delete(Label).where(Label.dimension_id.in_(dim_ids)))
    await db.execute(delete(Dimension).where(Dimension.codebook_id.in_(cb_ids)))
    await db.execute(delete(Codebook).where(Codebook.project_id == project_id))
    await db.execute(delete(Project).where(Project.id == project_id))
    await db.commit()

"""Annotation job API routes — start, status, pause/resume."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import resolve_api_key
from app.database import get_db, async_session
from app.models.tables import AnnotationJob, Project, Dataset, Pipeline, JobStatus
from app.schemas.schemas import JobCreate, JobOut
from app.engine.runner import PipelineRunner

router = APIRouter(prefix="/api/projects/{project_id}/jobs", tags=["jobs"])

# Global registry of running jobs
_running_jobs: dict[int, PipelineRunner] = {}


@router.post("", response_model=JobOut, status_code=201)
async def start_job(
    project_id: int,
    body: JobCreate,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    dataset = await db.get(Dataset, body.dataset_id)
    if not dataset or dataset.project_id != project_id:
        raise HTTPException(404, "Dataset not found")

    pipeline = await db.get(Pipeline, body.pipeline_id)
    if not pipeline or pipeline.project_id != project_id:
        raise HTTPException(404, "Pipeline not found")

    job = AnnotationJob(
        project_id=project_id,
        dataset_id=body.dataset_id,
        pipeline_id=body.pipeline_id,
        source=body.source if body.source in {"annotation", "human_feedback"} else "annotation",
        total_items=dataset.total_items,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Launch runner in background
    from app.api.ws import broadcast_to_job

    runner = PipelineRunner(
        job_id=job.id,
        session_factory=async_session,
        provider=project.llm_provider,
        model=project.llm_model,
        api_key=resolve_api_key(project.llm_provider, project.api_key_encrypted),
        ws_callback=broadcast_to_job,
    )
    _running_jobs[job.id] = runner
    asyncio.create_task(_run_and_cleanup(job.id, runner))

    return job


async def _run_and_cleanup(job_id: int, runner: PipelineRunner):
    try:
        await runner.run()
    finally:
        _running_jobs.pop(job_id, None)


@router.get("", response_model=list[JobOut])
async def list_jobs(project_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(AnnotationJob)
        .where(AnnotationJob.project_id == project_id)
        .order_by(AnnotationJob.created_at.desc())
    )
    return result.scalars().all()


@router.get("/{job_id}", response_model=JobOut)
async def get_job(project_id: int, job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/{job_id}/cancel", response_model=JobOut)
async def cancel_job(project_id: int, job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    runner = _running_jobs.get(job_id)
    if runner:
        runner.cancel()

    job.status = JobStatus.CANCELLED
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/pause", response_model=JobOut)
async def pause_job(project_id: int, job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    runner = _running_jobs.get(job_id)
    if not runner:
        raise HTTPException(409, "Job is not currently running")

    runner.pause()
    job.status = JobStatus.PAUSED
    await db.commit()
    await db.refresh(job)
    return job


@router.post("/{job_id}/resume", response_model=JobOut)
async def resume_job(project_id: int, job_id: int, db: AsyncSession = Depends(get_db)):
    job = await db.get(AnnotationJob, job_id)
    if not job or job.project_id != project_id:
        raise HTTPException(404, "Job not found")

    runner = _running_jobs.get(job_id)
    if not runner:
        raise HTTPException(409, "Job is not currently running")

    runner.resume()
    job.status = JobStatus.RUNNING
    await db.commit()
    await db.refresh(job)
    return job

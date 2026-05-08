"""FastAPI application entry point."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update

from app.config import settings
from app.database import async_session, engine
from app.models.tables import AnnotationJob, Base, JobStatus, OptimizerRun
from app.api import (
    projects, codebooks, codebook_drafts, datasets, pipelines, jobs,
    results, calibration, ws,
    optimizers as optimizers_api, config as config_api,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Reap stale in-flight rows. The asyncio.Task registry is process-local
    # and doesn't survive restart, so anything still ``running``/``pending``
    # in the DB is orphaned — its task no longer exists. Mark cancelled so
    # the UI clears and users can delete the rows.
    async with async_session() as session:
        opt_res = await session.execute(
            update(OptimizerRun)
            .where(OptimizerRun.status.in_(["running", "pending"]))
            .values(status="cancelled", error="server restarted before completion")
        )
        job_res = await session.execute(
            update(AnnotationJob)
            .where(AnnotationJob.status.in_([JobStatus.RUNNING, JobStatus.PENDING, JobStatus.PAUSED]))
            .values(status=JobStatus.CANCELLED)
        )
        await session.commit()
        if opt_res.rowcount or job_res.rowcount:
            logger.info(
                f"Reaped stale rows on startup: optimizer_runs={opt_res.rowcount} "
                f"annotation_jobs={job_res.rowcount}"
            )
    yield
    await engine.dispose()


app = FastAPI(
    title="AnnotAgent",
    description="Codebook-driven LLM annotation framework",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
app.include_router(projects.router)
app.include_router(codebooks.router)
app.include_router(codebook_drafts.router)
app.include_router(datasets.router)
app.include_router(pipelines.router)
app.include_router(jobs.router)
app.include_router(results.router)
app.include_router(calibration.router)
app.include_router(optimizers_api.router)
app.include_router(optimizers_api.memory_router)
app.include_router(ws.router)
app.include_router(config_api.router)


@app.get("/api/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}

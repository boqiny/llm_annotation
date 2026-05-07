"""FastAPI application entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.database import engine
from app.models.tables import Base
from app.api import (
    projects, codebooks, codebook_drafts, datasets, pipelines, jobs,
    results, calibration, ws,
    optimizers as optimizers_api, config as config_api,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
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

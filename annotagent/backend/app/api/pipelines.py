"""Pipeline API routes — decompose, view, edit steps/prompts."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.tables import Pipeline, Codebook, DataItem, Dataset, Project
from app.schemas.schemas import PipelineOut, PipelineUpdate
from app.engine.codebook_parser import parse_codebook
from app.agents.decomposition import decompose_codebook

router = APIRouter(prefix="/api/projects/{project_id}/pipelines", tags=["pipelines"])


def _rough_tokens(text: str) -> int:
    # Annotation prompts and short inputs are mostly plain English. The actual
    # runner has tracked closer to ~5 chars/token than the old conservative 4.
    return max(1, round(len(text or "") / 5))


def _annotation_user_message(content: str, context: str) -> str:
    user_msg = f"Sentence: {content}"
    if context:
        user_msg = f"Context: {context}\n\n{user_msg}"
    return user_msg


@router.post("/decompose", response_model=PipelineOut, status_code=201)
async def decompose(
    project_id: int,
    few_shot: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """Generate the active pipeline: one prompt per codebook dimension.

    ``few_shot=true`` appends each label's captured examples as a few-shot block in
    the generated prompts (opt-in).
    """
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
    steps = await decompose_codebook(codebook=parsed, few_shot=few_shot)

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


@router.get("/{pipeline_id}/estimate")
async def estimate_annotation_run(
    project_id: int,
    pipeline_id: int,
    dataset_id: int,
    db: AsyncSession = Depends(get_db),
):
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(404, "Project not found")

    pipeline = await db.get(Pipeline, pipeline_id)
    if not pipeline or pipeline.project_id != project_id:
        raise HTTPException(404, "Pipeline not found")

    dataset = await db.get(Dataset, dataset_id)
    if not dataset or dataset.project_id != project_id:
        raise HTTPException(404, "Dataset not found")

    sample = (await db.execute(
        select(DataItem)
        .where(DataItem.dataset_id == dataset_id)
        .order_by(DataItem.index)
        .limit(100)
    )).scalars().all()

    steps = pipeline.steps or []
    prompt_tokens_per_item = sum(_rough_tokens(str(step.get("prompt", ""))) for step in steps)
    avg_user_tokens_per_step = 0
    if sample and steps:
        sampled_tokens = [
            _rough_tokens(_annotation_user_message(item.content or "", item.context or ""))
            for item in sample
        ]
        avg_user_tokens_per_step = round(sum(sampled_tokens) / len(sampled_tokens))

    n_items = dataset.total_items or 0
    n_calls = n_items * len(steps)
    estimated_input_tokens = n_items * prompt_tokens_per_item + n_calls * avg_user_tokens_per_step
    # Annotation completions are label-only and parseable via "Answer: <label>".
    # Actual runs are usually far below the 512 max_tokens cap.
    estimated_output_tokens = n_calls * 24
    estimated_total_tokens = estimated_input_tokens + estimated_output_tokens

    return {
        "dataset_id": dataset.id,
        "dataset_name": dataset.name,
        "model": project.llm_model,
        "provider": project.llm_provider,
        "n_items": n_items,
        "n_prompts": len(steps),
        "n_calls": n_calls,
        "prompt_tokens_per_item": prompt_tokens_per_item,
        "avg_user_tokens_per_step": avg_user_tokens_per_step,
        "estimated_input_tokens": estimated_input_tokens,
        "estimated_output_tokens": estimated_output_tokens,
        "estimated_total_tokens": estimated_total_tokens,
        "sample_size": len(sample),
        "assumptions": {
            "tokenizer": "rough character-based estimate",
            "output_tokens_per_call": 24,
        },
    }


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

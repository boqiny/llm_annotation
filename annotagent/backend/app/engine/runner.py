"""Pipeline runner -- orchestrates annotation jobs."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Callable, Awaitable

from sqlalchemy import select

from app.models.tables import (
    AnnotationJob, AnnotationResult, DataItem, JobStatus,
    Pipeline, Dataset, Codebook, Dimension,
)
from app.models.tables import Label as LabelModel
from app.agents.annotation import annotate_item

logger = logging.getLogger(__name__)


class PipelineRunner:
    """Runs an annotation job: iterates dataset, calls annotation agent per item."""

    def __init__(
        self,
        job_id: int,
        session_factory: Any,
        provider: str = "openai",
        model: str = "gpt-5.4-mini",
        api_key: str = "",
        max_concurrency: int = 10,
        ws_callback: Optional[Callable[[dict], Awaitable[None]]] = None,
    ):
        self.job_id = job_id
        self.session_factory = session_factory
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.max_concurrency = max_concurrency
        self.ws_callback = ws_callback
        self._cancel = False
        self._pause = asyncio.Event()
        self._pause.set()  # not paused initially

    def cancel(self):
        self._cancel = True
        self._pause.set()  # release anyone waiting so they can observe cancel

    def pause(self):
        self._pause.clear()

    def resume(self):
        self._pause.set()

    async def run(self) -> None:
        """Execute the full annotation job."""
        async with self.session_factory() as session:
            job = await session.get(AnnotationJob, self.job_id)
            if not job:
                logger.error(f"Job {self.job_id} not found")
                return

            job.status = JobStatus.RUNNING
            await session.commit()

            pipeline = await session.get(Pipeline, job.pipeline_id)
            dataset = await session.get(Dataset, job.dataset_id)
            if not pipeline or not dataset:
                job.status = JobStatus.FAILED
                await session.commit()
                return

            steps = pipeline.steps

            result = await session.execute(
                select(DataItem).where(DataItem.dataset_id == dataset.id).order_by(DataItem.index)
            )
            items = result.scalars().all()
            job.total_items = len(items)
            await session.commit()

            # Build codebook_dims from project codebook
            codebook_dims: dict[str, list[str]] = {}
            codebook_result = await session.execute(
                select(Codebook).where(Codebook.project_id == job.project_id)
                .order_by(Codebook.id.desc()).limit(1)
            )
            codebook = codebook_result.scalars().first()
            if codebook:
                dim_result = await session.execute(
                    select(Dimension).where(Dimension.codebook_id == codebook.id)
                )
                for dim in dim_result.scalars().all():
                    label_result = await session.execute(
                        select(LabelModel).where(LabelModel.dimension_id == dim.id)
                    )
                    codebook_dims[dim.name] = [l.name for l in label_result.scalars().all()]

        # Run annotations with concurrency
        semaphore = asyncio.Semaphore(self.max_concurrency)
        completed = 0
        failed = 0
        total_tokens = 0

        async def process_item(item: DataItem) -> None:
            nonlocal completed, failed, total_tokens
            # Wait here if paused (released on resume/cancel)
            await self._pause.wait()
            if self._cancel:
                return

            async with semaphore:
                try:
                    ann_result = await annotate_item(
                        content=item.content,
                        context=item.context or "",
                        item_index=item.index,
                        steps=steps,
                        codebook_dims=codebook_dims,
                        provider=self.provider,
                        model=self.model,
                        api_key=self.api_key,
                    )

                    async with self.session_factory() as session:
                        for step_idx, step in enumerate(steps):
                            for dim_name in step.get("dimensions", []):
                                db_result = AnnotationResult(
                                    job_id=self.job_id,
                                    data_item_id=item.id,
                                    step_order=step_idx,
                                    dimension_name=dim_name,
                                    predicted_label=ann_result.labels.get(dim_name, ""),
                                    reasoning=ann_result.reasoning.get(dim_name, ""),
                                    tokens_used=ann_result.tokens_used // max(len(steps), 1),
                                )
                                session.add(db_result)
                        await session.commit()

                    completed += 1
                    total_tokens += ann_result.tokens_used

                except Exception as e:
                    logger.error(f"Error annotating item {item.index}: {e}")
                    failed += 1

                if self.ws_callback:
                    await self.ws_callback({
                        "job_id": self.job_id,
                        "completed": completed,
                        "total": len(items),
                        "failed": failed,
                        "tokens": total_tokens,
                        "status": "paused" if not self._pause.is_set() else "running",
                    })

        tasks = [process_item(item) for item in items]
        await asyncio.gather(*tasks)

        async with self.session_factory() as session:
            job = await session.get(AnnotationJob, self.job_id)
            if job:
                job.completed_items = completed
                job.failed_items = failed
                job.total_tokens = total_tokens
                job.status = JobStatus.CANCELLED if self._cancel else (
                    JobStatus.COMPLETED if failed == 0 else JobStatus.FAILED
                )
                await session.commit()

        if self.ws_callback:
            await self.ws_callback({
                "job_id": self.job_id,
                "completed": completed,
                "total": len(items),
                "failed": failed,
                "tokens": total_tokens,
                "status": "completed" if not self._cancel else "cancelled",
            })

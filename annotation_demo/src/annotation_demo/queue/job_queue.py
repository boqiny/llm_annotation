"""
In-process async job queue.

This module provides a lightweight job queue for running annotation workflows
asynchronously during demo usage. It is intended for local/demo deployment, not
large-scale distributed production.

Responsibilities:
- Submit background jobs.
- Track job status, progress, result, and error.
- Limit concurrent workers.
- Provide a simple interface for frontend polling.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


ProgressCallback = Callable[[float], None]
CoroFactory = Callable[[ProgressCallback], Awaitable[dict[str, Any]]]


@dataclass
class JobState:
    """Lifecycle states for a submitted workflow job."""
    job_id: str
    project_id: str
    status: str = "queued"
    created_at: str = field(default_factory=utc_now)
    started_at: str | None = None
    finished_at: str | None = None
    progress: float = 0.0
    result: dict[str, Any] | None = None
    error: str | None = None


@dataclass
class Job:
    """In-memory representation of a submitted job.

    Stores job state, timestamps, result metadata, and error information for local
    inspection.
    """
    state: JobState
    coro_factory: CoroFactory


class InMemoryJobQueue:
    """Small async-compatible in-memory queue for demo workflow jobs.

    The queue is suitable for local development and frontend integration testing,
    but it does not provide persistence, distributed workers, retries, or recovery.
    """
    def __init__(self, max_workers: int = 2):
        self.queue: asyncio.Queue[Job] = asyncio.Queue()
        self.jobs: dict[str, JobState] = {}
        self.max_workers = max_workers
        self.workers: list[asyncio.Task] = []
        self.started = False

    async def start(self) -> None:
        if self.started:
            return
        self.started = True
        self.workers = [
            asyncio.create_task(self._worker_loop(i))
            for i in range(self.max_workers)
        ]

    async def submit(
        self,
        project_id: str,
        coro_factory: CoroFactory,
    ) -> JobState:
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        state = JobState(job_id=job_id, project_id=project_id)

        self.jobs[job_id] = state
        await self.queue.put(Job(state=state, coro_factory=coro_factory))

        return state

    def get_status(self, job_id: str) -> JobState:
        if job_id not in self.jobs:
            raise KeyError(f"Unknown job_id: {job_id}")
        return self.jobs[job_id]

    async def _worker_loop(self, worker_id: int) -> None:
        while True:
            job = await self.queue.get()
            state = job.state

            try:
                state.status = "running"
                state.started_at = utc_now()
                state.progress = 0.0

                def on_progress(p: float) -> None:
                    state.progress = p

                result = await job.coro_factory(on_progress)

                state.status = "succeeded"
                state.result = result
                state.progress = 1.0

            except Exception as exc:
                state.status = "failed"
                state.error = repr(exc)

            finally:
                state.finished_at = utc_now()
                self.queue.task_done()

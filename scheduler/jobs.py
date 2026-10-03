"""
scheduler/jobs.py

Технические фоновые задачи автономной системы.

Jobs:
    - выполняют конкретные технические операции;
    - фиксируют результат;
    - не принимают стратегических решений.

Director остаётся владельцем решений.
"""

from __future__ import annotations

import asyncio
import inspect
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Optional
from uuid import uuid4


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


class JobStatus(str, Enum):
    """Lifecycle state of a technical job."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobType(str, Enum):
    """Known technical job categories."""

    DIRECTOR_CYCLE = "director_cycle"
    RESEARCH = "research"
    ANALYTICS = "analytics"
    EVALUATION = "evaluation"
    PERSIST = "persist"
    CLEANUP = "cleanup"
    GENERIC = "generic"


@dataclass
class JobResult:
    """Technical result returned by a job."""

    success: bool
    output: Any = None

    error: Optional[str] = None

    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_seconds(self) -> Optional[float]:
        if not self.started_at or not self.finished_at:
            return None

        return (
            self.finished_at - self.started_at
        ).total_seconds()

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "output": self.output,
            "error": self.error,
            "started_at": (
                self.started_at.isoformat()
                if self.started_at
                else None
            ),
            "finished_at": (
                self.finished_at.isoformat()
                if self.finished_at
                else None
            ),
            "duration_seconds": self.duration_seconds,
            "metadata": dict(self.metadata),
        }


@dataclass
class Job:
    """A single executable technical job."""

    job_id: str
    project_id: str
    job_type: JobType
    name: str

    handler: Callable[..., Any]

    payload: dict[str, Any] = field(default_factory=dict)

    status: JobStatus = JobStatus.PENDING

    created_at: datetime = field(default_factory=utc_now)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    result: Optional[JobResult] = None

    attempts: int = 0
    max_attempts: int = 1

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.created_at = self._utc(self.created_at)

        if self.max_attempts < 1:
            self.max_attempts = 1

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)

        return value.astimezone(UTC)

    @property
    def can_retry(self) -> bool:
        return (
            self.status == JobStatus.FAILED
            and self.attempts < self.max_attempts
        )

    def cancel(self) -> None:
        if self.status in {
            JobStatus.PENDING,
            JobStatus.RUNNING,
        }:
            self.status = JobStatus.CANCELLED

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "project_id": self.project_id,
            "job_type": self.job_type.value,
            "name": self.name,
            "payload": dict(self.payload),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "started_at": (
                self.started_at.isoformat()
                if self.started_at
                else None
            ),
            "finished_at": (
                self.finished_at.isoformat()
                if self.finished_at
                else None
            ),
            "result": (
                self.result.to_dict()
                if self.result
                else None
            ),
            "attempts": self.attempts,
            "max_attempts": self.max_attempts,
            "metadata": dict(self.metadata),
        }


class JobRunner:
    """
    Technical background job runner.

    It provides execution infrastructure but has no strategic logic.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._jobs: dict[str, Job] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        project_id: str,
        handler: Callable[..., Any],
        name: str,
        job_type: JobType | str = JobType.GENERIC,
        payload: Optional[dict[str, Any]] = None,
        max_attempts: int = 1,
        metadata: Optional[dict[str, Any]] = None,
    ) -> Job:
        if isinstance(job_type, str):
            job_type = JobType(job_type)

        job = Job(
            job_id=str(uuid4()),
            project_id=project_id,
            job_type=job_type,
            name=name,
            handler=handler,
            payload=dict(payload or {}),
            max_attempts=max(1, int(max_attempts)),
            metadata=dict(metadata or {}),
        )

        self._jobs[job.job_id] = job

        return job

    def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def list(
        self,
        *,
        project_id: Optional[str] = None,
        status: Optional[JobStatus] = None,
    ) -> list[Job]:
        jobs = list(self._jobs.values())

        if project_id is not None:
            jobs = [
                job
                for job in jobs
                if job.project_id == project_id
            ]

        if status is not None:
            jobs = [
                job
                for job in jobs
                if job.status == status
            ]

        return sorted(
            jobs,
            key=lambda job: job.created_at,
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def run(
        self,
        job_id: str,
    ) -> JobResult:
        """
        Execute a job exactly once for the current attempt.

        The handler can be sync or async.
        """

        if not self.enabled:
            return JobResult(
                success=False,
                error="Job runner is disabled.",
            )

        job = self.get(job_id)

        if job is None:
            return JobResult(
                success=False,
                error=f"Unknown job: {job_id}",
            )

        if job.status == JobStatus.CANCELLED:
            return JobResult(
                success=False,
                error="Job was cancelled.",
            )

        if job.status == JobStatus.RUNNING:
            return JobResult(
                success=False,
                error="Job is already running.",
            )

        if job.status == JobStatus.SUCCEEDED:
            return job.result or JobResult(
                success=True,
                output=None,
            )

        job.status = JobStatus.RUNNING
        job.attempts += 1
        job.started_at = utc_now()

        try:
            output = job.handler(**job.payload)

            if inspect.isawaitable(output):
                output = await output

            job.finished_at = utc_now()
            job.status = JobStatus.SUCCEEDED

            result = JobResult(
                success=True,
                output=output,
                started_at=job.started_at,
                finished_at=job.finished_at,
                metadata={
                    "job_id": job.job_id,
                    "job_type": job.job_type.value,
                    "attempt": job.attempts,
                },
            )

            job.result = result
            return result

        except Exception as exc:
            job.finished_at = utc_now()
            job.status = JobStatus.FAILED

            result = JobResult(
                success=False,
                error=str(exc),
                started_at=job.started_at,
                finished_at=job.finished_at,
                metadata={
                    "job_id": job.job_id,
                    "job_type": job.job_type.value,
                    "attempt": job.attempts,
                    "traceback": traceback.format_exc(),
                },
            )

            job.result = result
            return result

    async def run_with_retry(
        self,
        job_id: str,
    ) -> JobResult:
        """
        Execute a job until success or attempts are exhausted.

        Retry is technical. It does not decide whether Director
        should change strategy.
        """

        job = self.get(job_id)

        if job is None:
            return JobResult(
                success=False,
                error=f"Unknown job: {job_id}",
            )

        while True:
            result = await self.run(job_id)

            if result.success:
                return result

            if not job.can_retry:
                return result

            job.status = JobStatus.PENDING

    # ------------------------------------------------------------------
    # Convenience jobs
    # ------------------------------------------------------------------

    def create_director_cycle_job(
        self,
        *,
        project_id: str,
        handler: Callable[..., Any],
        payload: Optional[dict[str, Any]] = None,
        max_attempts: int = 1,
    ) -> Job:
        """
        Register technical execution of one Director cycle.

        The handler itself is supplied by the Director integration layer.
        """

        return self.create(
            project_id=project_id,
            handler=handler,
            name="Director cycle",
            job_type=JobType.DIRECTOR_CYCLE,
            payload=payload,
            max_attempts=max_attempts,
        )

    def create_research_job(
        self,
        *,
        project_id: str,
        handler: Callable[..., Any],
        payload: Optional[dict[str, Any]] = None,
        max_attempts: int = 1,
    ) -> Job:
        return self.create(
            project_id=project_id,
            handler=handler,
            name="Research",
            job_type=JobType.RESEARCH,
            payload=payload,
            max_attempts=max_attempts,
        )

    def create_evaluation_job(
        self,
        *,
        project_id: str,
        handler: Callable[..., Any],
        payload: Optional[dict[str, Any]] = None,
        max_attempts: int = 1,
    ) -> Job:
        return self.create(
            project_id=project_id,
            handler=handler,
            name="Evaluation",
            job_type=JobType.EVALUATION,
            payload=payload,
            max_attempts=max_attempts,
        )

    # ------------------------------------------------------------------
    # Queue / cancellation
    # ------------------------------------------------------------------

    def cancel(self, job_id: str) -> Optional[Job]:
        job = self.get(job_id)

        if job is None:
            return None

        job.cancel()
        return job

    def pending(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> list[Job]:
        return self.list(
            project_id=project_id,
            status=JobStatus.PENDING,
        )

    def snapshot(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        jobs = self.list(project_id=project_id)

        return {
            "enabled": self.enabled,
            "total": len(jobs),
            "pending": sum(
                job.status == JobStatus.PENDING
                for job in jobs
            ),
            "running": sum(
                job.status == JobStatus.RUNNING
                for job in jobs
            ),
            "succeeded": sum(
                job.status == JobStatus.SUCCEEDED
                for job in jobs
            ),
            "failed": sum(
                job.status == JobStatus.FAILED
                for job in jobs
            ),
            "cancelled": sum(
                job.status == JobStatus.CANCELLED
                for job in jobs
            ),
        }

    def clear_finished(self) -> int:
        """Remove completed technical jobs."""

        removable = [
            job_id
            for job_id, job in self._jobs.items()
            if job.status
            in {
                JobStatus.SUCCEEDED,
                JobStatus.CANCELLED,
            }
        ]

        for job_id in removable:
            del self._jobs[job_id]

        return len(removable)


def create_job_runner(
    *,
    enabled: bool = True,
) -> JobRunner:
    return JobRunner(enabled=enabled)

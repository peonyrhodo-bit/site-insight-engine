"""
scheduler/scheduler.py

Планировщик автономной работы Director.

Ответственность:
    - хранить запланированные wake-up события;
    - вычислять ближайшее событие;
    - создавать/отменять расписания;
    - определять, пора ли будить Director.

Scheduler НЕ:
    - принимает стратегические решения;
    - анализирует YouTube;
    - формирует рекомендации;
    - заменяет Director;
    - хранит долгосрочную память проекта.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Iterable, Optional
from uuid import uuid4


UTC = timezone.utc


def utc_now() -> datetime:
    """Return timezone-aware current UTC time."""
    return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Normalize datetime to timezone-aware UTC."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ScheduleType(str, Enum):
    """Reason/type of scheduled wake-up."""

    ONE_TIME = "one_time"
    INTERVAL = "interval"


class ScheduleStatus(str, Enum):
    """Lifecycle status of a schedule."""

    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class ScheduledWake:
    """
    A single scheduled wake-up instruction.

    This object describes WHEN Director should be awakened.
    It does not describe WHAT strategic decision Director should make.
    """

    schedule_id: str
    project_id: str
    reason: str
    run_at: datetime

    schedule_type: ScheduleType = ScheduleType.ONE_TIME
    interval_seconds: Optional[int] = None

    status: ScheduleStatus = ScheduleStatus.ACTIVE

    created_at: datetime = field(default_factory=utc_now)
    last_triggered_at: Optional[datetime] = None
    trigger_count: int = 0

    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.run_at = ensure_utc(self.run_at)
        self.created_at = ensure_utc(self.created_at)

        if self.last_triggered_at is not None:
            self.last_triggered_at = ensure_utc(self.last_triggered_at)

        if self.interval_seconds is not None:
            self.interval_seconds = max(1, int(self.interval_seconds))

    @property
    def is_active(self) -> bool:
        return self.status == ScheduleStatus.ACTIVE

    @property
    def is_due(self) -> bool:
        return self.is_active and utc_now() >= self.run_at

    def trigger(self, now: Optional[datetime] = None) -> None:
        """
        Mark this schedule as triggered.

        One-time schedules become completed.
        Interval schedules move to their next occurrence.
        """

        now = ensure_utc(now or utc_now())

        self.last_triggered_at = now
        self.trigger_count += 1

        if self.schedule_type == ScheduleType.INTERVAL:
            if not self.interval_seconds:
                self.status = ScheduleStatus.COMPLETED
                return

            self.run_at = now + timedelta(
                seconds=self.interval_seconds
            )
            return

        self.status = ScheduleStatus.COMPLETED

    def pause(self) -> None:
        if self.status == ScheduleStatus.ACTIVE:
            self.status = ScheduleStatus.PAUSED

    def resume(self) -> None:
        if self.status == ScheduleStatus.PAUSED:
            self.status = ScheduleStatus.ACTIVE

    def cancel(self) -> None:
        self.status = ScheduleStatus.CANCELLED

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)

        data["schedule_type"] = self.schedule_type.value
        data["status"] = self.status.value

        data["run_at"] = self.run_at.isoformat()
        data["created_at"] = self.created_at.isoformat()

        if self.last_triggered_at is not None:
            data["last_triggered_at"] = self.last_triggered_at.isoformat()

        return data


class Scheduler:
    """
    In-memory scheduler for Director wake-up events.

    Persistence can later be delegated to Memory/Supabase.
    The scheduler itself intentionally remains a lightweight
    execution/planning layer.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        default_project_id: Optional[str] = None,
    ) -> None:
        self.enabled = enabled
        self.default_project_id = default_project_id

        self._schedules: dict[str, ScheduledWake] = {}

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def schedule_once(
        self,
        *,
        run_at: datetime,
        reason: str,
        project_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ScheduledWake:
        """Schedule a single future wake-up."""

        schedule = ScheduledWake(
            schedule_id=str(uuid4()),
            project_id=project_id or self._require_project_id(),
            reason=reason,
            run_at=ensure_utc(run_at),
            schedule_type=ScheduleType.ONE_TIME,
            metadata=dict(metadata or {}),
        )

        self._schedules[schedule.schedule_id] = schedule

        return schedule

    def schedule_after(
        self,
        *,
        delay_seconds: int,
        reason: str,
        project_id: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ScheduledWake:
        """Schedule a wake-up after a delay."""

        delay_seconds = max(0, int(delay_seconds))

        return self.schedule_once(
            run_at=utc_now() + timedelta(seconds=delay_seconds),
            reason=reason,
            project_id=project_id,
            metadata=metadata,
        )

    def schedule_interval(
        self,
        *,
        interval_seconds: int,
        reason: str,
        project_id: Optional[str] = None,
        first_run_at: Optional[datetime] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> ScheduledWake:
        """
        Schedule recurring wake-ups.

        The scheduler only controls timing. Director decides what
        to do after waking up.
        """

        interval_seconds = max(1, int(interval_seconds))

        run_at = ensure_utc(
            first_run_at
            or (utc_now() + timedelta(seconds=interval_seconds))
        )

        schedule = ScheduledWake(
            schedule_id=str(uuid4()),
            project_id=project_id or self._require_project_id(),
            reason=reason,
            run_at=run_at,
            schedule_type=ScheduleType.INTERVAL,
            interval_seconds=interval_seconds,
            metadata=dict(metadata or {}),
        )

        self._schedules[schedule.schedule_id] = schedule

        return schedule

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def pause(self, schedule_id: str) -> Optional[ScheduledWake]:
        schedule = self.get(schedule_id)

        if schedule is None:
            return None

        schedule.pause()
        return schedule

    def resume(self, schedule_id: str) -> Optional[ScheduledWake]:
        schedule = self.get(schedule_id)

        if schedule is None:
            return None

        schedule.resume()
        return schedule

    def cancel(self, schedule_id: str) -> Optional[ScheduledWake]:
        schedule = self.get(schedule_id)

        if schedule is None:
            return None

        schedule.cancel()
        return schedule

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def get(self, schedule_id: str) -> Optional[ScheduledWake]:
        return self._schedules.get(schedule_id)

    def list(
        self,
        *,
        project_id: Optional[str] = None,
        include_completed: bool = False,
    ) -> list[ScheduledWake]:
        schedules = list(self._schedules.values())

        if project_id is not None:
            schedules = [
                item
                for item in schedules
                if item.project_id == project_id
            ]

        if not include_completed:
            schedules = [
                item
                for item in schedules
                if item.status
                not in {
                    ScheduleStatus.COMPLETED,
                    ScheduleStatus.CANCELLED,
                }
            ]

        return sorted(
            schedules,
            key=lambda item: item.run_at,
        )

    def due(
        self,
        *,
        project_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> list[ScheduledWake]:
        """
        Return schedules that are ready to trigger.

        Nothing is automatically executed here.
        """

        if not self.enabled:
            return []

        current_time = ensure_utc(now or utc_now())

        candidates = self.list(project_id=project_id)

        return [
            item
            for item in candidates
            if item.is_active and current_time >= item.run_at
        ]

    def next_wake(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> Optional[ScheduledWake]:
        """Return the next active wake-up."""

        schedules = self.list(project_id=project_id)

        for schedule in schedules:
            if schedule.status == ScheduleStatus.ACTIVE:
                return schedule

        return None

    # ------------------------------------------------------------------
    # Triggering
    # ------------------------------------------------------------------

    def trigger_due(
        self,
        *,
        project_id: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> list[ScheduledWake]:
        """
        Mark all due schedules as triggered and return them.

        Actual Director execution belongs to wakeup.py / Director.
        """

        if not self.enabled:
            return []

        current_time = ensure_utc(now or utc_now())

        due_items = self.due(
            project_id=project_id,
            now=current_time,
        )

        for schedule in due_items:
            schedule.trigger(current_time)

        return due_items

    # ------------------------------------------------------------------
    # Control
    # ------------------------------------------------------------------

    def enable(self) -> None:
        self.enabled = True

    def disable(self) -> None:
        self.enabled = False

    def clear_completed(self) -> int:
        """Remove completed/cancelled schedules from memory."""

        removable = [
            schedule_id
            for schedule_id, schedule in self._schedules.items()
            if schedule.status
            in {
                ScheduleStatus.COMPLETED,
                ScheduleStatus.CANCELLED,
            }
        ]

        for schedule_id in removable:
            del self._schedules[schedule_id]

        return len(removable)

    def snapshot(self) -> dict[str, Any]:
        """Return scheduler state for diagnostics/dashboard."""

        schedules = self.list(include_completed=True)

        return {
            "enabled": self.enabled,
            "default_project_id": self.default_project_id,
            "total": len(schedules),
            "active": sum(
                item.status == ScheduleStatus.ACTIVE
                for item in schedules
            ),
            "paused": sum(
                item.status == ScheduleStatus.PAUSED
                for item in schedules
            ),
            "completed": sum(
                item.status == ScheduleStatus.COMPLETED
                for item in schedules
            ),
            "cancelled": sum(
                item.status == ScheduleStatus.CANCELLED
                for item in schedules
            ),
            "next_wake": (
                self.next_wake().to_dict()
                if self.next_wake()
                else None
            ),
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _require_project_id(self) -> str:
        if not self.default_project_id:
            raise ValueError(
                "project_id is required when Scheduler has no "
                "default_project_id"
            )

        return self.default_project_id


def create_scheduler(
    *,
    enabled: bool = True,
    project_id: Optional[str] = None,
) -> Scheduler:
    """Factory used by the future server integration."""

    return Scheduler(
        enabled=enabled,
        default_project_id=project_id,
    )

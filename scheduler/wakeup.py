"""
scheduler/wakeup.py

Механизм пробуждения Director.

Ответственность:
    - сформировать wake-up сигнал;
    - классифицировать причину пробуждения;
    - передать сигнал вызывающей системе;
    - не принимать стратегических решений.

Wakeup НЕ является Director.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Iterable, Optional
from uuid import uuid4

from .scheduler import ScheduledWake, Scheduler


UTC = timezone.utc


def utc_now() -> datetime:
    return datetime.now(UTC)


class WakeupReason(str, Enum):
    """Standard reasons why Director should wake up."""

    SCHEDULED = "scheduled"
    NEW_DATA = "new_data"
    RESEARCH_DUE = "research_due"
    RESULT_AVAILABLE = "result_available"
    EVALUATION_DUE = "evaluation_due"
    USER_MESSAGE = "user_message"
    MANUAL = "manual"
    RETRY = "retry"
    SYSTEM = "system"


class WakeupPriority(str, Enum):
    """Priority of a wake-up signal."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class WakeupSignal:
    """
    Immutable-ish message saying that Director should wake up.

    It contains context for the wake-up, not a strategic command.
    """

    wakeup_id: str
    project_id: str
    reason: WakeupReason

    created_at: datetime = field(default_factory=utc_now)

    priority: WakeupPriority = WakeupPriority.NORMAL

    schedule_id: Optional[str] = None

    payload: dict[str, Any] = field(default_factory=dict)

    source: str = "scheduler"

    consumed: bool = False
    consumed_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        if self.created_at.tzinfo is None:
            self.created_at = self.created_at.replace(tzinfo=UTC)
        else:
            self.created_at = self.created_at.astimezone(UTC)

        if self.consumed_at is not None:
            if self.consumed_at.tzinfo is None:
                self.consumed_at = self.consumed_at.replace(tzinfo=UTC)
            else:
                self.consumed_at = self.consumed_at.astimezone(UTC)

    def consume(self) -> None:
        self.consumed = True
        self.consumed_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "wakeup_id": self.wakeup_id,
            "project_id": self.project_id,
            "reason": self.reason.value,
            "created_at": self.created_at.isoformat(),
            "priority": self.priority.value,
            "schedule_id": self.schedule_id,
            "payload": dict(self.payload),
            "source": self.source,
            "consumed": self.consumed,
            "consumed_at": (
                self.consumed_at.isoformat()
                if self.consumed_at
                else None
            ),
        }


class WakeupManager:
    """
    Creates, queues and consumes Director wake-up signals.

    The manager is intentionally independent from Director internals.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
    ) -> None:
        self.enabled = enabled
        self._queue: list[WakeupSignal] = []

    # ------------------------------------------------------------------
    # Signal creation
    # ------------------------------------------------------------------

    def create(
        self,
        *,
        project_id: str,
        reason: WakeupReason | str,
        priority: WakeupPriority | str = WakeupPriority.NORMAL,
        payload: Optional[dict[str, Any]] = None,
        schedule_id: Optional[str] = None,
        source: str = "scheduler",
    ) -> WakeupSignal:
        """Create and queue a wake-up signal."""

        if isinstance(reason, str):
            reason = WakeupReason(reason)

        if isinstance(priority, str):
            priority = WakeupPriority(priority)

        signal = WakeupSignal(
            wakeup_id=str(uuid4()),
            project_id=project_id,
            reason=reason,
            priority=priority,
            schedule_id=schedule_id,
            payload=dict(payload or {}),
            source=source,
        )

        if self.enabled:
            self._queue.append(signal)

        return signal

    def from_schedule(
        self,
        schedule: ScheduledWake,
    ) -> WakeupSignal:
        """
        Convert a scheduler event into a Director wake-up signal.
        """

        return self.create(
            project_id=schedule.project_id,
            reason=self._reason_from_schedule(schedule.reason),
            schedule_id=schedule.schedule_id,
            payload={
                "scheduled_reason": schedule.reason,
                "schedule_metadata": dict(schedule.metadata),
                "trigger_count": schedule.trigger_count,
            },
            source="scheduler",
        )

    # ------------------------------------------------------------------
    # Queue
    # ------------------------------------------------------------------

    def pending(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> list[WakeupSignal]:
        signals = [
            signal
            for signal in self._queue
            if not signal.consumed
        ]

        if project_id is not None:
            signals = [
                signal
                for signal in signals
                if signal.project_id == project_id
            ]

        return sorted(
            signals,
            key=self._priority_sort_key,
            reverse=True,
        )

    def next(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> Optional[WakeupSignal]:
        signals = self.pending(project_id=project_id)

        return signals[0] if signals else None

    def consume(
        self,
        wakeup_id: str,
    ) -> Optional[WakeupSignal]:
        for signal in self._queue:
            if signal.wakeup_id == wakeup_id:
                if signal.consumed:
                    return signal

                signal.consume()
                return signal

        return None

    def consume_next(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> Optional[WakeupSignal]:
        signal = self.next(project_id=project_id)

        if signal is None:
            return None

        signal.consume()
        return signal

    def clear_consumed(self) -> int:
        before = len(self._queue)

        self._queue = [
            signal
            for signal in self._queue
            if not signal.consumed
        ]

        return before - len(self._queue)

    # ------------------------------------------------------------------
    # Scheduler bridge
    # ------------------------------------------------------------------

    def collect_due(
        self,
        scheduler: Scheduler,
        *,
        project_id: Optional[str] = None,
    ) -> list[WakeupSignal]:
        """
        Take due schedules and convert them into wake-up signals.

        Director is not executed here.
        """

        if not self.enabled:
            return []

        schedules = scheduler.trigger_due(
            project_id=project_id,
        )

        return [
            self.from_schedule(schedule)
            for schedule in schedules
        ]

    # ------------------------------------------------------------------
    # Event helpers
    # ------------------------------------------------------------------

    def notify_new_data(
        self,
        *,
        project_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> WakeupSignal:
        return self.create(
            project_id=project_id,
            reason=WakeupReason.NEW_DATA,
            priority=WakeupPriority.NORMAL,
            payload=payload,
            source="data",
        )

    def notify_research_due(
        self,
        *,
        project_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> WakeupSignal:
        return self.create(
            project_id=project_id,
            reason=WakeupReason.RESEARCH_DUE,
            priority=WakeupPriority.NORMAL,
            payload=payload,
            source="research",
        )

    def notify_result_available(
        self,
        *,
        project_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> WakeupSignal:
        return self.create(
            project_id=project_id,
            reason=WakeupReason.RESULT_AVAILABLE,
            priority=WakeupPriority.HIGH,
            payload=payload,
            source="result",
        )

    def notify_evaluation_due(
        self,
        *,
        project_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> WakeupSignal:
        return self.create(
            project_id=project_id,
            reason=WakeupReason.EVALUATION_DUE,
            priority=WakeupPriority.HIGH,
            payload=payload,
            source="evaluation",
        )

    def notify_user(
        self,
        *,
        project_id: str,
        message: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> WakeupSignal:
        data = dict(payload or {})
        data["message"] = message

        return self.create(
            project_id=project_id,
            reason=WakeupReason.USER_MESSAGE,
            priority=WakeupPriority.HIGH,
            payload=data,
            source="user",
        )

    def notify_manual(
        self,
        *,
        project_id: str,
        payload: Optional[dict[str, Any]] = None,
    ) -> WakeupSignal:
        return self.create(
            project_id=project_id,
            reason=WakeupReason.MANUAL,
            priority=WakeupPriority.NORMAL,
            payload=payload,
            source="manual",
        )

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def snapshot(
        self,
        *,
        project_id: Optional[str] = None,
    ) -> dict[str, Any]:
        pending = self.pending(project_id=project_id)

        return {
            "enabled": self.enabled,
            "pending": len(pending),
            "signals": [
                signal.to_dict()
                for signal in pending
            ],
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _priority_sort_key(
        signal: WakeupSignal,
    ) -> tuple[int, float]:
        priority = {
            WakeupPriority.LOW: 1,
            WakeupPriority.NORMAL: 2,
            WakeupPriority.HIGH: 3,
            WakeupPriority.CRITICAL: 4,
        }[signal.priority]

        return (
            priority,
            -signal.created_at.timestamp(),
        )

    @staticmethod
    def _reason_from_schedule(
        reason: str,
    ) -> WakeupReason:
        """
        Map arbitrary scheduler reason into a known wake-up reason.

        Unknown reasons intentionally become SCHEDULED rather than
        inventing strategic semantics.
        """

        normalized = reason.strip().lower()

        mapping = {
            "scheduled": WakeupReason.SCHEDULED,
            "research_due": WakeupReason.RESEARCH_DUE,
            "result_available": WakeupReason.RESULT_AVAILABLE,
            "evaluation_due": WakeupReason.EVALUATION_DUE,
            "new_data": WakeupReason.NEW_DATA,
            "retry": WakeupReason.RETRY,
            "manual": WakeupReason.MANUAL,
        }

        return mapping.get(
            normalized,
            WakeupReason.SCHEDULED,
        )


def create_wakeup_manager(
    *,
    enabled: bool = True,
) -> WakeupManager:
    return WakeupManager(enabled=enabled)

"""
Director wakeup boundary.

Scheduler decides WHEN the system should wake.
Director decides WHAT should be done after wakeup.

This module intentionally does not contain strategic logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


@dataclass
class WakeupRequest:
    reason: str = "scheduled"
    requested_at: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "reason": self.reason,
            "requested_at": self.requested_at,
            "metadata": self.metadata or {},
        }


class DirectorWakeup:
    """
    Small boundary between scheduler and Director autonomy.

    External cron/job infrastructure can call wake().
    """

    def __init__(
        self,
        *,
        autonomy: Any | None = None,
    ) -> None:
        self.autonomy = autonomy

    def create_request(
        self,
        *,
        reason: str = "scheduled",
        metadata: dict[str, Any] | None = None,
    ) -> WakeupRequest:
        return WakeupRequest(
            reason=reason,
            requested_at=datetime.now(
                timezone.utc
            ).isoformat(),
            metadata=dict(metadata or {}),
        )

    def wake(
        self,
        *,
        reason: str = "scheduled",
        metadata: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        run_id: int | None = None,
        runner: Callable[..., Any] | None = None,
    ) -> Any:
        """
        Wake the Director system.

        The wakeup layer only forwards the event.
        """

        request = self.create_request(
            reason=reason,
            metadata=metadata,
        )

        if runner is not None:
            return runner(
                wakeup=request,
                context=context or {},
                run_id=run_id,
            )

        if self.autonomy is None:
            return {
                "status": "no_autonomy",
                "wakeup": request.to_dict(),
            }

        return self.autonomy.run(
            run_id=run_id,
            context={
                **(context or {}),
                "wakeup": request.to_dict(),
            },
        )

"""Fail-closed quota authority used when the durable ledger is unavailable."""

from __future__ import annotations

from typing import Any


class UnavailableYouTubeQuotaManager:
    """Keep cached-data analysis available without permitting unmetered API calls."""

    def __init__(self, *, reason: str) -> None:
        self.reason = reason

    def _raise_unavailable(self) -> None:
        raise RuntimeError(
            "youtube_quota_authority_unavailable: outbound YouTube API calls are blocked; "
            + self.reason
        )

    def preflight_call(
        self,
        *,
        bucket: str,
        operation: str,
        method: str,
        units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._raise_unavailable()

    def authorize_call(
        self,
        *,
        bucket: str,
        operation: str,
        method: str,
        units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._raise_unavailable()

    def finish_call(
        self,
        event_id: int,
        *,
        status: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self._raise_unavailable()

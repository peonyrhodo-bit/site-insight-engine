"""
Dashboard data preparation.

The dashboard is a presentation layer.

It may read Director state, memory, research and recommendations,
but it must not make strategic decisions.
"""

from __future__ import annotations

from typing import Any


class Dashboard:
    """
    Prepares a read-only snapshot for the web UI.
    """

    def __init__(
        self,
        *,
        memory: Any | None = None,
        director: Any | None = None,
        research: Any | None = None,
        recommendations: Any | None = None,
    ) -> None:
        self.memory = memory
        self.director = director
        self.research = research
        self.recommendations = recommendations

    def get_snapshot(self) -> dict[str, Any]:
        """
        Build a dashboard snapshot without changing system state.
        """

        snapshot: dict[str, Any] = {
            "director": {},
            "research": {},
            "recommendations": [],
            "recent_decisions": [],
            "recent_results": [],
            "recent_runs": [],
            "pending_questions": [],
        }

        self._load_memory(snapshot)
        self._load_director(snapshot)
        self._load_research(snapshot)
        self._load_recommendations(snapshot)

        return snapshot

    def _load_memory(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        if self.memory is None:
            return

        try:
            snapshot["recent_decisions"] = (
                self.memory.get_recent_decisions(
                    limit=10
                )
            )
        except Exception:
            snapshot["recent_decisions"] = []

        try:
            snapshot["recent_results"] = (
                self.memory.get_recent_results(
                    limit=10
                )
            )
        except Exception:
            snapshot["recent_results"] = []

        try:
            snapshot["recent_runs"] = (
                self.memory.get_recent_runs(
                    limit=10
                )
            )
        except Exception:
            snapshot["recent_runs"] = []

    def _load_director(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        if self.director is None:
            return

        try:
            if hasattr(
                self.director,
                "get_status",
            ):
                status = self.director.get_status()

                if isinstance(status, dict):
                    snapshot["director"] = status
        except Exception:
            pass

    def _load_research(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        if self.research is None:
            return

        try:
            if hasattr(
                self.research,
                "get_status",
            ):
                status = self.research.get_status()

                if isinstance(status, dict):
                    snapshot["research"] = status
        except Exception:
            pass

    def _load_recommendations(
        self,
        snapshot: dict[str, Any],
    ) -> None:
        if self.recommendations is None:
            return

        try:
            if hasattr(
                self.recommendations,
                "list",
            ):
                recommendations = (
                    self.recommendations.list()
                )

                if isinstance(
                    recommendations,
                    list,
                ):
                    snapshot["recommendations"] = (
                        recommendations
                    )

                return

            if hasattr(
                self.recommendations,
                "get_recent",
            ):
                recommendations = (
                    self.recommendations.get_recent(
                        limit=10
                    )
                )

                if isinstance(
                    recommendations,
                    list,
                ):
                    snapshot["recommendations"] = (
                        recommendations
                    )
        except Exception:
            pass

    def get_status(self) -> dict[str, Any]:
        """
        Alias for web routes that expect a status-style method.
        """

        return self.get_snapshot()

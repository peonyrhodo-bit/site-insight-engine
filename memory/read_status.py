"""Explicit read outcomes for Director memory context."""

from __future__ import annotations

from typing import Any


class MemoryTableReadError(RuntimeError):
    """A table read failed after zero or more rows had already been fetched."""

    def __init__(
        self,
        table_name: str,
        *,
        partial_rows: list[dict[str, Any]] | None = None,
        cause: Exception | None = None,
    ) -> None:
        self.table_name = table_name
        self.partial_rows = list(partial_rows or [])
        self.cause = cause
        super().__init__(f"Memory table {table_name!r} could not be read completely")


class MemoryReadError(RuntimeError):
    """A context read was unavailable, partial, or failed.

    The partial context and per-table errors remain available to diagnostics;
    callers must not silently treat this outcome as an empty memory.
    """

    def __init__(
        self,
        status: str,
        *,
        context: dict[str, Any] | None = None,
        errors: dict[str, str] | None = None,
    ) -> None:
        if status not in {"partial", "error", "unavailable"}:
            raise ValueError("status must be partial, error, or unavailable")
        self.status = status
        self.context = dict(context or {})
        self.errors = dict(errors or {})
        super().__init__(
            f"Memory context read {status}: "
            + (", ".join(self.errors) if self.errors else "no readable storage")
        )

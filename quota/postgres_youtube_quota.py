from __future__ import annotations

import json
import math
import os
from datetime import datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from quota.youtube_quota import YouTubeQuotaExceeded


QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")
_ADVISORY_LOCK_NAMESPACE = 741923
_ADVISORY_LOCK_KEY = 1


class YouTubeQuotaManager:
    """PostgreSQL-backed quota ledger stored in Supabase's private schema."""

    def __init__(
        self,
        db_url: str | None = None,
        search_daily_limit: int | None = None,
        other_daily_limit: int | None = None,
        base_reserve_ratio: float | None = None,
    ):
        self.db_url = (db_url or os.environ.get("YOUTUBE_QUOTA_DATABASE_URL", "")).strip()
        if not self.db_url:
            raise RuntimeError("YOUTUBE_QUOTA_DATABASE_URL is required")
        self.search_daily_limit = int(
            search_daily_limit if search_daily_limit is not None
            else os.environ.get("YOUTUBE_SEARCH_DAILY_LIMIT", "100")
        )
        self.other_daily_limit = int(
            other_daily_limit if other_daily_limit is not None
            else os.environ.get("YOUTUBE_OTHER_DAILY_QUOTA_UNITS", "10000")
        )
        self.base_reserve_ratio = float(
            base_reserve_ratio if base_reserve_ratio is not None
            else os.environ.get("YOUTUBE_OTHER_RESERVE_RATIO", "0.20")
        )
        self._check_schema()

    def _connect(self):
        return psycopg.connect(self.db_url, connect_timeout=10, row_factory=dict_row)

    def _check_schema(self) -> None:
        with self._connect() as conn:
            conn.execute(
                "SELECT 1 FROM private.youtube_quota_usage LIMIT 0"
            )
            conn.execute(
                "SELECT 1 FROM private.youtube_quota_events LIMIT 0"
            )

    @staticmethod
    def _period_start_utc(now: datetime | None = None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_now = current.astimezone(QUOTA_TIMEZONE)
        local_midnight = datetime.combine(local_now.date(), time.min, tzinfo=QUOTA_TIMEZONE)
        return local_midnight.astimezone(timezone.utc)

    def _usage_in_connection(self, conn, now: datetime | None = None) -> dict[str, int]:
        start = self._period_start_utc(now)
        row = conn.execute(
            """
            SELECT COALESCE(SUM(search_calls), 0)::bigint AS search_calls,
                   COALESCE(SUM(other_units), 0)::bigint AS other_units
            FROM private.youtube_quota_usage
            WHERE created_at >= %s
            """,
            (start,),
        ).fetchone()
        return {
            "search_calls": int(row["search_calls"] or 0),
            "other_units": int(row["other_units"] or 0),
        }

    def get_usage(self) -> dict[str, int]:
        with self._connect() as conn:
            return self._usage_in_connection(conn)

    def get_remaining(self) -> dict[str, int]:
        usage = self.get_usage()
        return {
            "search_remaining": max(self.search_daily_limit - usage["search_calls"], 0),
            "other_remaining": max(self.other_daily_limit - usage["other_units"], 0),
        }

    def get_status(self) -> dict[str, int]:
        usage = self.get_usage()
        return {
            "search_calls": usage["search_calls"],
            "search_limit": self.search_daily_limit,
            "search_remaining": max(self.search_daily_limit - usage["search_calls"], 0),
            "other_units": usage["other_units"],
            "other_limit": self.other_daily_limit,
            "other_remaining": max(self.other_daily_limit - usage["other_units"], 0),
        }

    def record_usage(
        self,
        operation: str,
        search_calls: int = 0,
        other_units: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        search_calls = max(0, int(search_calls or 0))
        other_units = max(0, int(other_units or 0))
        if not search_calls and not other_units:
            return
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO private.youtube_quota_usage
                    (operation, search_calls, other_units, metadata_json)
                VALUES (%s, %s, %s, %s)
                """,
                (operation, search_calls, other_units, Jsonb(metadata or {})),
            )

    def record_planned_call(
        self,
        *,
        bucket: str,
        operation: str,
        method: str,
        units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        if bucket not in {"search", "other"}:
            raise ValueError("bucket must be 'search' or 'other'")
        remaining = self.get_remaining()
        with self._connect() as conn:
            row = conn.execute(
                """
                INSERT INTO private.youtube_quota_events
                    (operation, method, bucket, units, status, remaining_json, metadata_json)
                VALUES (%s, %s, %s, %s, 'planned', %s, %s)
                RETURNING id
                """,
                (
                    operation, method, bucket, max(1, int(units)),
                    Jsonb(remaining), Jsonb(metadata or {}),
                ),
            ).fetchone()
            return int(row["id"])

    def preflight_call(
        self,
        *,
        bucket: str,
        operation: str,
        method: str,
        units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if bucket not in {"search", "other"}:
            raise ValueError("bucket must be 'search' or 'other'")
        units = max(1, int(units))
        event_id = self.record_planned_call(
            bucket=bucket, operation=operation, method=method,
            units=units, metadata=metadata,
        )
        remaining = self.get_remaining()
        key = "search_remaining" if bucket == "search" else "other_remaining"
        if remaining[key] < units:
            self.finish_planned_call(event_id, status="blocked", reason="budget_exhausted")
            raise YouTubeQuotaExceeded(
                bucket, {**remaining, "event_id": event_id, "reason": "budget_exhausted"}
            )
        return {"allowed": True, "event_id": event_id, **remaining, "preflight_only": True}

    def finish_planned_call(
        self, event_id: int, *, status: str, reason: str | None = None
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE private.youtube_quota_events
                SET status = %s, reason = %s, finished_at = now()
                WHERE id = %s AND status = 'planned'
                """,
                (status, reason, int(event_id)),
            )

    def authorize_call(
        self,
        *,
        bucket: str,
        operation: str,
        method: str,
        units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if bucket not in {"search", "other"}:
            raise ValueError("bucket must be 'search' or 'other'")
        units = max(1, int(units))
        denied: dict[str, Any] | None = None
        result: dict[str, Any] | None = None
        with self._connect() as conn:
            # Serialize quota decisions across processes and Render instances.
            with conn.transaction():
                conn.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s)",
                    (_ADVISORY_LOCK_NAMESPACE, _ADVISORY_LOCK_KEY),
                )
                usage = self._usage_in_connection(conn)
                search_remaining = max(self.search_daily_limit - usage["search_calls"], 0)
                other_remaining = max(self.other_daily_limit - usage["other_units"], 0)
                remaining = {
                    "search_remaining": search_remaining,
                    "other_remaining": other_remaining,
                    "search_limit": self.search_daily_limit,
                    "other_limit": self.other_daily_limit,
                }
                key = "search_remaining" if bucket == "search" else "other_remaining"
                now = datetime.now(timezone.utc)
                if remaining[key] < units:
                    row = conn.execute(
                        """
                        INSERT INTO private.youtube_quota_events
                            (created_at, operation, method, bucket, units, status, reason,
                             remaining_json, metadata_json)
                        VALUES (%s, %s, %s, %s, %s, 'blocked', 'budget_exhausted', %s, %s)
                        RETURNING id
                        """,
                        (
                            now, operation, method, bucket, units,
                            Jsonb(remaining), Jsonb(metadata or {}),
                        ),
                    ).fetchone()
                    denied = {
                        **remaining, "event_id": int(row["id"]),
                        "reason": "budget_exhausted",
                    }
                else:
                    search_charge = units if bucket == "search" else 0
                    other_charge = units if bucket == "other" else 0
                    conn.execute(
                        """
                        INSERT INTO private.youtube_quota_usage
                            (created_at, operation, search_calls, other_units, metadata_json)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            now, operation, search_charge, other_charge,
                            Jsonb({"method": method, **(metadata or {})}),
                        ),
                    )
                    updated = {
                        **remaining,
                        "search_remaining": max(search_remaining - search_charge, 0),
                        "other_remaining": max(other_remaining - other_charge, 0),
                    }
                    row = conn.execute(
                        """
                        INSERT INTO private.youtube_quota_events
                            (created_at, operation, method, bucket, units, status,
                             remaining_json, metadata_json)
                        VALUES (%s, %s, %s, %s, %s, 'attempted', %s, %s)
                        RETURNING id
                        """,
                        (
                            now, operation, method, bucket, units,
                            Jsonb(updated), Jsonb(metadata or {}),
                        ),
                    ).fetchone()
                    result = {"allowed": True, "event_id": int(row["id"]), **updated}
        if denied is not None:
            raise YouTubeQuotaExceeded(bucket, denied)
        assert result is not None
        return result

    def finish_call(
        self,
        event_id: int,
        *,
        status: str,
        reason: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if status not in {"succeeded", "error"}:
            raise ValueError("status must be 'succeeded' or 'error'")
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT metadata_json
                FROM private.youtube_quota_events
                WHERE id = %s
                """,
                (int(event_id),),
            ).fetchone()
            if row is None:
                raise ValueError(f"Quota event {event_id} does not exist")
            merged = dict(row["metadata_json"] or {})
            if metadata:
                merged.update(metadata)
            conn.execute(
                """
                UPDATE private.youtube_quota_events
                SET status = %s, reason = %s, finished_at = now(), metadata_json = %s
                WHERE id = %s
                """,
                (status, reason, Jsonb(merged), int(event_id)),
            )

    def get_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id, created_at, operation, method, bucket, units, status, reason,
                       remaining_json, metadata_json, finished_at
                FROM private.youtube_quota_events
                ORDER BY id DESC LIMIT %s
                """,
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def seconds_until_reset(self) -> int:
        now = datetime.now(timezone.utc)
        local_now = now.astimezone(QUOTA_TIMEZONE)
        next_midnight = datetime.combine(
            local_now.date() + timedelta(days=1), time.min, tzinfo=QUOTA_TIMEZONE
        )
        return max(
            int((next_midnight.astimezone(timezone.utc) - now).total_seconds()), 0
        )

    def get_reserve_ratio(self) -> float:
        hours_left = self.seconds_until_reset() / 3600
        base = max(min(self.base_reserve_ratio, 1.0), 0.0)
        if hours_left >= 12:
            return base
        if hours_left <= 1:
            return 0.0
        return base * ((hours_left - 1) / 11)

    def get_available_budget(self) -> dict[str, int | float | bool]:
        remaining = self.get_remaining()
        reserve_ratio = self.get_reserve_ratio()
        search_reserve = int(math.ceil(remaining["search_remaining"] * reserve_ratio))
        other_reserve = int(math.ceil(remaining["other_remaining"] * reserve_ratio))
        search_available = max(remaining["search_remaining"] - search_reserve, 0)
        other_available = max(remaining["other_remaining"] - other_reserve, 0)
        return {
            "search_available": search_available,
            "other_available": other_available,
            "reserve_ratio": reserve_ratio,
            "seconds_until_reset": self.seconds_until_reset(),
            "resource_available": search_available > 0 or other_available > 0,
        }

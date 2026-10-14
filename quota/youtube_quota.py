from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


QUOTA_TIMEZONE = ZoneInfo("America/Los_Angeles")


class YouTubeQuotaExceeded(RuntimeError):
    """Raised before an API request when its independent budget is exhausted."""

    def __init__(self, bucket: str, status: dict[str, Any]):
        self.bucket = bucket
        self.status = status
        super().__init__(
            f"YouTube {bucket} budget exhausted; "
            f"remaining={status.get(bucket + '_remaining', 0)}"
        )


class YouTubeQuotaManager:
    """Atomic, durable preflight and accounting for YouTube API method calls.

    The search bucket counts search.list attempts (the configured cap defaults
    to 100). The other bucket counts non-search API request units (videos.list
    and channels.list cost one unit per request under the current accounting
    policy). An attempt is charged before the network request because failed
    requests may still consume quota.
    """

    def __init__(
        self,
        db_path: str,
        search_daily_limit: int | None = None,
        other_daily_limit: int | None = None,
        base_reserve_ratio: float | None = None,
    ):
        self.db_path = db_path
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
        self._ensure_schema()

    def _get_db(self) -> sqlite3.Connection:
        if self.db_path != ":memory:":
            Path(self.db_path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout = 30000")
        return conn

    @staticmethod
    def _period_start_utc(now: datetime | None = None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        local_now = current.astimezone(QUOTA_TIMEZONE)
        local_midnight = datetime.combine(local_now.date(), time.min, tzinfo=QUOTA_TIMEZONE)
        return local_midnight.astimezone(timezone.utc)

    def _ensure_schema(self) -> None:
        conn = self._get_db()
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS youtube_quota_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    search_calls INTEGER NOT NULL DEFAULT 0,
                    other_units INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL DEFAULT '{}'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS youtube_quota_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    method TEXT NOT NULL,
                    bucket TEXT NOT NULL,
                    units INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    reason TEXT,
                    remaining_json TEXT NOT NULL DEFAULT '{}',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    finished_at TEXT
                )
            """)
        finally:
            conn.close()

    def _usage_in_connection(self, conn: sqlite3.Connection, now: datetime | None = None) -> dict[str, int]:
        start = self._period_start_utc(now).isoformat()
        row = conn.execute("""
            SELECT COALESCE(SUM(search_calls), 0) AS search_calls,
                   COALESCE(SUM(other_units), 0) AS other_units
            FROM youtube_quota_usage
            WHERE created_at >= ?
        """, (start,)).fetchone()
        return {"search_calls": int(row["search_calls"] or 0), "other_units": int(row["other_units"] or 0)}

    def get_usage(self) -> dict[str, int]:
        conn = self._get_db()
        try:
            return self._usage_in_connection(conn)
        finally:
            conn.close()

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
        conn = self._get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("""
                INSERT INTO youtube_quota_usage
                    (created_at, operation, search_calls, other_units, metadata_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                datetime.now(timezone.utc).isoformat(), operation, search_calls,
                other_units, json.dumps(metadata or {}, ensure_ascii=False, default=str),
            ))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def authorize_call(
        self,
        *,
        bucket: str,
        operation: str,
        method: str,
        units: int = 1,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Atomically check and charge a planned API attempt before networking."""
        if bucket not in {"search", "other"}:
            raise ValueError("bucket must be 'search' or 'other'")
        units = max(1, int(units))
        conn = self._get_db()
        try:
            conn.execute("BEGIN IMMEDIATE")
            usage = self._usage_in_connection(conn)
            search_remaining = max(self.search_daily_limit - usage["search_calls"], 0)
            other_remaining = max(self.other_daily_limit - usage["other_units"], 0)
            remaining = {
                "search_remaining": search_remaining,
                "other_remaining": other_remaining,
                "search_limit": self.search_daily_limit,
                "other_limit": self.other_daily_limit,
            }
            available = search_remaining if bucket == "search" else other_remaining
            if available < units:
                event_id = conn.execute("""
                    INSERT INTO youtube_quota_events
                        (created_at, operation, method, bucket, units, status, reason, remaining_json, metadata_json)
                    VALUES (?, ?, ?, ?, ?, 'blocked', ?, ?, ?)
                """, (
                    datetime.now(timezone.utc).isoformat(), operation, method, bucket, units,
                    "budget_exhausted", json.dumps(remaining), json.dumps(metadata or {}, default=str),
                )).lastrowid
                conn.commit()
                raise YouTubeQuotaExceeded(bucket, {**remaining, "event_id": event_id, "reason": "budget_exhausted"})
            now = datetime.now(timezone.utc).isoformat()
            conn.execute("""
                INSERT INTO youtube_quota_usage
                    (created_at, operation, search_calls, other_units, metadata_json)
                VALUES (?, ?, ?, ?, ?)
            """, (
                now, operation, units if bucket == "search" else 0,
                units if bucket == "other" else 0,
                json.dumps({"method": method, **(metadata or {})}, ensure_ascii=False, default=str),
            ))
            updated = {
                **remaining,
                "search_remaining": max(search_remaining - (units if bucket == "search" else 0), 0),
                "other_remaining": max(other_remaining - (units if bucket == "other" else 0), 0),
            }
            event_id = conn.execute("""
                INSERT INTO youtube_quota_events
                    (created_at, operation, method, bucket, units, status, remaining_json, metadata_json)
                VALUES (?, ?, ?, ?, ?, 'attempted', ?, ?)
            """, (
                now, operation, method, bucket, units, json.dumps(updated),
                json.dumps(metadata or {}, ensure_ascii=False, default=str),
            )).lastrowid
            conn.commit()
            return {"allowed": True, "event_id": event_id, **updated}
        except YouTubeQuotaExceeded:
            raise
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

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
        conn = self._get_db()
        try:
            conn.execute("""
                UPDATE youtube_quota_events
                SET status = ?, reason = ?, finished_at = ?, metadata_json = ?
                WHERE id = ?
            """, (
                status, reason, datetime.now(timezone.utc).isoformat(),
                json.dumps(metadata or {}, ensure_ascii=False, default=str), int(event_id),
            ))
            conn.commit()
        finally:
            conn.close()

    def get_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        conn = self._get_db()
        try:
            rows = conn.execute("""
                SELECT * FROM youtube_quota_events ORDER BY id DESC LIMIT ?
            """, (max(1, min(int(limit), 1000)),)).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                for key in ("remaining_json", "metadata_json"):
                    try:
                        item[key.removesuffix("_json")] = json.loads(item.pop(key) or "{}")
                    except (TypeError, ValueError):
                        item[key.removesuffix("_json")] = {}
                result.append(item)
            return result
        finally:
            conn.close()

    def seconds_until_reset(self) -> int:
        now = datetime.now(timezone.utc)
        local_now = now.astimezone(QUOTA_TIMEZONE)
        next_local_midnight = datetime.combine(
            local_now.date() + timedelta(days=1), time.min, tzinfo=QUOTA_TIMEZONE
        )
        return max(int((next_local_midnight.astimezone(timezone.utc) - now).total_seconds()), 0)

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

from __future__ import annotations

import math
import os
import sqlite3

from datetime import datetime, timezone


class YouTubeQuotaManager:
    """
    Manages YouTube daily quota.

    The Director does not need to know the raw remaining quota.
    This class is responsible for:
    - reading actual usage;
    - calculating remaining quota;
    - calculating a dynamic reserve;
    - determining how much resource can currently be allocated.
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
            search_daily_limit
            if search_daily_limit is not None
            else os.environ.get(
                "YOUTUBE_SEARCH_DAILY_LIMIT",
                "100",
            )
        )

        self.other_daily_limit = int(
            other_daily_limit
            if other_daily_limit is not None
            else os.environ.get(
                "YOUTUBE_OTHER_DAILY_QUOTA_UNITS",
                "10000",
            )
        )

        self.base_reserve_ratio = float(
            base_reserve_ratio
            if base_reserve_ratio is not None
            else os.environ.get(
                "YOUTUBE_OTHER_RESERVE_RATIO",
                "0.20",
            )
        )

    # ========================================================
    # DATABASE
    # ========================================================

    def _get_db(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            self.db_path
        )
        conn.row_factory = sqlite3.Row
        return conn

    # ========================================================
    # USAGE
    # ========================================================

    def get_usage(self) -> dict[str, int]:

        conn = self._get_db()

        try:
            row = conn.execute(
                """
                SELECT
                    COALESCE(
                        SUM(search_calls),
                        0
                    ) AS search_calls,
                    COALESCE(
                        SUM(other_units),
                        0
                    ) AS other_units
                FROM youtube_quota_usage
                WHERE created_at >= date('now')
                """
            ).fetchone()

            return {
                "search_calls": int(
                    row["search_calls"] or 0
                ),
                "other_units": int(
                    row["other_units"] or 0
                ),
            }

        finally:
            conn.close()

    # ========================================================
    # REMAINING
    # ========================================================

    def get_remaining(self) -> dict[str, int]:

        usage = self.get_usage()

        return {
            "search_remaining": max(
                self.search_daily_limit
                - usage["search_calls"],
                0,
            ),
            "other_remaining": max(
                self.other_daily_limit
                - usage["other_units"],
                0,
            ),
        }

    # ========================================================
    # TIME UNTIL RESET
    # ========================================================

    def seconds_until_reset(self) -> int:

        now = datetime.now(
            timezone.utc
        )

        next_day = (
            now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
        )

        if now >= next_day:
            from datetime import timedelta

            next_day += timedelta(
                days=1
            )

        return max(
            int(
                (
                    next_day - now
                ).total_seconds()
            ),
            0,
        )

    # ========================================================
    # DYNAMIC RESERVE
    # ========================================================

    def get_reserve_ratio(self) -> float:
        """
        Reserve protects future work.

        As the daily reset approaches,
        the reserve gradually decreases.

        The reserve never becomes negative.
        """

        seconds_left = (
            self.seconds_until_reset()
        )

        hours_left = (
            seconds_left / 3600
        )

        base = max(
            min(
                self.base_reserve_ratio,
                1.0,
            ),
            0.0,
        )

        if hours_left >= 12:
            return base

        if hours_left <= 1:
            return 0.0

        return base * (
            (hours_left - 1)
            / 11
        )

    # ========================================================
    # ALLOCATABLE RESOURCE
    # ========================================================

    def get_available_budget(
        self,
    ) -> dict[str, int | float | bool]:

        remaining = (
            self.get_remaining()
        )

        reserve_ratio = (
            self.get_reserve_ratio()
        )

        search_reserve = int(
            math.ceil(
                remaining["search_remaining"]
                * reserve_ratio
            )
        )

        other_reserve = int(
            math.ceil(
                remaining["other_remaining"]
                * reserve_ratio
            )
        )

        search_available = max(
            remaining["search_remaining"]
            - search_reserve,
            0,
        )

        other_available = max(
            remaining["other_remaining"]
            - other_reserve,
            0,
        )

        return {
            "search_available": search_available,
            "other_available": other_available,
            "reserve_ratio": reserve_ratio,
            "seconds_until_reset": (
                self.seconds_until_reset()
            ),
            "resource_available": (
                search_available > 0
                or other_available > 0
            ),
        }

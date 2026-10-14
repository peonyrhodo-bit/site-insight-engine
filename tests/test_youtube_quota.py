import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from quota.youtube_quota import YouTubeQuotaExceeded, YouTubeQuotaManager


class YouTubeQuotaManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.manager = YouTubeQuotaManager(
            db_path=str(Path(self.tmp.name) / "quota.sqlite3"),
            search_daily_limit=1,
            other_daily_limit=2,
            base_reserve_ratio=0,
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_exhaustion_does_not_block_other_bucket(self):
        token = self.manager.authorize_call(
            bucket="search", operation="search", method="search.list"
        )
        self.manager.finish_call(token["event_id"], status="error", reason="simulated API error")

        with self.assertRaises(YouTubeQuotaExceeded):
            self.manager.authorize_call(
                bucket="search", operation="search-again", method="search.list"
            )

        stats_token = self.manager.authorize_call(
            bucket="other", operation="refresh-known", method="videos.list"
        )
        self.manager.finish_call(stats_token["event_id"], status="succeeded")

        status = self.manager.get_status()
        self.assertEqual(status["search_calls"], 1)
        self.assertEqual(status["search_remaining"], 0)
        self.assertEqual(status["other_units"], 1)
        self.assertEqual(status["other_remaining"], 1)

    def test_attempts_are_charged_and_outcomes_are_audited(self):
        token = self.manager.authorize_call(
            bucket="other", operation="refresh-known", method="videos.list",
            metadata={"batch_size": 50},
        )
        self.manager.finish_call(token["event_id"], status="error", reason="timeout")
        event = self.manager.get_events(limit=1)[0]
        self.assertEqual(event["status"], "error")
        self.assertEqual(event["reason"], "timeout")
        self.assertEqual(event["metadata"]["batch_size"], 50)
        self.assertEqual(self.manager.get_status()["other_units"], 1)

    def test_reset_uses_pacific_midnight_including_dst(self):
        # 2026-03-08 is the spring-forward day in Los Angeles.
        now = datetime(2026, 3, 8, 8, 30, tzinfo=timezone.utc)
        start = self.manager._period_start_utc(now)
        self.assertEqual(start.astimezone(ZoneInfo("America/Los_Angeles")).hour, 0)
        self.assertEqual(start.astimezone(ZoneInfo("America/Los_Angeles")).date().isoformat(), "2026-03-08")


if __name__ == "__main__":
    unittest.main()

import unittest

from quota.unavailable_youtube_quota import UnavailableYouTubeQuotaManager


class UnavailableQuotaManagerTests(unittest.TestCase):
    def test_preflight_fails_closed_when_authority_is_unavailable(self):
        manager = UnavailableYouTubeQuotaManager(reason="password authentication failed")

        with self.assertRaisesRegex(RuntimeError, "outbound YouTube API calls are blocked"):
            manager.preflight_call(
                bucket="search",
                operation="search_videos",
                method="search.list",
            )

    def test_internal_authorization_fails_closed(self):
        manager = UnavailableYouTubeQuotaManager(reason="ledger unavailable")

        with self.assertRaisesRegex(RuntimeError, "youtube_quota_authority_unavailable"):
            manager.authorize_call(
                bucket="search",
                operation="search_videos",
                method="search.list",
            )


if __name__ == "__main__":
    unittest.main()

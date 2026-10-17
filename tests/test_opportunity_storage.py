"""Regression tests for opportunity data persistence summaries."""

import unittest
from unittest.mock import MagicMock

from memory.supabase import SupabaseMemoryBackend


class OpportunityStorageTests(unittest.TestCase):
    def test_save_opportunity_data_returns_counts_for_valid_rows(self):
        client = MagicMock()
        # The active implementation counts rows only when Supabase returns an id.
        # Model the response from upsert(...).select("id").execute(). A bare
        # MagicMock has a non-list .data attribute and correctly counts as no rows.
        client.table.return_value.upsert.return_value.select.return_value.execute.return_value.data = [{"id": 1}]
        backend = SupabaseMemoryBackend(client=client)

        counts = backend.save_opportunity_data(
            project_id="project-1",
            data={
                "channels": [{"channel_id": "UC1", "title": "Channel"}],
                "channel_snapshots": [
                    {"channel_id": "UC1", "captured_at": "2026-10-17T00:00:00Z"}
                ],
                "niches": [{"niche_id": "niche-1", "name": "Cooking"}],
                "niche_snapshots": [
                    {"niche_id": "niche-1", "captured_at": "2026-10-17T00:00:00Z"}
                ],
            },
        )

        self.assertEqual(
            counts,
            {
                "channels": 1,
                "channel_snapshots": 1,
                "niches": 1,
                "niche_snapshots": 1,
            },
        )
        self.assertEqual(client.table.call_count, 4)

    def test_save_opportunity_data_returns_zero_counts_for_empty_data(self):
        backend = SupabaseMemoryBackend(client=MagicMock())
        self.assertEqual(
            backend.save_opportunity_data(project_id="project-1", data={}),
            {
                "channels": 0,
                "channel_snapshots": 0,
                "niches": 0,
                "niche_snapshots": 0,
            },
        )


if __name__ == "__main__":
    unittest.main()

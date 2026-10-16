import unittest

from director.research_executor import _extract_video_id, _validate_search_items


class SearchResponseValidationTests(unittest.TestCase):
    def test_empty_search_results_are_valid(self):
        self.assertIsNone(_validate_search_items([]))

    def test_nonempty_search_results_without_video_ids_are_malformed(self):
        malformed_items = [
            [None],
            ["not a video"],
            [{"snippet": {"title": "Missing ID"}}],
            [{"id": {"channelId": "channel-only"}}],
            [{"id": {"videoId": ""}}],
        ]
        for items in malformed_items:
            with self.subTest(items=items):
                with self.assertRaisesRegex(ValueError, "youtube_mcp_malformed_response"):
                    _validate_search_items(items)

    def test_extract_video_id_accepts_only_supported_scalar_ids(self):
        cases = [
            ({"id": {"videoId": "abc123"}}, "abc123"),
            ({"video_id": "abc123"}, "abc123"),
            ({"youtube_id": "abc123"}, "abc123"),
            ({"id": "abc123"}, "abc123"),
            ({"id": {"channelId": "not-a-video"}}, None),
            ({"id": {"videoId": {"unexpected": "object"}}}, None),
        ]
        for item, expected in cases:
            with self.subTest(item=item):
                self.assertEqual(_extract_video_id(item), expected)

    def test_mixed_valid_and_malformed_items_are_not_misclassified_as_empty(self):
        items = [
            {"snippet": {"title": "Malformed item"}},
            {"id": {"videoId": "abc123"}},
        ]
        self.assertIsNone(_validate_search_items(items))


if __name__ == "__main__":
    unittest.main()

import pytest

from director.research_executor import _extract_video_id, _validate_search_items


def test_empty_search_results_are_valid():
    assert _validate_search_items([]) is None


@pytest.mark.parametrize(
    "items",
    [
        [None],
        ["not a video"],
        [{"snippet": {"title": "Missing ID"}}],
        [{"id": {"channelId": "channel-only"}}],
        [{"id": {"videoId": ""}}],
    ],
)
def test_nonempty_search_results_without_video_ids_are_malformed(items):
    with pytest.raises(ValueError, match="youtube_mcp_malformed_response"):
        _validate_search_items(items)


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"id": {"videoId": "abc123"}}, "abc123"),
        ({"video_id": "abc123"}, "abc123"),
        ({"youtube_id": "abc123"}, "abc123"),
        ({"id": "abc123"}, "abc123"),
        ({"id": {"channelId": "not-a-video"}}, None),
        ({"id": {"videoId": {"unexpected": "object"}}}, None),
    ],
)
def test_extract_video_id_accepts_only_supported_scalar_ids(item, expected):
    assert _extract_video_id(item) == expected


def test_mixed_valid_and_malformed_items_are_not_misclassified_as_empty():
    items = [
        {"snippet": {"title": "Malformed item"}},
        {"id": {"videoId": "abc123"}},
    ]
    assert _validate_search_items(items) is None

"""Offline regression tests for targeted Memory 2.0 collection reads."""

from types import SimpleNamespace

import pytest

from memory.director_adapter import ServerMemory
from memory.read_status import MemoryReadError, MemoryTableReadError


@pytest.mark.asyncio
async def test_recommendations_reader_only_fetches_recommendations():
    calls = []

    class Backend:
        def get_recent_recommendations(self, *, project_id, limit):
            calls.append(("recommendations", project_id, limit))
            return [
                {"id": 5, "source_data": {"director_recommendation_id": "rec-5"}},
            ]

        def get_context(self, **kwargs):
            raise AssertionError("Full eight-table context must not be read")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = SimpleNamespace(get_context=adapter.backend.get_context)

    rows = await adapter.get_collection("recommendations", project_id="alpha", limit=3)

    assert calls == [("recommendations", "alpha", 3)]
    assert rows[0]["recommendation_id"] == "rec-5"


@pytest.mark.asyncio
async def test_events_reader_only_fetches_events():
    calls = []

    class Backend:
        def get_recent_events(self, *, project_id, limit):
            calls.append((project_id, limit))
            return [{"id": 1, "event": "created"}]

        def get_context(self, **kwargs):
            raise AssertionError("Full context must not be read")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = SimpleNamespace(get_context=adapter.backend.get_context)

    rows = await adapter.get_collection("events", project_id="beta", limit=2)

    assert calls == [("beta", 2)]
    assert rows == [{"id": 1, "event": "created"}]


@pytest.mark.asyncio
async def test_targeted_read_failure_is_not_silently_empty():
    class Backend:
        def get_recent_events(self, **kwargs):
            raise RuntimeError("database unavailable")

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = object()

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_collection("events", project_id="alpha")

    assert error.value.status == "error"
    assert "database unavailable" in error.value.errors["events"]


@pytest.mark.asyncio
async def test_partial_page_failure_is_not_silently_accepted():
    class Backend:
        def get_recent_recommendations(self, **kwargs):
            raise MemoryTableReadError(
                "director_recommendations",
                partial_rows=[{"id": 1}],
                cause=RuntimeError("page two failed"),
            )

    adapter = object.__new__(ServerMemory)
    adapter.backend = Backend()
    adapter.memory = object()

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_collection("recommendations", project_id="alpha")

    assert error.value.status == "partial"
    assert error.value.context["recommendations"] == [{"id": 1}]
    assert "page two failed" in error.value.errors["recommendations"]


@pytest.mark.asyncio
async def test_missing_reader_uses_full_context_fail_closed_fallback():
    adapter = object.__new__(ServerMemory)
    adapter.backend = object()
    adapter.memory = SimpleNamespace(
        get_context=lambda **kwargs: {
            "recommendations": [{"id": 7}],
            "_memory_read": {"status": "complete", "tables": {}, "errors": {}},
        },
    )

    rows = await adapter.get_collection("recommendations", project_id="alpha")

    assert rows[0]["recommendation_id"] == 7


@pytest.mark.asyncio
async def test_unavailable_backend_fails_closed():
    adapter = object.__new__(ServerMemory)
    adapter.backend = None
    adapter.memory = None

    with pytest.raises(MemoryReadError):
        await adapter.get_collection("events")


@pytest.mark.asyncio
async def test_unknown_collection_is_rejected():
    adapter = object.__new__(ServerMemory)
    adapter.backend = object()
    adapter.memory = object()

    with pytest.raises(ValueError):
        await adapter.get_collection("runs")


def test_supabase_recommendations_do_not_swallow_database_failure():
    from memory.supabase import SupabaseMemoryBackend

    backend = object.__new__(SupabaseMemoryBackend)

    def fail(*args, **kwargs):
        raise RuntimeError("supabase 402 quota exceeded")

    backend._recent_for_project = fail

    with pytest.raises(RuntimeError, match="402"):
        backend.get_recent_recommendations(project_id="alpha", limit=5)


@pytest.mark.asyncio
async def test_supabase_read_failure_propagates_through_adapter():
    from memory.supabase import SupabaseMemoryBackend

    backend = object.__new__(SupabaseMemoryBackend)

    def fail(*args, **kwargs):
        raise RuntimeError("supabase 402 quota exceeded")

    backend._recent_for_project = fail
    adapter = object.__new__(ServerMemory)
    adapter.backend = backend
    adapter.memory = object()

    with pytest.raises(MemoryReadError) as error:
        await adapter.get_collection("recommendations", project_id="alpha", limit=5)

    assert error.value.status == "error"
    assert "402" in error.value.errors["recommendations"]


@pytest.mark.asyncio
async def test_inmemory_backend_keeps_projects_isolated():
    from memory.inmemory import InMemoryMemoryBackend

    backend = InMemoryMemoryBackend()
    backend._recommendations.extend([
        {"id": 1, "project_id": "alpha", "title": "A"},
        {"id": 2, "project_id": "beta", "title": "B"},
    ])
    backend._events.extend([
        {"id": 3, "project_id": "alpha", "event": "A"},
        {"id": 4, "project_id": "beta", "event": "B"},
    ])
    adapter = object.__new__(ServerMemory)
    adapter.backend = backend
    adapter.memory = object()

    recommendations = await adapter.get_collection(
        "recommendations", project_id="alpha",
    )
    events = await adapter.get_collection("events", project_id="beta")

    assert [row["id"] for row in recommendations] == [1]
    assert [row["id"] for row in events] == [4]


@pytest.mark.asyncio
async def test_api_routes_preserve_response_shape_without_full_context(monkeypatch):
    import server

    calls = []

    class MemoryStub:
        async def get_collection(self, name, *, project_id, limit):
            calls.append((name, project_id, limit))
            return [{"id": 9, "recommendation_id": "legacy-9"}] if name == "recommendations" else [{"id": 8}]

        async def get_context(self, **kwargs):
            raise AssertionError("API should not request full memory context")

    monkeypatch.setattr(server.runtime, "memory", MemoryStub())

    recommendations = await server.director_recommendations(
        project_id="alpha", limit=4,
    )
    events = await server.events(project_id="beta", limit=6)

    assert recommendations == {
        "project_id": "alpha",
        "recommendations": [{"id": 9, "recommendation_id": "legacy-9"}],
    }
    assert events == {"project_id": "beta", "events": [{"id": 8}]}
    assert calls == [
        ("recommendations", "alpha", 4),
        ("events", "beta", 6),
    ]

@pytest.mark.asyncio
async def test_director_decision_carries_history_evidence():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate YouTube topics'
    history = {'youtube': {'video_count': 321, 'snapshot_count': 654}}
    analysis = {
        'opportunities': [{'opportunity_id': 'topic-1', 'title': 'Topic 1', 'overall_score': 0.9}],
        'history_analytics': history,
    }
    decision = await director.decide(analysis)
    assert decision.metadata['history_analytics'] == history
    assert decision.metadata['opportunity_id'] == 'topic-1'

@pytest.mark.asyncio
async def test_global_history_does_not_falsely_reorder_opportunities():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    analysis = {
        'opportunities': [
            {'opportunity_id': 'strong', 'overall_score': 0.9},
            {'opportunity_id': 'weak', 'overall_score': 0.2},
        ],
        'history_analytics': {
            'youtube': {'status': 'complete', 'video_count': 5000,
                        'snapshot_count': 10000, 'top_topics': [
                            {'topic': 'weak', 'videos': 3000}
                        ]}
        },
    }
    decision = await director.decide(analysis)
    assert decision.metadata['opportunity_id'] == 'strong'
    assert decision.metadata['history_analytics'] == analysis['history_analytics']

@pytest.mark.asyncio
async def test_director_links_only_exact_historical_topic_to_candidate():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    analysis = {
        'opportunities': [{'opportunity_id': 'topic-1', 'title': 'Garden Ideas', 'overall_score': 0.9}],
        'history_analytics': {'youtube': {'status': 'complete', 'top_topics': [
            {'topic': 'garden ideas', 'videos': 17},
            {'topic': 'garden', 'videos': 900},
        ]}},
    }
    decision = await director.decide(analysis)
    assert decision.metadata['matching_historical_topics'] == [
        {'topic': 'garden ideas', 'videos': 17},
    ]

@pytest.mark.asyncio
async def test_partial_history_cannot_validate_specific_topic():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    analysis = {
        'opportunities': [{'opportunity_id': 'topic-1', 'title': 'Garden Ideas', 'overall_score': 0.9}],
        'history_analytics': {'youtube': {
            'status': 'partial', 'top_topics': [{'topic': 'Garden Ideas', 'videos': 17}],
        }},
    }
    decision = await director.decide(analysis)
    assert 'matching_historical_topics' not in decision.metadata
    assert decision.metadata['history_analytics']['youtube']['status'] == 'partial'

def test_streaming_history_tracks_per_topic_views_only_when_observed():
    from analytics.streaming import StreamingYouTubeAnalytics
    stats = StreamingYouTubeAnalytics()
    stats.add_video({'video_id': 'a', 'metadata': {'topic': 'Gardening'}, 'views': 100})
    stats.add_video({'video_id': 'b', 'metadata': {'topic': 'Gardening'}, 'views': 300})
    stats.add_video({'video_id': 'c', 'metadata': {'topic': 'Gardening'}})
    stats.add_video({'video_id': 'd', 'metadata': {'topic': 'Cooking'}, 'views': 50})
    result = stats.to_dict()
    by_topic = {row['topic']: row for row in result['topic_view_metrics']}
    assert by_topic['Gardening'] == {
        'topic': 'Gardening', 'videos_with_views': 2, 'average_views': 200.0,
        'source': 'videos.data_json.statistics', 'snapshot_views_included': False,
    }
    assert by_topic['Cooking']['average_views'] == 50.0
    assert next(row['videos'] for row in result['top_topics'] if row['topic'] == 'Gardening') == 3

@pytest.mark.asyncio
async def test_director_attaches_only_verified_topic_view_performance():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    analysis = {
        'opportunities': [{'opportunity_id': 'garden', 'title': 'Gardening', 'overall_score': 0.9}],
        'history_analytics': {'youtube': {
            'status': 'complete',
            'top_topics': [{'topic': 'Gardening', 'videos': 10}],
            'topic_view_metrics': [
                {'topic': 'gardening', 'videos_with_views': 3, 'average_views': 200.0},
                {'topic': 'Cooking', 'videos_with_views': 99, 'average_views': 90000.0},
            ],
        }},
    }
    decision = await director.decide(analysis)
    assert decision.metadata['matching_historical_view_metrics'] == [
        {'topic': 'gardening', 'videos_with_views': 3, 'average_views': 200.0},
    ]
    assert decision.metadata['historical_view_coverage'] == [
        {'topic': 'gardening', 'videos_with_views': 3, 'topic_video_count': 10, 'fraction': 0.3},
    ]
    assert decision.metadata['historical_evidence_quality'][0]['status'] == 'limited_sample'

@pytest.mark.asyncio
async def test_sufficient_historical_sample_is_labeled_without_changing_rank():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    analysis = {
        'opportunities': [
            {'opportunity_id': 'gardening', 'title': 'Gardening', 'overall_score': 0.9},
            {'opportunity_id': 'cooking', 'title': 'Cooking', 'overall_score': 0.8},
        ],
        'history_analytics': {'youtube': {
            'status': 'complete',
            'top_topics': [{'topic': 'Gardening', 'videos': 40}],
            'topic_view_metrics': [{'topic': 'Gardening', 'videos_with_views': 25, 'average_views': 200.0}],
        }},
    }
    decision = await director.decide(analysis)
    assert decision.metadata['opportunity_id'] == 'gardening'
    assert decision.metadata['historical_evidence_quality'][0]['status'] == 'sufficient_sample'

def test_streaming_deduplicates_topic_labels_within_one_video():
    from analytics.streaming import StreamingYouTubeAnalytics
    stats = StreamingYouTubeAnalytics()
    stats.add_video({
        'video_id': 'a', 'views': 100,
        'metadata': {'topic': 'Gardening', 'niche': 'Gardening',
                     'tags': ['Gardening', 'Gardening']},
    })
    result = stats.to_dict()
    assert result['top_topics'] == [{'topic': 'Gardening', 'videos': 1}]
    assert result['topic_view_metrics'][0]['videos_with_views'] == 1

@pytest.mark.asyncio
async def test_niche_comparison_excludes_thin_samples_without_reordering():
    from director.director import Director
    director = Director(project_id='alpha')
    director.context.objective = 'Evaluate topics'
    decision = await director.decide({
        'opportunities': [
            {'opportunity_id': 'a', 'title': 'Gardening', 'overall_score': 0.9},
            {'opportunity_id': 'b', 'title': 'Cooking', 'overall_score': 0.8},
        ],
        'history_analytics': {'youtube': {
            'status': 'complete',
            'snapshot_topic_attribution': 'partial',
            'snapshot_topic_join_misses': 7,
            'top_topics': [{'topic': 'Gardening', 'videos': 40},
                           {'topic': 'Cooking', 'videos': 100}],
            'topic_view_metrics': [
                {'topic': 'Gardening', 'videos_with_views': 30, 'average_views': 200.0},
                {'topic': 'Cooking', 'videos_with_views': 2, 'average_views': 90000.0},
            ],
        }},
    })
    assert decision.metadata['opportunity_id'] == 'a'
    assert decision.metadata['historical_niche_comparison'] == [
        {'topic': 'Gardening', 'videos_with_views': 30,
         'topic_video_count': 40, 'average_views': 200.0},
    ]
    assert decision.metadata['snapshot_niche_evidence_status'] == 'partial'
    assert decision.metadata['snapshot_niche_unmatched_count'] == 7

def test_supabase_streaming_reads_video_views_from_data_json():
    from memory.supabase import SupabaseMemoryBackend
    backend = object.__new__(SupabaseMemoryBackend)
    def rows(table, **kwargs):
        if table == 'videos':
            yield {
                'video_id': 'abc',
                'data_json': {
                    'snippet': {'title': 'Garden', 'channelId': 'c'},
                    'topic': 'Gardening',
                    'statistics': {'viewCount': '240'},
                },
            }
    backend._iter_paginated_rows = rows
    result = backend.load_youtube_analysis_data()
    metrics = result['history_analytics']['topic_view_metrics']
    assert metrics == [{'topic': 'Gardening', 'videos_with_views': 1, 'average_views': 240.0,
                        'source': 'videos.data_json.statistics', 'snapshot_views_included': False}]
    assert 'views' not in result['videos'][0]

def test_snapshot_topic_views_are_separate_and_require_explicit_topic():
    from analytics.streaming import StreamingYouTubeAnalytics
    stats = StreamingYouTubeAnalytics()
    stats.add_snapshot({'video_id': 'a', 'data_json': {
        'topic': 'Gardening', 'statistics': {'viewCount': '100'},
    }})
    stats.add_snapshot({'video_id': 'a', 'data_json': {
        'topic': 'Gardening', 'statistics': {'viewCount': '200'},
    }})
    stats.add_snapshot({'video_id': 'b', 'data_json': {
        'statistics': {'viewCount': '9000'},
    }})
    result = stats.to_dict()
    assert result['snapshot_topic_view_metrics'] == [{
        'topic': 'Gardening', 'snapshots_with_views': 2,
        'average_snapshot_views': 150.0, 'source': 'video_snapshots.data_json',
        'unit': 'snapshots_not_unique_videos',
    }]
    assert result['topic_view_metrics'] == []

def test_snapshot_video_id_join_uses_bounded_video_topic_index():
    from analytics.streaming import StreamingYouTubeAnalytics
    stats = StreamingYouTubeAnalytics()
    stats.add_video({'video_id': 'a', 'metadata': {'topic': 'Gardening'}})
    stats.add_snapshot({'video_id': 'a', 'data_json': {
        'statistics': {'viewCount': '400'},
    }})
    stats.add_snapshot({'video_id': 'unknown', 'data_json': {
        'statistics': {'viewCount': '900'},
    }})
    result = stats.to_dict()
    assert result['snapshot_topic_view_metrics'][0]['topic'] == 'Gardening'
    assert result['snapshot_topic_view_metrics'][0]['average_snapshot_views'] == 400.0
    assert result['snapshot_topic_join_misses'] == 1
    assert result['snapshot_video_topic_index_limit'] == 1000
    assert result['snapshot_topic_join_hits'] == 1
    assert result['snapshot_topic_attribution'] == 'partial'

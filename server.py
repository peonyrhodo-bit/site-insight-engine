import json
import logging
import math
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "youtube.db"

MCP_URL = os.environ.get(
    "MCP_URL",
    "http://youtube-mcp:8002/mcp",
).strip()

FREE_MODE = (
    os.environ.get(
        "FREE_MODE",
        "true",
    ).lower()
    == "true"
)

AUTONOMOUS = (
    os.environ.get(
        "AUTONOMOUS",
        "false",
    ).lower()
    == "true"
)

# AI
GEMINI_API_KEY = os.environ.get(
    "GEMINI_API_KEY",
    "",
).strip()

GEMINI_MODEL = os.environ.get(
    "GEMINI_MODEL",
    "gemini-3.7-flash",
).strip()

AI_ENABLED = (
    os.environ.get(
        "AI_ENABLED",
        "true",
    ).lower()
    == "true"
    and bool(GEMINI_API_KEY)
)


# ============================================================
# LOGGING
# ============================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)

logger = logging.getLogger(
    "site-insight-engine"
)


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="Site Insight Engine",
    version="1.0.0",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# DATABASE
# ============================================================

def get_db() -> sqlite3.Connection:
    conn = sqlite3.connect(
        DB_PATH,
        check_same_thread=False,
    )

    conn.row_factory = sqlite3.Row

    return conn


def init_db() -> None:
    conn = get_db()

    cursor = conn.cursor()

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            data_json TEXT,
            first_seen TEXT,
            last_seen TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            video_id TEXT,
            data_json TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS director_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            language TEXT,
            region_code TEXT,
            data_json TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            decision TEXT,
            data_json TEXT
        )
        """
    )

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS system_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            event_type TEXT,
            data_json TEXT
        )
        """
    )

    conn.commit()
    conn.close()


init_db()


# ============================================================
# GENERAL HELPERS
# ============================================================

def now_iso() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def json_dumps(data: Any) -> str:
    return json.dumps(
        data,
        ensure_ascii=False,
        default=str,
    )


def json_loads_safe(
    value: str | None,
    default: Any = None,
) -> Any:
    if not value:
        return default

    try:
        return json.loads(value)
    except Exception:
        return default


# ============================================================
# EVENTS
# ============================================================

def log_event(
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:
    conn = get_db()

    conn.execute(
        """
        INSERT INTO system_events (
            created_at,
            event_type,
            data_json
        )
        VALUES (?, ?, ?)
        """,
        (
            now_iso(),
            event_type,
            json_dumps(data or {}),
        ),
    )

    conn.commit()
    conn.close()


# ============================================================
# MCP
# ============================================================

async def mcp_call(
    name: str,
    args: dict[str, Any],
) -> Any:
    """
    Call a tool on youtube-mcp.
    """

    async with streamablehttp_client(
        MCP_URL
    ) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            await session.initialize()

            result = await session.call_tool(
                name,
                arguments=args,
            )

            return result


# ============================================================
# MCP RESULT HELPERS
# ============================================================

def extract_items(
    result: Any,
) -> list[dict[str, Any]]:
    if result is None:
        return []

    if isinstance(result, list):
        return result

    if isinstance(result, dict):
        items = result.get("items")

        if isinstance(items, list):
            return items

        return [result]

    structured = getattr(
        result,
        "structuredContent",
        None,
    )

    if isinstance(structured, dict):
        items = structured.get(
            "items"
        )

        if isinstance(items, list):
            return items

    content = getattr(
        result,
        "content",
        None,
    )

    if content:
        for item in content:
            text = getattr(
                item,
                "text",
                None,
            )

            if not text:
                continue

            try:
                parsed = json.loads(text)

                if isinstance(parsed, list):
                    return parsed

                if isinstance(parsed, dict):
                    items = parsed.get(
                        "items"
                    )

                    if isinstance(items, list):
                        return items

                    return [parsed]

            except Exception:
                continue

    return []


def extract_object(
    result: Any,
) -> dict[str, Any]:
    items = extract_items(result)

    if items:
        if len(items) == 1:
            return items[0]

        return {
            "items": items
        }

    return {}


# ============================================================
# SNAPSHOTS
# ============================================================

def save_snapshot(
    videos: list[dict[str, Any]],
) -> int:
    conn = get_db()

    created_at = now_iso()

    count = 0

    for video in videos:
        video_id = video.get(
            "video_id"
        ) or video.get("id")

        if not video_id:
            continue

        video_id = str(video_id)

        data_json = json_dumps(video)

        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO videos (
                video_id,
                data_json,
                first_seen,
                last_seen
            )
            VALUES (?, ?, ?, ?)
            ON CONFLICT(video_id)
            DO UPDATE SET
                data_json = excluded.data_json,
                last_seen = excluded.last_seen
            """,
            (
                video_id,
                data_json,
                created_at,
                created_at,
            ),
        )

        cursor.execute(
            """
            INSERT INTO video_snapshots (
                created_at,
                video_id,
                data_json
            )
            VALUES (?, ?, ?)
            """,
            (
                created_at,
                video_id,
                data_json,
            ),
        )

        count += 1

    conn.commit()
    conn.close()

    return count


# ============================================================
# HEURISTIC ANALYSIS
# ============================================================

def score(
    video: dict[str, Any],
) -> float:
    views = float(
        video.get(
            "views",
            video.get(
                "viewCount",
                0,
            ),
        )
        or 0
    )

    likes = float(
        video.get(
            "likes",
            video.get(
                "likeCount",
                0,
            ),
        )
        or 0
    )

    comments = float(
        video.get(
            "comments",
            video.get(
                "commentCount",
                0,
            ),
        )
        or 0
    )

    return (
        math.log10(
            max(views, 1)
        )
        + 0.5
        * math.log10(
            max(likes, 1)
        )
        + 0.5
        * math.log10(
            max(comments, 1)
        )
    )


def make_heuristic_hypothesis(
    videos: list[dict[str, Any]],
) -> dict[str, Any]:
    ranked = sorted(
        videos,
        key=score,
        reverse=True,
    )

    top = ranked[:10]

    topics = []

    for video in top:
        title = video.get(
            "title",
            "",
        )

        if title:
            topics.append(title)

    return {
        "provider": "heuristic",
        "hypothesis": (
            "The strongest current signals are "
            "concentrated among the highest-ranked "
            "videos in the collected radar."
        ),
        "reasoning": (
            "Ranking combines logarithmic views, "
            "likes and comments. This is a signal "
            "for analysis, not a prediction of future success."
        ),
        "topics": topics[:10],
        "formats": [],
        "experiments": [],
        "confidence": 0.3,
    }


# ============================================================
# GEMINI AI
# ============================================================

def ai_error_message(
    response: requests.Response,
) -> str:
    """
    Return a safe AI error.
    Never include the API key.
    """

    try:
        data = response.json()

        error = data.get(
            "error",
            {},
        )

        message = error.get(
            "message",
            "",
        )

        return str(message)[:500]

    except Exception:
        return (
            f"HTTP {response.status_code}"
        )


def gemini_generate_json(
    system_instruction: str,
    prompt: str,
) -> dict[str, Any]:
    """
    Call Gemini using the REST API.

    API key is sent only in the HTTP header.
    It is never included in logs.
    """

    if not GEMINI_API_KEY:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured"
        )

    url = (
        "https://generativelanguage.googleapis.com"
        f"/v1beta/models/{GEMINI_MODEL}:generateContent"
    )

    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": GEMINI_API_KEY,
    }

    payload = {
        "system_instruction": {
            "parts": [
                {
                    "text": system_instruction
                }
            ]
        },
        "contents": [
            {
                "parts": [
                    {
                        "text": prompt
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=60,
        )

    except requests.RequestException as exc:
        logger.error(
            "AI_REQUEST_ERROR provider=gemini error_type=%s",
            type(exc).__name__,
        )

        raise RuntimeError(
            "Gemini request failed"
        ) from exc

    if not response.ok:
        safe_message = ai_error_message(
            response
        )

        logger.error(
            "AI_API_ERROR provider=gemini status=%s message=%s",
            response.status_code,
            safe_message,
        )

        raise RuntimeError(
            f"Gemini API error: {safe_message}"
        )

    try:
        data = response.json()

    except ValueError as exc:
        logger.error(
            "AI_INVALID_JSON_RESPONSE provider=gemini"
        )

        raise RuntimeError(
            "Gemini returned invalid JSON"
        ) from exc

    candidates = data.get(
        "candidates",
        [],
    )

    if not candidates:
        raise RuntimeError(
            "Gemini returned no candidates"
        )

    parts = (
        candidates[0]
        .get("content", {})
        .get("parts", [])
    )

    text_parts = []

    for part in parts:
        text = part.get("text")

        if text:
            text_parts.append(text)

    text = "\n".join(
        text_parts
    ).strip()

    if not text:
        raise RuntimeError(
            "Gemini returned empty content"
        )

    try:
        return json.loads(text)

    except json.JSONDecodeError:
        # Try to recover JSON enclosed in markdown.
        cleaned = text.strip()

        if cleaned.startswith(
            "```"
        ):
            cleaned = (
                cleaned
                .replace(
                    "```json",
                    "",
                    1,
                )
                .replace(
                    "```",
                    "",
                )
                .strip()
            )

            try:
                return json.loads(
                    cleaned
                )

            except json.JSONDecodeError:
                pass

        raise RuntimeError(
            "Gemini returned non-JSON content"
        )


# ============================================================
# AI ANALYSIS
# ============================================================

def make_ai_hypothesis(
    videos: list[dict[str, Any]],
    trends: list[dict[str, Any]],
    language: str,
    region_code: str,
) -> dict[str, Any]:
    """
    Ask Gemini to analyze the collected YouTube signals.

    The AI is an analyst.
    It must not pretend to know which video will go viral.
    """

    ranked_videos = sorted(
        videos,
        key=score,
        reverse=True,
    )[:20]

    ranked_trends = sorted(
        trends,
        key=score,
        reverse=True,
    )[:10]

    compact_videos = []

    for video in ranked_videos:
        compact_videos.append(
            {
                "title": video.get(
                    "title",
                    "",
                ),
                "channel": video.get(
                    "channel_title",
                    "",
                ),
                "views": video.get(
                    "views",
                    0,
                ),
                "likes": video.get(
                    "likes",
                    0,
                ),
                "comments": video.get(
                    "comments",
                    0,
                ),
                "published_at": video.get(
                    "published_at",
                    "",
                ),
                "language": video.get(
                    "language",
                    language,
                ),
                "query": video.get(
                    "query",
                    "",
                ),
            }
        )

    compact_trends = []

    for video in ranked_trends:
        snippet = video.get(
            "snippet",
            {},
        )

        statistics = video.get(
            "statistics",
            {},
        )

        compact_trends.append(
            {
                "title": snippet.get(
                    "title",
                    video.get(
                        "title",
                        "",
                    ),
                ),
                "channel": snippet.get(
                    "channelTitle",
                    video.get(
                        "channel_title",
                        "",
                    ),
                ),
                "views": int(
                    statistics.get(
                        "viewCount",
                        video.get(
                            "views",
                            0,
                        ),
                    )
                    or 0
                ),
                "likes": int(
                    statistics.get(
                        "likeCount",
                        video.get(
                            "likes",
                            0,
                        ),
                    )
                    or 0
                ),
                "comments": int(
                    statistics.get(
                        "commentCount",
                        video.get(
                            "comments",
                            0,
                        ),
                    )
                    or 0
                ),
            }
        )

    system_instruction = """
You are the analytical brain of an AI Director for YouTube.

Your task is to analyze supplied YouTube observations.

Important rules:

1. Use ONLY the supplied data.
2. Do not invent facts.
3. Do not claim that you can predict viral success.
4. Treat views, likes, comments and other metrics as signals.
5. Look for evidence of growing or interesting demand.
6. Prefer repeated signals over a single unusual video.
7. Consider competition and format when evidence exists.
8. Do not recommend news.
9. Do not recommend politics.
10. Do not recommend 18+ content.
11. Moderate narrative violence may exist, but do not recommend gore,
    torture, graphic injury, glorification or incitement of violence.
12. If evidence is weak, explicitly say that evidence is insufficient.
13. Confidence means confidence in the interpretation of the supplied
    evidence, NOT probability of future viral success.

Return ONLY valid JSON with this structure:

{
  "hypothesis": "short statement",
  "reasoning": "evidence-based explanation",
  "topics": ["topic 1", "topic 2"],
  "formats": ["format 1", "format 2"],
  "experiments": ["experiment 1", "experiment 2"],
  "confidence": 0.0
}
"""

    prompt = json_dumps(
        {
            "task": (
                "Analyze current YouTube signals "
                "for the AI Director."
            ),
            "language": language,
            "region_code": region_code,
            "radar_videos": compact_videos,
            "trending_videos": compact_trends,
        }
    )

    result = gemini_generate_json(
        system_instruction=system_instruction,
        prompt=prompt,
    )

    # Normalize result
    return {
        "provider": "gemini",
        "model": GEMINI_MODEL,
        "hypothesis": str(
            result.get(
                "hypothesis",
                "",
            )
        ),
        "reasoning": str(
            result.get(
                "reasoning",
                "",
            )
        ),
        "topics": (
            result.get(
                "topics",
                [],
            )
            if isinstance(
                result.get(
                    "topics",
                    [],
                ),
                list,
            )
            else []
        ),
        "formats": (
            result.get(
                "formats",
                [],
            )
            if isinstance(
                result.get(
                    "formats",
                    [],
                ),
                list,
            )
            else []
        ),
        "experiments": (
            result.get(
                "experiments",
                [],
            )
            if isinstance(
                result.get(
                    "experiments",
                    [],
                ),
                list,
            )
            else []
        ),
        "confidence": float(
            result.get(
                "confidence",
                0.0,
            )
            or 0.0
        ),
    }


def make_hypothesis(
    videos: list[dict[str, Any]],
    language: str,
    region_code: str,
    trends: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    Use Gemini when available.
    Otherwise fall back to the local heuristic.
    """

    trends = trends or []

    if not AI_ENABLED:
        return make_heuristic_hypothesis(
            videos
        )

    try:
        result = make_ai_hypothesis(
            videos=videos,
            trends=trends,
            language=language,
            region_code=region_code,
        )

        log_event(
            "ai_analysis_completed",
            {
                "provider": "gemini",
                "model": GEMINI_MODEL,
            },
        )

        return result

    except Exception as exc:
        logger.error(
            "AI_ANALYSIS_FAILED provider=gemini error_type=%s",
            type(exc).__name__,
        )

        log_event(
            "ai_analysis_failed",
            {
                "provider": "gemini",
                "error_type": type(exc).__name__,
            },
        )

        fallback = make_heuristic_hypothesis(
            videos
        )

        fallback["ai_fallback_reason"] = (
            "Gemini analysis was unavailable; "
            "local heuristic used."
        )

        return fallback


# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def home():
    return """
    <html>
        <head>
            <title>AI YouTube System</title>
        </head>
        <body>
            <h1>Site Insight Engine</h1>
            <p>AI YouTube analytics engine is running.</p>
        </body>
    </html>
    """


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "site-insight-engine",
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "ai_enabled": AI_ENABLED,
        "ai_provider": (
            "gemini"
            if AI_ENABLED
            else "heuristic"
        ),
    }


@app.get("/system/status")
async def system_status():
    return {
        "status": "ok",
        "service": "site-insight-engine",
        "mcp_url": MCP_URL,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "ai": {
            "enabled": AI_ENABLED,
            "provider": (
                "gemini"
                if AI_ENABLED
                else "heuristic"
            ),
            "model": GEMINI_MODEL,
        },
    }


# ============================================================
# AI STATUS
# ============================================================

@app.get("/ai/status")
async def ai_status():
    return {
        "enabled": AI_ENABLED,
        "provider": (
            "gemini"
            if AI_ENABLED
            else "heuristic"
        ),
        "model": GEMINI_MODEL,
        "free_mode": FREE_MODE,
        "api_key_configured": bool(
            GEMINI_API_KEY
        ),
    }


@app.get("/ai/test")
async def ai_test():
    if not AI_ENABLED:
        return {
            "ok": False,
            "enabled": False,
            "provider": "heuristic",
            "message": (
                "Gemini is not enabled. "
                "Configure GEMINI_API_KEY."
            ),
        }

    try:
        result = gemini_generate_json(
            system_instruction=(
                "Return valid JSON only. "
                "The JSON must contain one key named "
                "\"message\"."
            ),
            prompt=(
                "Return a JSON object with "
                "\"message\": \"AI connection works\"."
            ),
        )

        return {
            "ok": True,
            "provider": "gemini",
            "model": GEMINI_MODEL,
            "result": result,
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "provider": "gemini",
                "error": str(exc),
            },
        )


# ============================================================
# SEARCH CHANNELS
# ============================================================

@app.get("/search-channels")
async def search_channels(
    query: str,
    max_results: int = 10,
):
    try:
        result = await mcp_call(
            "search_channels",
            {
                "query": query,
                "max_results": max_results,
            },
        )

        return {
            "items": extract_items(
                result
            )
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc)
            },
        )


# ============================================================
# SEARCH VIDEOS
# ============================================================

@app.get("/search-videos")
async def search_videos(
    query: str,
    max_results: int = 10,
    region_code: str = "US",
):
    try:
        result = await mcp_call(
            "search_videos",
            {
                "query": query,
                "max_results": max_results,
                "region_code": region_code,
            },
        )

        return {
            "items": extract_items(
                result
            )
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc)
            },
        )


# ============================================================
# TRENDING
# ============================================================

@app.get("/trending-videos")
async def trending_videos(
    max_results: int = 50,
    region_code: str = "US",
):
    try:
        result = await mcp_call(
            "search_trending_videos",
            {
                "max_results": max_results,
                "region_code": region_code,
            },
        )

        return {
            "items": extract_items(
                result
            )
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc)
            },
        )


# ============================================================
# RADAR
# ============================================================

@app.get("/radar-videos")
async def radar_videos(
    language: str = "ru",
    max_results_per_query: int = 10,
    region_code: str = "US",
):
    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "language": language,
                "max_results_per_query": (
                    max_results_per_query
                ),
                "region_code": region_code,
            },
        )

        return {
            "items": extract_items(
                result
            )
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "error": str(exc)
            },
        )


# ============================================================
# RADAR DEBUG
# ============================================================

@app.get("/radar-debug")
async def radar_debug(
    language: str = "ru",
    max_results_per_query: int = 10,
    region_code: str = "US",
):
    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "language": language,
                "max_results_per_query": (
                    max_results_per_query
                ),
                "region_code": region_code,
            },
        )

        items = extract_items(
            result
        )

        return {
            "ok": True,
            "count": len(items),
            "items": items[:20],
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(exc),
            },
        )


# ============================================================
# RADAR SAVE
# ============================================================

@app.get("/radar-save")
async def radar_save(
    language: str = "ru",
    max_results_per_query: int = 10,
    region_code: str = "US",
):
    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "language": language,
                "max_results_per_query": (
                    max_results_per_query
                ),
                "region_code": region_code,
            },
        )

        items = extract_items(
            result
        )

        saved = save_snapshot(
            items
        )

        return {
            "ok": True,
            "found": len(items),
            "saved": saved,
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(exc),
            },
        )


# ============================================================
# RADAR HISTORY
# ============================================================

@app.get("/radar-history")
async def radar_history(
    limit: int = 100,
):
    limit = max(
        1,
        min(int(limit), 1000),
    )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM video_snapshots
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "video_id": row["video_id"],
            "data": json_loads_safe(
                row["data_json"],
                {},
            ),
        }
        for row in rows
    ]


# ============================================================
# DATABASE STATUS
# ============================================================

@app.get("/database-status")
async def database_status():
    conn = get_db()

    videos_count = conn.execute(
        "SELECT COUNT(*) FROM videos"
    ).fetchone()[0]

    snapshots_count = conn.execute(
        "SELECT COUNT(*) FROM video_snapshots"
    ).fetchone()[0]

    runs_count = conn.execute(
        "SELECT COUNT(*) FROM director_runs"
    ).fetchone()[0]

    events_count = conn.execute(
        "SELECT COUNT(*) FROM system_events"
    ).fetchone()[0]

    conn.close()

    return {
        "database": str(DB_PATH),
        "videos": videos_count,
        "snapshots": snapshots_count,
        "director_runs": runs_count,
        "events": events_count,
    }


# ============================================================
# ANALYZE
# ============================================================

@app.get("/analyze")
async def analyze(
    language: str = "ru",
    max_results_per_query: int = 10,
    region_code: str = "US",
):
    try:
        radar_result = await mcp_call(
            "search_radar_videos",
            {
                "language": language,
                "max_results_per_query": (
                    max_results_per_query
                ),
                "region_code": region_code,
            },
        )

        videos = extract_items(
            radar_result
        )

        hypothesis = make_hypothesis(
            videos=videos,
            language=language,
            region_code=region_code,
            trends=[],
        )

        return {
            "ok": True,
            "videos_count": len(videos),
            "analysis": hypothesis,
        }

    except Exception as exc:
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": str(exc),
            },
        )


# ============================================================
# DIRECTOR DEBUG
# ============================================================

@app.get("/director-debug")
async def director_debug(
    language: str = "ru",
    region_code: str = "US",
):
    result = {
        "radar": None,
        "trending": None,
        "ai": {
            "enabled": AI_ENABLED,
            "provider": (
                "gemini"
                if AI_ENABLED
                else "heuristic"
            ),
            "model": GEMINI_MODEL,
        },
    }

    try:
        radar = await mcp_call(
            "search_radar_videos",
            {
                "language": language,
                "max_results_per_query": 10,
                "region_code": region_code,
            },
        )

        result["radar"] = {
            "ok": True,
            "count": len(
                extract_items(radar)
            ),
        }

    except Exception as exc:
        result["radar"] = {
            "ok": False,
            "error": str(exc),
        }

    try:
        trending = await mcp_call(
            "search_trending_videos",
            {
                "max_results": 20,
                "region_code": region_code,
            },
        )

        result["trending"] = {
            "ok": True,
            "count": len(
                extract_items(trending)
            ),
        }

    except Exception as exc:
        result["trending"] = {
            "ok": False,
            "error": str(exc),
        }

    return result


# ============================================================
# DIRECTOR RUN
# ============================================================

@app.post("/director/run")
@app.get("/director/run")
async def director_run(
    language: str = "ru",
    region_code: str = "US",
):
    started_at = now_iso()

    log_event(
        "director_run_started",
        {
            "language": language,
            "region_code": region_code,
        },
    )

    # --------------------------------------------------------
    # 1. RADAR
    # --------------------------------------------------------

    radar_result = await mcp_call(
        "search_radar_videos",
        {
            "language": language,
            "max_results_per_query": 10,
            "region_code": region_code,
        },
    )

    radar_videos = extract_items(
        radar_result
    )

    # --------------------------------------------------------
    # 2. SAVE RADAR SNAPSHOT
    # --------------------------------------------------------

    saved_count = save_snapshot(
        radar_videos
    )

    # --------------------------------------------------------
    # 3. TRENDING
    # --------------------------------------------------------

    trending_result = await mcp_call(
        "search_trending_videos",
        {
            "max_results": 30,
            "region_code": region_code,
        },
    )

    trending_videos = extract_items(
        trending_result
    )

    # --------------------------------------------------------
    # 4. AI ANALYSIS
    # --------------------------------------------------------

    analysis = make_hypothesis(
        videos=radar_videos,
        language=language,
        region_code=region_code,
        trends=trending_videos,
    )

    # --------------------------------------------------------
    # 5. DIRECTOR DECISION
    # --------------------------------------------------------

    if AUTONOMOUS:
        next_action = (
            "continue_autonomously"
        )
    else:
        next_action = (
            "requires_user_decision"
        )

    # --------------------------------------------------------
    # 6. SAVE RUN
    # --------------------------------------------------------

    run_data = {
        "started_at": started_at,
        "finished_at": now_iso(),
        "language": language,
        "region_code": region_code,
        "radar_count": len(
            radar_videos
        ),
        "saved_count": saved_count,
        "trending_count": len(
            trending_videos
        ),
        "analysis": analysis,
        "next_action": next_action,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
    }

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO director_runs (
            created_at,
            language,
            region_code,
            data_json
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            now_iso(),
            language,
            region_code,
            json_dumps(run_data),
        ),
    )

    run_id = cursor.lastrowid

    conn.commit()
    conn.close()

    log_event(
        "director_run_completed",
        {
            "run_id": run_id,
            "next_action": next_action,
            "ai_provider": analysis.get(
                "provider"
            ),
        },
    )

    return {
        "ok": True,
        "run_id": run_id,
        "radar": {
            "count": len(
                radar_videos
            ),
            "saved": saved_count,
        },
        "trending": {
            "count": len(
                trending_videos
            ),
        },
        "ai": analysis,
        "next_action": next_action,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "top_videos": sorted(
            radar_videos,
            key=score,
            reverse=True,
        )[:10],
    }


# ============================================================
# DIRECTOR HISTORY
# ============================================================

@app.get("/director/history")
async def director_history(
    limit: int = 20,
):
    limit = max(
        1,
        min(int(limit), 100),
    )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM director_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "language": row["language"],
            "region_code": row["region_code"],
            "data": json_loads_safe(
                row["data_json"],
                {},
            ),
        }
        for row in rows
    ]


# ============================================================
# DIRECTOR DECISION
# ============================================================

@app.post("/director/decision")
async def director_decision(
    decision: str,
    data: dict[str, Any] | None = None,
):
    allowed = {
        "approve",
        "discuss",
        "leave_as_is",
    }

    if decision not in allowed:
        return JSONResponse(
            status_code=400,
            content={
                "error": (
                    "decision must be one of: "
                    "approve, discuss, leave_as_is"
                )
            },
        )

    conn = get_db()

    cursor = conn.execute(
        """
        INSERT INTO decisions (
            created_at,
            decision,
            data_json
        )
        VALUES (?, ?, ?)
        """,
        (
            now_iso(),
            decision,
            json_dumps(data or {}),
        ),
    )

    decision_id = cursor.lastrowid

    conn.commit()
    conn.close()

    log_event(
        "director_decision",
        {
            "decision_id": decision_id,
            "decision": decision,
        },
    )

    return {
        "ok": True,
        "decision_id": decision_id,
        "decision": decision,
    }


# ============================================================
# EVENTS
# ============================================================

@app.get("/events")
async def events(
    limit: int = 100,
):
    limit = max(
        1,
        min(int(limit), 1000),
    )

    conn = get_db()

    rows = conn.execute(
        """
        SELECT *
        FROM system_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    conn.close()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "event_type": row["event_type"],
            "data": json_loads_safe(
                row["data_json"],
                {},
            ),
        }
        for row in rows
    ]


# ============================================================
# DIRECTOR TEST
# ============================================================

@app.get("/director/test")
async def director_test():
    return {
        "ok": True,
        "message": (
            "Director endpoint is available."
        ),
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "ai_enabled": AI_ENABLED,
        "ai_provider": (
            "gemini"
            if AI_ENABLED
            else "heuristic"
        ),
    }

import os
import json
import sqlite3
import math
from pathlib import Path
from datetime import datetime, timezone

import aiofiles
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from mcp.client.mcp_client import MCPClient


# ============================================================
# CONFIG
# ============================================================

APP_TITLE = "AI Full-Cycle YouTube System"

MCP_URL = os.environ.get(
    "MCP_URL",
    "https://youtube-mcp-u39z.onrender.com/mcp",
)

FREE_MODE = os.environ.get("FREE_MODE", "true").lower() == "true"
AUTONOMOUS = os.environ.get("AUTONOMOUS", "false").lower() == "true"

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "youtube.db"


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(title=APP_TITLE)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# TIME / DATABASE
# ============================================================

def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


def init_db():
    connection = db()

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS videos (
            video_id TEXT PRIMARY KEY,
            channel_id TEXT,
            title TEXT,
            channel_title TEXT,
            published_at TEXT,
            language TEXT,
            first_seen_at TEXT
        );

        CREATE TABLE IF NOT EXISTS video_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT NOT NULL,
            observed_at TEXT NOT NULL,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            age_hours REAL,
            views_per_hour REAL
        );

        CREATE INDEX IF NOT EXISTS idx_snap_video
        ON video_snapshots(video_id);

        CREATE INDEX IF NOT EXISTS idx_snap_time
        ON video_snapshots(observed_at);

        CREATE TABLE IF NOT EXISTS director_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            language TEXT,
            region_code TEXT,
            mode TEXT,
            status TEXT,
            hypothesis TEXT,
            reasoning TEXT,
            data_json TEXT
        );

        CREATE TABLE IF NOT EXISTS decisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            run_id INTEGER,
            decision_type TEXT,
            status TEXT,
            user_note TEXT
        );

        CREATE TABLE IF NOT EXISTS system_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            event_type TEXT,
            message TEXT,
            data_json TEXT
        );
        """
    )

    connection.commit()
    connection.close()


init_db()


# ============================================================
# MCP CLIENT
# ============================================================

async def mcp_call(name, arguments):
    """
    Call a tool on youtube-mcp.

    This function accepts both:
    - direct list results
    - dictionary/object results
    - MCP structured content
    - MCP text content containing JSON
    """

    try:
        client = MCPClient(MCP_URL)

        await client.initialize()

        result = await client.call_tool(
            name,
            arguments,
        )

        return parse_mcp_result(result)

    except Exception as exc:
        raise RuntimeError(
            f"MCP call failed: {name}: {exc}"
        ) from exc


def parse_mcp_result(result):
    """
    Convert MCP result into normal Python data.
    """

    if result is None:
        raise RuntimeError("MCP returned empty result")

    # Already a Python structure
    if isinstance(result, (dict, list)):
        return result

    # Objects containing content
    content = getattr(result, "content", None)

    if content is not None:
        for item in content:
            structured = getattr(item, "structuredContent", None)

            if structured is not None:
                return structured

            structured = getattr(item, "structured_content", None)

            if structured is not None:
                return structured

            text = getattr(item, "text", None)

            if text:
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    return text

    # Generic object
    structured = getattr(result, "structuredContent", None)

    if structured is not None:
        return structured

    structured = getattr(result, "structured_content", None)

    if structured is not None:
        return structured

    text = getattr(result, "text", None)

    if text:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    raise RuntimeError(
        f"Unsupported MCP response type: {type(result).__name__}"
    )


# ============================================================
# EVENTS
# ============================================================

def event(kind, message, data=None):
    connection = db()

    connection.execute(
        """
        INSERT INTO system_events(
            created_at,
            event_type,
            message,
            data_json
        )
        VALUES (?, ?, ?, ?)
        """,
        (
            now(),
            kind,
            message,
            json.dumps(
                data or {},
                ensure_ascii=False,
            ),
        ),
    )

    connection.commit()
    connection.close()


# ============================================================
# SNAPSHOTS
# ============================================================

def save_snapshot(videos, language):
    if not isinstance(videos, list):
        return {
            "saved_count": 0,
            "observed_at": now(),
        }

    timestamp = now()

    connection = db()
    saved = 0

    for video in videos:
        if not isinstance(video, dict):
            continue

        video_id = video.get("video_id")

        if not video_id:
            continue

        connection.execute(
            """
            INSERT OR IGNORE INTO videos(
                video_id,
                channel_id,
                title,
                channel_title,
                published_at,
                language,
                first_seen_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                video.get("channel_id"),
                video.get("title"),
                video.get("channel_title"),
                video.get("published_at"),
                language,
                timestamp,
            ),
        )

        connection.execute(
            """
            INSERT INTO video_snapshots(
                video_id,
                observed_at,
                views,
                likes,
                comments,
                age_hours,
                views_per_hour
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                timestamp,
                int(video.get("views") or 0),
                int(video.get("likes") or 0),
                int(video.get("comments") or 0),
                video.get("age_hours"),
                video.get("views_per_hour"),
            ),
        )

        saved += 1

    connection.commit()
    connection.close()

    return {
        "saved_count": saved,
        "observed_at": timestamp,
    }


# ============================================================
# DIRECTOR SCORING
# ============================================================

def score(video):
    views = float(video.get("views") or 0)
    speed = float(video.get("views_per_hour") or 0)
    likes = float(video.get("likes") or 0)
    comments = float(video.get("comments") or 0)

    engagement = 0

    if views > 0:
        engagement = (likes + comments * 3) / views

    return (
        math.log1p(speed) * 0.65
        + math.log1p(views) * 0.15
        + min(engagement * 1000, 20) * 0.20
    )


def make_hypothesis(videos, language, region):
    if not isinstance(videos, list):
        videos = []

    ranked = sorted(
        videos,
        key=score,
        reverse=True,
    )[:10]

    if not ranked:
        return {
            "hypothesis": "Недостаточно данных для гипотезы.",
            "reasoning": (
                "Радар не вернул подходящих видео."
            ),
            "top_videos": [],
        }

    names = [
        video.get("title", "")
        for video in ranked[:5]
    ]

    return {
        "hypothesis": (
            f"В сегменте {language} стоит проверить "
            "темы и форматы, представленные "
            "наиболее быстрорастущими видео."
        ),
        "reasoning": (
            f"Проанализировано {len(videos)} видео. "
            "Ранжирование учитывает скорость просмотров, "
            "общий объём просмотров и относительную "
            f"вовлечённость. Это гипотеза для эксперимента, "
            "а не прогноз успеха. Регион: {region}. "
            "Сильнейшие сигналы: "
            + "; ".join(names)
        ),
        "top_videos": [
            {
                **video,
                "director_score": round(
                    score(video),
                    4,
                ),
            }
            for video in ranked
        ],
    }


# ============================================================
# BASIC ROUTES
# ============================================================

@app.get("/")
async def home():
    index_file = BASE_DIR / "index.html"

    if not index_file.exists():
        return HTMLResponse(
            "<h1>AI Full-Cycle YouTube System</h1>"
            "<p>index.html not found</p>",
            status_code=200,
        )

    async with aiofiles.open(
        index_file,
        "r",
        encoding="utf-8",
    ) as file:
        html = await file.read()

    return HTMLResponse(html)


@app.get("/health")
def health():
    return {
        "status": "ok",
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "mcp_url": MCP_URL,
    }


@app.get("/system/status")
def system_status():
    return {
        "system": APP_TITLE,
        "phase": "free-working-model",
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "wallet_balance": 0,
        "paid_tools_enabled": False,
        "website_code_modification_by_ai": False,
        "youtube_channel_deletion_by_ai": False,
        "published_video_deletion_by_ai": False,
    }


# ============================================================
# YOUTUBE SEARCH
# ============================================================

@app.get("/search-channels")
async def search_channels(
    query: str,
    max_results: int = 20,
):
    try:
        result = await mcp_call(
            "search_channels",
            {
                "query": query,
                "max_results": min(
                    max(max_results, 1),
                    50,
                ),
            },
        )

        return result

    except Exception as exc:
        return JSONResponse(
            {
                "error": str(exc),
            },
            status_code=500,
        )


@app.get("/search-videos")
async def search_videos(
    query: str,
    max_results: int = 20,
    published_after: str | None = None,
    published_before: str | None = None,
    region_code: str | None = None,
    relevance_language: str | None = None,
    order: str = "viewCount",
):
    try:
        result = await mcp_call(
            "search_videos",
            {
                "query": query,
                "max_results": min(
                    max(max_results, 1),
                    50,
                ),
                "published_after": published_after,
                "published_before": published_before,
                "region_code": region_code,
                "relevance_language": relevance_language,
                "order": order,
            },
        )

        return result

    except Exception as exc:
        return JSONResponse(
            {
                "error": str(exc),
            },
            status_code=500,
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
                "max_results": min(
                    max(max_results, 1),
                    50,
                ),
                "region_code": region_code,
            },
        )

        return result

    except Exception as exc:
        return JSONResponse(
            {
                "error": str(exc),
            },
            status_code=500,
        )


# ============================================================
# GROWTH RADAR
# ============================================================

@app.get("/radar-videos")
async def radar_videos(
    max_results: int = 50,
    language: str = "ru",
    hours_back: int = 72,
):
    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "max_results": min(
                    max(max_results, 1),
                    50,
                ),
                "language": language,
                "hours_back": min(
                    max(hours_back, 1),
                    168,
                ),
            },
        )

        return result

    except Exception as exc:
        return JSONResponse(
            {
                "error": str(exc),
            },
            status_code=500,
        )


@app.post("/radar-save")
async def radar_save(payload: dict):
    videos = payload.get("videos", [])

    if not videos:
        return JSONResponse(
            {
                "error": "Нет видео для сохранения",
            },
            status_code=400,
        )

    result = save_snapshot(
        videos,
        payload.get("language", "unknown"),
    )

    event(
        "radar_saved",
        "Сохранено наблюдение радара",
        result,
    )

    return {
        "status": "ok",
        **result,
    }


# ============================================================
# RADAR HISTORY
# ============================================================

@app.get("/radar-history")
def radar_history(limit: int = 100):
    connection = db()

    rows = connection.execute(
        """
        SELECT
            v.video_id,
            v.title,
            v.channel_title,
            v.published_at,
            v.language,
            s.observed_at,
            s.views,
            s.likes,
            s.comments,
            s.age_hours,
            s.views_per_hour
        FROM video_snapshots s
        JOIN videos v
            ON v.video_id = s.video_id
        ORDER BY s.observed_at DESC
        LIMIT ?
        """,
        (
            min(max(limit, 1), 500),
        ),
    ).fetchall()

    connection.close()

    return {
        "count": len(rows),
        "snapshots": [
            dict(row)
            for row in rows
        ],
    }


# ============================================================
# DATABASE STATUS
# ============================================================

@app.get("/database-status")
def database_status():
    connection = db()

    result = {
        "status": "ok",
        "database": str(DB_PATH),
        "videos": connection.execute(
            "SELECT COUNT(*) FROM videos"
        ).fetchone()[0],
        "snapshots": connection.execute(
            "SELECT COUNT(*) FROM video_snapshots"
        ).fetchone()[0],
        "director_runs": connection.execute(
            "SELECT COUNT(*) FROM director_runs"
        ).fetchone()[0],
    }

    connection.close()

    return result


# ============================================================
# CHANNEL ANALYSIS
# ============================================================

@app.get("/analyze")
async def analyze(channel_id: str):
    try:
        return await mcp_call(
            "get_channel_stats",
            {
                "channel_id": channel_id,
            },
        )

    except Exception as exc:
        return JSONResponse(
            {
                "error": str(exc),
            },
            status_code=500,
        )


# ============================================================
# AI DIRECTOR
# ============================================================

@app.post("/director/run")
async def director_run(
    language: str = "ru",
    region_code: str = "RU",
    hours_back: int = 72,
    max_results: int = 50,
):
    try:
        radar_result = await mcp_call(
            "search_radar_videos",
            {
                "max_results": min(
                    max(max_results, 1),
                    50,
                ),
                "language": language,
                "hours_back": min(
                    max(hours_back, 1),
                    168,
                ),
            },
        )

        if isinstance(radar_result, list):
            radar_videos = radar_result
        elif isinstance(radar_result, dict):
            radar_videos = radar_result.get(
                "videos",
                [],
            )
        else:
            radar_videos = []

        save_snapshot(
            radar_videos,
            language,
        )

        trends_result = await mcp_call(
            "search_trending_videos",
            {
                "max_results": 25,
                "region_code": region_code,
            },
        )

        if isinstance(trends_result, list):
            trends = trends_result
        elif isinstance(trends_result, dict):
            trends = trends_result.get(
                "videos",
                [],
            )
        else:
            trends = []

        hypothesis = make_hypothesis(
            radar_videos,
            language,
            region_code,
        )

        connection = db()

        cursor = connection.execute(
            """
            INSERT INTO director_runs(
                created_at,
                language,
                region_code,
                mode,
                status,
                hypothesis,
                reasoning,
                data_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now(),
                language,
                region_code,
                "FREE_ONLY",
                "completed",
                hypothesis["hypothesis"],
                hypothesis["reasoning"],
                json.dumps(
                    {
                        "radar_count": len(
                            radar_videos
                        ),
                        "trends_count": len(
                            trends
                        ),
                        "top_videos": hypothesis[
                            "top_videos"
                        ],
                    },
                    ensure_ascii=False,
                ),
            ),
        )

        run_id = cursor.lastrowid

        connection.commit()
        connection.close()

        event(
            "director_run",
            "AI Director завершил аналитический цикл",
            {
                "run_id": run_id,
            },
        )

        return {
            "status": "completed",
            "run_id": run_id,
            "mode": "FREE_ONLY",
            "hypothesis": hypothesis[
                "hypothesis"
            ],
            "reasoning": hypothesis[
                "reasoning"
            ],
            "top_videos": hypothesis[
                "top_videos"
            ],
            "trends": trends[:10],
            "next_action": (
                "Ожидается решение пользователя"
                if not AUTONOMOUS
                else "Сформировать контент по гипотезе"
            ),
        }

    except Exception as exc:
        event(
            "director_error",
            str(exc),
        )

        return JSONResponse(
            {
                "status": "error",
                "error": str(exc),
            },
            status_code=500,
        )


# ============================================================
# DIRECTOR HISTORY
# ============================================================

@app.get("/director/history")
def director_history(limit: int = 20):
    connection = db()

    rows = connection.execute(
        """
        SELECT
            id,
            created_at,
            language,
            region_code,
            mode,
            status,
            hypothesis,
            reasoning
        FROM director_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            min(max(limit, 1), 100),
        ),
    ).fetchall()

    connection.close()

    return {
        "count": len(rows),
        "runs": [
            dict(row)
            for row in rows
        ],
    }


# ============================================================
# DIRECTOR DECISIONS
# ============================================================

@app.post("/director/decision")
def director_decision(payload: dict):
    decision = payload.get("decision")

    allowed = {
        "approve",
        "discuss",
        "leave_as_is",
    }

    if decision not in allowed:
        return JSONResponse(
            {
                "error": "Недопустимое решение",
            },
            status_code=400,
        )

    connection = db()

    connection.execute(
        """
        INSERT INTO decisions(
            created_at,
            run_id,
            decision_type,
            status,
            user_note
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            now(),
            payload.get("run_id"),
            decision,
            "accepted",
            payload.get("note"),
        ),
    )

    connection.commit()
    connection.close()

    event(
        "decision",
        "Пользователь принял решение",
        {
            "run_id": payload.get("run_id"),
            "decision": decision,
        },
    )

    return {
        "status": "ok",
        "run_id": payload.get("run_id"),
        "decision": decision,
    }


# ============================================================
# SYSTEM EVENTS
# ============================================================

@app.get("/events")
def events(limit: int = 50):
    connection = db()

    rows = connection.execute(
        """
        SELECT
            id,
            created_at,
            event_type,
            message,
            data_json
        FROM system_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (
            min(max(limit, 1), 200),
        ),
    ).fetchall()

    connection.close()

    return {
        "events": [
            dict(row)
            for row in rows
        ],
    }


# ============================================================
# LOCAL START
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                "10000",
            )
        ),
    )

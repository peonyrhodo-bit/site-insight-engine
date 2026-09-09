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

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ============================================================
# APP
# ============================================================

app = FastAPI(title="AI Full-Cycle YouTube System")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CONFIG
# ============================================================

MCP_URL = os.environ.get(
    "MCP_URL",
    "https://youtube-mcp-u39z.onrender.com/mcp",
)

FREE_MODE = os.environ.get("FREE_MODE", "true").lower() == "true"
AUTONOMOUS = os.environ.get("AUTONOMOUS", "false").lower() == "true"


# ============================================================
# DATABASE
# ============================================================

DATA_DIR = Path(
    os.environ.get(
        "DATA_DIR",
        str(Path(__file__).parent / "data")
    )
)

DATA_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH = DATA_DIR / "youtube.db"


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
        CREATE TABLE IF NOT EXISTS videos(
            video_id TEXT PRIMARY KEY,
            channel_id TEXT,
            title TEXT,
            channel_title TEXT,
            published_at TEXT,
            language TEXT,
            first_seen_at TEXT
        );

        CREATE TABLE IF NOT EXISTS video_snapshots(
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

        CREATE TABLE IF NOT EXISTS director_runs(
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

        CREATE TABLE IF NOT EXISTS decisions(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT,
            run_id INTEGER,
            decision_type TEXT,
            status TEXT,
            user_note TEXT
        );

        CREATE TABLE IF NOT EXISTS system_events(
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

async def mcp_call(name, args):
    """
    MCP 1.x client.

    Совместимо с youtube-mcp, который сейчас работает
    на mcp<2.
    """

    async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _):

        async with ClientSession(
            read_stream,
            write_stream,
        ) as session:

            await session.initialize()

            result = await session.call_tool(
                name,
                arguments=args,
            )

            if not result.content:
                raise RuntimeError(
                    "MCP вернул пустой ответ"
                )

            # Ищем текстовый JSON-ответ.
            for item in result.content:

                text = getattr(
                    item,
                    "text",
                    None,
                )

                if text is None:
                    continue

                try:
                    return json.loads(text)

                except json.JSONDecodeError:

                    # Иногда MCP может вернуть обычный текст.
                    return text

            raise RuntimeError(
                "MCP вернул ответ без распознаваемого текста"
            )


# ============================================================
# RESPONSE NORMALIZATION
# ============================================================

def extract_items(data):
    """
    Приводит разные варианты MCP-ответа к списку.

    Наш youtube-mcp сейчас возвращает обычные списки:
        [...]

    Но если позже MCP начнёт возвращать:
        {"videos": [...]}
    или
        {"items": [...]}

    сайт тоже продолжит работать.
    """

    if data is None:
        return []

    if isinstance(data, list):
        return data

    if isinstance(data, dict):

        for key in (
            "videos",
            "channels",
            "results",
            "items",
            "data",
        ):

            value = data.get(key)

            if isinstance(value, list):
                return value

    return []


def extract_object(data):
    """
    Приводит ответ с одним объектом к dict.
    """

    if data is None:
        return {}

    if isinstance(data, dict):
        return data

    if isinstance(data, list) and data:

        if isinstance(data[0], dict):
            return data[0]

    return {}


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

    observed_at = now()

    connection = db()

    saved_count = 0

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
                observed_at,
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
                observed_at,
                int(video.get("views") or 0),
                int(video.get("likes") or 0),
                int(video.get("comments") or 0),
                video.get("age_hours"),
                video.get("views_per_hour"),
            ),
        )

        saved_count += 1

    connection.commit()
    connection.close()

    return {
        "saved_count": saved_count,
        "observed_at": observed_at,
    }


# ============================================================
# DIRECTOR SCORE
# ============================================================

def score(video):

    views = float(
        video.get("views") or 0
    )

    speed = float(
        video.get("views_per_hour") or 0
    )

    likes = float(
        video.get("likes") or 0
    )

    comments = float(
        video.get("comments") or 0
    )

    engagement = (
        (likes + comments * 3) / views
        if views
        else 0
    )

    return (
        math.log1p(speed) * 0.65
        + math.log1p(views) * 0.15
        + min(engagement * 1000, 20) * 0.20
    )


def make_hypothesis(
    videos,
    language,
    region,
):

    ranked = sorted(
        videos,
        key=score,
        reverse=True,
    )[:10]

    if not ranked:

        return {
            "hypothesis": (
                "Недостаточно данных для гипотезы."
            ),
            "reasoning": (
                "Радар не вернул подходящих видео."
            ),
            "top_videos": [],
        }

    names = [
        video.get("title", "")
        for video in ranked[:5]
    ]

    hypothesis = (
        f"В сегменте {language} стоит проверить "
        "темы и форматы, представленные "
        "наиболее быстрорастущими видео."
    )

    reasoning = (
        f"Проанализировано {len(videos)} видео. "
        "Ранжирование учитывает скорость просмотров, "
        "общий объём просмотров и относительную "
        "вовлечённость. "
        "Это гипотеза для эксперимента, "
        "а не прогноз успеха. "
        f"Регион: {region}. "
        "Сильнейшие сигналы: "
        + "; ".join(names)
    )

    top_videos = []

    for video in ranked:

        item = dict(video)

        item["director_score"] = round(
            score(video),
            4,
        )

        top_videos.append(item)

    return {
        "hypothesis": hypothesis,
        "reasoning": reasoning,
        "top_videos": top_videos,
    }


# ============================================================
# HOME
# ============================================================

@app.get("/")
async def home():

    index_path = (
        Path(__file__).parent / "index.html"
    )

    async with aiofiles.open(
        index_path,
        "r",
        encoding="utf-8",
    ) as file:

        return HTMLResponse(
            await file.read()
        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():

    return {
        "status": "ok",
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "mcp_url": MCP_URL,
    }


# ============================================================
# SYSTEM STATUS
# ============================================================

@app.get("/system/status")
def status():

    return {
        "system": "AI Full-Cycle YouTube System",
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
# SEARCH CHANNELS
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

        return extract_items(result)

    except Exception as error:

        event(
            "search_channels_error",
            str(error),
        )

        return JSONResponse(
            {
                "error": str(error),
            },
            status_code=500,
        )


# ============================================================
# SEARCH VIDEOS
# ============================================================

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

        return extract_items(result)

    except Exception as error:

        event(
            "search_videos_error",
            str(error),
        )

        return JSONResponse(
            {
                "error": str(error),
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

        return extract_items(result)

    except Exception as error:

        event(
            "trending_error",
            str(error),
        )

        return JSONResponse(
            {
                "error": str(error),
            },
            status_code=500,
        )


# ============================================================
# RADAR
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

        return extract_items(result)

    except Exception as error:

        event(
            "radar_error",
            str(error),
        )

        return JSONResponse(
            {
                "error": str(error),
            },
            status_code=500,
        )

# ============================================================
# RADAR DEBUG
# ============================================================

@app.get("/radar-debug")
async def radar_debug(
    max_results: int = 10,
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

        return {
            "raw_type": type(result).__name__,
            "raw_result": result,
            "extracted_count": len(
                extract_items(result)
            ),
            "extracted_items": extract_items(result),
        }

    except Exception as error:

        event(
            "radar_debug_error",
            str(error),
        )

        return JSONResponse(
            {
                "error": str(error),
            },
            status_code=500,
        )

# ============================================================
# SAVE RADAR
# ============================================================

@app.post("/radar-save")
async def radar_save(payload: dict):

    videos = payload.get(
        "videos",
        [],
    )

    if not videos:

        return JSONResponse(
            {
                "error": "Нет видео для сохранения",
            },
            status_code=400,
        )

    result = save_snapshot(
        videos,
        payload.get(
            "language",
            "unknown",
        ),
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
def radar_history(
    limit: int = 100,
):

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
            min(
                max(limit, 1),
                500,
            ),
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

        "database": str(
            DB_PATH
        ),

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
async def analyze(
    channel_id: str,
):

    try:

        result = await mcp_call(
            "get_channel_stats",
            {
                "channel_id": channel_id,
            },
        )

        return extract_object(result)

    except Exception as error:

        event(
            "channel_analysis_error",
            str(error),
        )

        return JSONResponse(
            {
                "error": str(error),
            },
            status_code=500,
        )


# ============================================================
# DIRECTOR RUN
# ============================================================

@app.post("/director/run")
async def director_run(
    language: str = "ru",
    region_code: str = "RU",
    hours_back: int = 72,
    max_results: int = 50,
):

    try:

        # ----------------------------------------------------
        # 1. Growth Radar
        # ----------------------------------------------------

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

        videos = extract_items(
            radar_result
        )

        # ----------------------------------------------------
        # 2. Save observation
        # ----------------------------------------------------

        snapshot_result = save_snapshot(
            videos,
            language,
        )

        # ----------------------------------------------------
        # 3. Trending
        # ----------------------------------------------------

        trends_result = await mcp_call(
            "search_trending_videos",
            {
                "max_results": 25,
                "region_code": region_code,
            },
        )

        trends = extract_items(
            trends_result
        )

        # ----------------------------------------------------
        # 4. Hypothesis
        # ----------------------------------------------------

        hypothesis = make_hypothesis(
            videos,
            language,
            region_code,
        )

        # ----------------------------------------------------
        # 5. Save run
        # ----------------------------------------------------

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
                            videos
                        ),
                        "trends_count": len(
                            trends
                        ),
                        "snapshot": snapshot_result,
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

        # ----------------------------------------------------
        # 6. Event
        # ----------------------------------------------------

        event(
            "director_run",
            "AI Director завершил аналитический цикл",
            {
                "run_id": run_id,
                "radar_count": len(videos),
                "trends_count": len(trends),
            },
        )

        # ----------------------------------------------------
        # 7. Next action
        # ----------------------------------------------------

        if AUTONOMOUS:

            next_action = (
                "Сформировать контент по гипотезе"
            )

        else:

            next_action = (
                "Ожидается решение пользователя"
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

            "next_action": next_action,
        }

    except Exception as error:

        event(
            "director_error",
            str(error),
        )

        return JSONResponse(
            {
                "status": "error",
                "error": str(error),
            },
            status_code=500,
        )


# ============================================================
# DIRECTOR HISTORY
# ============================================================

@app.get("/director/history")
def director_history(
    limit: int = 20,
):

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
            min(
                max(limit, 1),
                100,
            ),
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
# DIRECTOR DECISION
# ============================================================

@app.post("/director/decision")
def director_decision(
    payload: dict,
):

    decision = payload.get(
        "decision"
    )

    allowed_decisions = {
        "approve",
        "discuss",
        "leave_as_is",
    }

    if decision not in allowed_decisions:

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
# EVENTS
# ============================================================

@app.get("/events")
def events(
    limit: int = 50,
):

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
            min(
                max(limit, 1),
                200,
            ),
        ),
    ).fetchall()

    connection.close()

    return {
        "events": [
            dict(row)
            for row in rows
        ]
    }

# ============================================================
# DIRECTOR TEST
# ============================================================

@app.get("/director/test")
async def director_test():
    return await director_run(
        language="ru",
        region_code="RU",
        hours_back=72,
        max_results=50,
    )

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

import os
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import aiofiles

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# MCP SERVER
# ============================================================

MCP_URL = (
    "https://youtube-mcp-u39z.onrender.com/mcp"
)


# ============================================================
# DATABASE
# ============================================================

# Пока храним SQLite в папке data.
# Позже эту папку можно будет подключить
# к persistent disk или заменить SQLite на Postgres.

DATA_DIR = (
    Path(__file__).parent
    / "data"
)

DATA_DIR.mkdir(
    parents=True,
    exist_ok=True,
)

DB_PATH = (
    DATA_DIR
    / "youtube.db"
)


# ============================================================
# DATABASE INITIALIZATION
# ============================================================

def init_database():

    connection = sqlite3.connect(
        DB_PATH
    )

    cursor = connection.cursor()


    # --------------------------------------------------------
    # VIDEOS
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS videos (

            video_id TEXT PRIMARY KEY,

            channel_id TEXT,

            title TEXT,

            channel_title TEXT,

            published_at TEXT,

            language TEXT,

            first_seen_at TEXT

        )
        """
    )


    # --------------------------------------------------------
    # VIDEO SNAPSHOTS
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS video_snapshots (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            video_id TEXT NOT NULL,

            observed_at TEXT NOT NULL,

            views INTEGER,

            likes INTEGER,

            comments INTEGER,

            age_hours REAL,

            views_per_hour REAL,

            FOREIGN KEY (
                video_id
            )
            REFERENCES videos (
                video_id
            )

        )
        """
    )


    # --------------------------------------------------------
    # INDEX
    # --------------------------------------------------------

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_video_snapshots_video_id
        ON video_snapshots(video_id)
        """
    )


    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS
        idx_video_snapshots_observed_at
        ON video_snapshots(observed_at)
        """
    )


    connection.commit()

    connection.close()


# Создаём БД при запуске сервера
init_database()


# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def save_radar_snapshot(
    videos: list,
    language: str,
):
    """
    Сохраняет текущий результат радара.

    Для каждого видео:
    1. создаём запись в videos, если её ещё нет;
    2. добавляем новый snapshot.
    """

    connection = sqlite3.connect(
        DB_PATH
    )

    cursor = connection.cursor()


    observed_at = (
        datetime.now(
            timezone.utc
        )
        .isoformat()
        .replace(
            "+00:00",
            "Z",
        )
    )


    saved_count = 0


    for video in videos:

        video_id = video.get(
            "video_id"
        )

        if not video_id:
            continue


        # ----------------------------------------------------
        # VIDEO
        # ----------------------------------------------------

        cursor.execute(
            """
            INSERT OR IGNORE INTO videos (
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

                video.get(
                    "channel_id"
                ),

                video.get(
                    "title"
                ),

                video.get(
                    "channel_title"
                ),

                video.get(
                    "published_at"
                ),

                language,

                observed_at,
            ),
        )


        # ----------------------------------------------------
        # SNAPSHOT
        # ----------------------------------------------------

        cursor.execute(
            """
            INSERT INTO video_snapshots (
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

                int(
                    video.get(
                        "views",
                        0,
                    ) or 0
                ),

                int(
                    video.get(
                        "likes",
                        0,
                    ) or 0
                ),

                int(
                    video.get(
                        "comments",
                        0,
                    ) or 0
                ),

                video.get(
                    "age_hours"
                ),

                video.get(
                    "views_per_hour"
                ),
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
# HOME PAGE
# ============================================================

@app.get("/")
async def home():

    html_path = (
        Path(__file__).parent
        / "index.html"
    )

    async with aiofiles.open(
        html_path,
        mode="r",
        encoding="utf-8",
    ) as f:

        html = await f.read()

    return HTMLResponse(
        html
    )


# ============================================================
# MCP CALL
# ============================================================

async def call_mcp_tool(
    tool_name: str,
    arguments: dict,
):

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
                tool_name,
                arguments,
            )

            if not result.content:

                raise RuntimeError(
                    "MCP вернул пустой ответ"
                )

            content = result.content[0]

            if not hasattr(
                content,
                "text",
            ):

                raise RuntimeError(
                    "MCP вернул контент "
                    "не текстового типа"
                )

            try:

                return json.loads(
                    content.text
                )

            except json.JSONDecodeError:

                raise RuntimeError(
                    "MCP вернул не JSON: "
                    + content.text
                )


# ============================================================
# SEARCH CHANNELS
# ============================================================

@app.get("/search-channels")
async def search_channels(
    query: str,
    max_results: int = 20,
):

    try:

        data = await call_mcp_tool(
            "search_channels",
            {
                "query": query,
                "max_results": max_results,
            },
        )

        return JSONResponse(
            data
        )

    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
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

        data = await call_mcp_tool(
            "search_videos",
            {
                "query": query,
                "max_results": max_results,
                "published_after": published_after,
                "published_before": published_before,
                "region_code": region_code,
                "relevance_language": relevance_language,
                "order": order,
            },
        )

        return JSONResponse(
            data
        )

    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
            },
            status_code=500,
        )


# ============================================================
# YOUTUBE TRENDS
# ============================================================

@app.get("/trending-videos")
async def trending_videos(
    max_results: int = 50,
    region_code: str = "US",
):

    try:

        data = await call_mcp_tool(
            "search_trending_videos",
            {
                "max_results": max_results,
                "region_code": region_code,
            },
        )

        return JSONResponse(
            data
        )

    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
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

        data = await call_mcp_tool(
            "search_radar_videos",
            {
                "max_results": max_results,
                "language": language,
                "hours_back": hours_back,
            },
        )

        return JSONResponse(
            data
        )

    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
            },
            status_code=500,
        )


# ============================================================
# SAVE RADAR SNAPSHOT
# ============================================================

@app.post("/radar-save")
async def radar_save(
    payload: dict,
):

    try:

        videos = payload.get(
            "videos",
            []
        )

        language = payload.get(
            "language",
            "unknown",
        )


        if not videos:

            return JSONResponse(
                {
                    "error":
                        "Нет видео для сохранения"
                },
                status_code=400,
            )


        result = save_radar_snapshot(
            videos=videos,
            language=language,
        )


        return JSONResponse(
            {
                "status": "ok",
                **result,
            }
        )


    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
            },
            status_code=500,
        )


# ============================================================
# DATABASE STATUS
# ============================================================

@app.get("/database-status")
async def database_status():

    try:

        connection = sqlite3.connect(
            DB_PATH
        )

        cursor = connection.cursor()


        cursor.execute(
            "SELECT COUNT(*) FROM videos"
        )

        videos_count = cursor.fetchone()[0]


        cursor.execute(
            "SELECT COUNT(*) FROM video_snapshots"
        )

        snapshots_count = (
            cursor.fetchone()[0]
        )


        connection.close()


        return {
            "status": "ok",
            "database": str(
                DB_PATH
            ),
            "videos": videos_count,
            "snapshots": snapshots_count,
        }


    except Exception as e:

        return JSONResponse(
            {
                "error": str(e)
            },
            status_code=500,
        )


# ============================================================
# CHANNEL ANALYSIS
# ============================================================

@app.get("/radar-history")
async def radar_history(limit: int = 100):
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row

        rows = conn.execute("""
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
            JOIN videos v ON v.video_id = s.video_id
            ORDER BY s.observed_at DESC
            LIMIT ?
        """, (limit,)).fetchall()

        conn.close()

        return {
            "count": len(rows),
            "snapshots": [dict(row) for row in rows]
        }

    except Exception as e:
        return {
            "error": str(e)
        }

@app.get("/analyze")
async def analyze(
    channel_id: str,
):

    try:

        data = await call_mcp_tool(
            "get_channel_stats",
            {
                "channel_id": channel_id,
            },
        )

        return JSONResponse(
            data
        )

    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
            },
            status_code=500,
        )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.environ.get(
            "PORT",
            "10000",
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )

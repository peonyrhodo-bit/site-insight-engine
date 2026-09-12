import json 
import logging
import math
import os
import sqlite3
import hashlib
import hmac
import secrets
import requests

from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any
from fastapi import FastAPI, Request
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from supabase import create_client, Client
from memory.memory import Memory
from memory.supabase import SupabaseMemoryBackend


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
# SITE AUTHENTICATION
# ============================================================

SITE_LOGIN = os.environ.get(
    "SITE_LOGIN",
    "",
).strip()

SITE_PASSWORD = os.environ.get(
    "SITE_PASSWORD",
    "",
).strip()

SITE_AUTH_SECRET = os.environ.get(
    "SITE_AUTH_SECRET",
    "",
).strip()

DIRECTOR_CRON_SECRET = os.environ.get(
    "DIRECTOR_CRON_SECRET",
    "",
).strip()

def make_auth_token() -> str:
    """
    Creates a signed authentication token.
    The actual password is never stored in the cookie.
    """

    payload = "site-insight-engine-auth"

    signature = hmac.new(
        SITE_AUTH_SECRET.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return signature


def is_authenticated(request: Request) -> bool:

    if not (
        SITE_LOGIN
        and SITE_PASSWORD
        and SITE_AUTH_SECRET
    ):
        return False

    cookie = request.cookies.get(
        "site_auth"
    )

    if not cookie:
        return False

    expected = make_auth_token()

    return hmac.compare_digest(
        cookie,
        expected,
    )


def auth_is_configured() -> bool:

    return bool(
        SITE_LOGIN
        and SITE_PASSWORD
        and SITE_AUTH_SECRET
    )
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

# ============================================================
# YOUTUBE / STORAGE RESOURCE LIMITS
# ============================================================

YOUTUBE_SEARCH_DAILY_LIMIT = int(
    os.environ.get(
        "YOUTUBE_SEARCH_DAILY_LIMIT",
        "100",
    )
)

YOUTUBE_OTHER_DAILY_QUOTA_UNITS = int(
    os.environ.get(
        "YOUTUBE_OTHER_DAILY_QUOTA_UNITS",
        "10000",
    )
)

YOUTUBE_SEARCH_RESERVE_RATIO = float(
    os.environ.get(
        "YOUTUBE_SEARCH_RESERVE_RATIO",
        "0.20",
    )
)

YOUTUBE_OTHER_RESERVE_RATIO = float(
    os.environ.get(
        "YOUTUBE_OTHER_RESERVE_RATIO",
        "0.20",
    )
)

SUPABASE_STORAGE_SOFT_LIMIT_BYTES = int(
    os.environ.get(
        "SUPABASE_STORAGE_SOFT_LIMIT_BYTES",
        str(450 * 1024 * 1024),
    )
)

SUPABASE_STORAGE_RESERVE_BYTES = int(
    os.environ.get(
        "SUPABASE_STORAGE_RESERVE_BYTES",
        str(50 * 1024 * 1024),
    )
)
# ============================================================
# OPENROUTER AI
# ============================================================

OPENROUTER_API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "",
).strip()

OPENROUTER_BASE_URL = os.environ.get(
    "OPENROUTER_BASE_URL",
    "https://openrouter.ai/api/v1",
).strip()

AI_MODEL = os.environ.get(
    "AI_MODEL",
    "openrouter/free",
).strip()

AI_ENABLED = (
    os.environ.get(
        "AI_ENABLED",
        "true",
    ).lower()
    == "true"
    and bool(OPENROUTER_API_KEY)
)


# ============================================================
# SUPABASE
# ============================================================

SUPABASE_URL = os.environ.get(
    "SUPABASE_URL",
    "",
).strip()

SUPABASE_KEY = os.environ.get(
    "SUPABASE_KEY",
    "",
).strip()

SUPABASE_ENABLED = bool(
    SUPABASE_URL and SUPABASE_KEY
)

supabase: Client | None = None


if SUPABASE_ENABLED:
    try:
        supabase = create_client(
            SUPABASE_URL,
            SUPABASE_KEY,
        )

        memory_backend = SupabaseMemoryBackend(
            client=supabase
        )

        memory = Memory(
            memory_backend
        )

        logger.info(
            "SUPABASE_INITIALIZED"
        )

    except Exception as exc:
        logger.error(
            "SUPABASE_INITIALIZATION_FAILED error_type=%s",
            type(exc).__name__,
        )

        supabase = None
        SUPABASE_ENABLED = False


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
# AUTHENTICATION MIDDLEWARE
# ============================================================

@app.middleware("http")
async def authentication_middleware(
    request: Request,
    call_next,
):
    path = request.url.path

    # Эти страницы доступны без авторизации
    public_paths = {
    "/login",
    "/health",
    "/director/cron",
}

    if path in public_paths:
        return await call_next(request)

    # Если авторизация не настроена в Render,
    # не блокируем сайт
    if not auth_is_configured():
        return await call_next(request)

    # Пользователь уже авторизован
    if is_authenticated(request):
        return await call_next(request)

    # При заходе на сайт отправляем на страницу входа,
    # а не показываем JSON 401
    if path == "/":
        return RedirectResponse(
            url="/login",
            status_code=303,
        )

    # Для API оставляем нормальный JSON 401
    return JSONResponse(
        status_code=401,
        content={
            "ok": False,
            "authenticated": False,
            "error": "Authentication required",
        },
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
    conn.execute("""
        CREATE TABLE IF NOT EXISTS youtube_quota_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            operation TEXT NOT NULL,
            search_calls INTEGER NOT NULL DEFAULT 0,
            other_units INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT
        )
    """)
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

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS weekly_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            created_at TEXT NOT NULL,
            summary TEXT,
            what_happened TEXT,
            what_worked TEXT,
            what_did_not_work TEXT,
            what_changed TEXT,
            recommendations TEXT,
            raw_context TEXT
        )
        """
    )

    quota_columns = {
        row["name"]
        for row in cursor.execute(
            "PRAGMA table_info(youtube_quota_usage)"
        ).fetchall()
    }

    if "units" in quota_columns and "search_calls" not in quota_columns:
        cursor.execute(
            "ALTER TABLE youtube_quota_usage "
            "RENAME TO youtube_quota_usage_legacy"
        )

        cursor.execute("""
            CREATE TABLE youtube_quota_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                operation TEXT NOT NULL,
                search_calls INTEGER NOT NULL DEFAULT 0,
                other_units INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT
            )
        """)

        cursor.execute("""
            INSERT INTO youtube_quota_usage (
                created_at,
                operation,
                search_calls,
                other_units,
                metadata_json
            )
            SELECT
                created_at,
                operation,
                0,
                units,
                metadata_json
            FROM youtube_quota_usage_legacy
        """)

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
# YOUTUBE QUOTA MANAGER
# ============================================================

def get_youtube_quota_status() -> dict[str, Any]:
    conn = get_db()

    try:
        row = conn.execute(
            """
            SELECT
                COALESCE(SUM(search_calls), 0) AS search_calls,
                COALESCE(SUM(other_units), 0) AS other_units
            FROM youtube_quota_usage
            WHERE created_at >= date('now')
            """
        ).fetchone()

        search_calls = int(
            row["search_calls"]
            if row and row["search_calls"] is not None
            else 0
        )

        other_units = int(
            row["other_units"]
            if row and row["other_units"] is not None
            else 0
        )

        search_limit = int(
            os.environ.get(
                "YOUTUBE_SEARCH_DAILY_LIMIT",
                "100",
            )
        )

        other_limit = int(
            os.environ.get(
                "YOUTUBE_OTHER_DAILY_QUOTA_UNITS",
                "10000",
            )
        )

        return {
            "search_calls": search_calls,
            "search_limit": search_limit,
            "search_remaining": max(
                search_limit - search_calls,
                0,
            ),
            "other_units": other_units,
            "other_limit": other_limit,
            "other_remaining": max(
                other_limit - other_units,
                0,
            ),
        }

    finally:
        conn.close()

def record_youtube_quota_usage(
    operation: str,
    search_calls: int = 0,
    other_units: int = 0,
    metadata: dict[str, Any] | None = None,
) -> None:

    search_calls = max(
        0,
        int(search_calls or 0),
    )

    other_units = max(
        0,
        int(other_units or 0),
    )

    if (
        search_calls == 0
        and other_units == 0
    ):
        return

    conn = get_db()

    try:
        conn.execute(
            """
            INSERT INTO youtube_quota_usage (
                created_at,
                operation,
                search_calls,
                other_units,
                metadata_json
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                now_iso(),
                operation,
                search_calls,
                other_units,
                json_dumps(
                    metadata or {}
                ),
            ),
        )

        conn.commit()

    finally:
        conn.close()

# ============================================================
# SUPABASE STORAGE STATUS
# ============================================================

def get_storage_status() -> dict[str, Any]:
    if not SUPABASE_ENABLED or supabase is None:
        return {
            "available": False,
            "videos": 0,
            "snapshots": 0,
            "estimated_bytes": 0,
            "limit_bytes": SUPABASE_STORAGE_SOFT_LIMIT_BYTES,
            "reserve_bytes": SUPABASE_STORAGE_RESERVE_BYTES,
            "remaining_bytes": 0,
        }

    try:
        videos_result = (
            supabase
            .table("videos")
            .select("video_id", count="exact", head=True)
            .execute()
        )

        snapshots_result = (
            supabase
            .table("video_snapshots")
            .select("id", count="exact", head=True)
            .execute()
        )

        videos_count = int(videos_result.count or 0)
        snapshots_count = int(snapshots_result.count or 0)

    except Exception as exc:
        logging.exception(
            "Failed to read Supabase storage counts: %s",
            exc,
        )

        return {
            "available": False,
            "videos": 0,
            "snapshots": 0,
            "estimated_bytes": 0,
            "limit_bytes": SUPABASE_STORAGE_SOFT_LIMIT_BYTES,
            "reserve_bytes": SUPABASE_STORAGE_RESERVE_BYTES,
            "remaining_bytes": 0,
            "error": str(exc),
        }

    # --------------------------------------------------------
    # Conservative estimate.
    # Supabase is the primary storage for video data.
    # --------------------------------------------------------

    estimated_bytes = (
        videos_count * 8_000
        + snapshots_count * 8_000
    )

    remaining = max(
        SUPABASE_STORAGE_SOFT_LIMIT_BYTES
        - SUPABASE_STORAGE_RESERVE_BYTES
        - estimated_bytes,
        0,
    )

    return {
        "available": True,
        "videos": videos_count,
        "snapshots": snapshots_count,
        "estimated_bytes": estimated_bytes,
        "limit_bytes": SUPABASE_STORAGE_SOFT_LIMIT_BYTES,
        "reserve_bytes": SUPABASE_STORAGE_RESERVE_BYTES,
        "remaining_bytes": remaining,
    }
def get_director_resource_status() -> dict[str, Any]:

    quota = get_youtube_quota_status()
    storage = get_storage_status()

    search_remaining = int(
        quota.get(
            "search_remaining",
            0,
        )
    )

    other_remaining = int(
        quota.get(
            "other_remaining",
            0,
        )
    )

    search_reserve = int(
        math.ceil(
            search_remaining
            * YOUTUBE_SEARCH_RESERVE_RATIO
        )
    )

    other_reserve = int(
        math.ceil(
            other_remaining
            * YOUTUBE_OTHER_RESERVE_RATIO
        )
    )

    searchable_calls = max(
        0,
        search_remaining
        - search_reserve,
    )

    usable_other_units = max(
        0,
        other_remaining
        - other_reserve,
    )

    return {
        "youtube_quota": {
            "search_remaining": search_remaining,
            "search_reserve": search_reserve,
            "search_available_for_research": (
                searchable_calls
            ),
            "other_remaining": other_remaining,
            "other_reserve": other_reserve,
            "other_available_for_research": (
                usable_other_units
            ),
        },
        "storage": storage,
    }

# ============================================================
# WEEKLY REPORTS
# ============================================================

def save_weekly_report(
    week_start: str,
    week_end: str,
    summary: str = "",
    what_happened: str = "",
    what_worked: str = "",
    what_did_not_work: str = "",
    what_changed: str = "",
    recommendations: str = "",
    raw_context: dict[str, Any] | None = None,
) -> int | None:

    if SUPABASE_ENABLED and supabase is not None:
        try:
            result = (
                supabase
                .table("weekly_reports")
                .upsert(
                    {
                        "week_start": week_start,
                        "week_end": week_end,
                        "created_at": now_iso(),
                        "summary": summary,
                        "what_happened": what_happened,
                        "what_worked": what_worked,
                        "what_did_not_work": what_did_not_work,
                        "what_changed": what_changed,
                        "recommendations": recommendations,
                        "raw_context": raw_context or {},
                    },
                    on_conflict="week_start,week_end",
                )
                .execute()
            )

            rows = result.data or []

            if rows:
                return rows[0].get("id")

        except Exception as exc:
            logger.error(
                "SUPABASE_SAVE_WEEKLY_REPORT_FAILED "
                "error_type=%s error=%s",
                type(exc).__name__,
                str(exc),
            )

    conn = get_db()

    try:
        cursor = conn.cursor()

        cursor.execute(
            """
            INSERT INTO weekly_reports (
                week_start,
                week_end,
                created_at,
                summary,
                what_happened,
                what_worked,
                what_did_not_work,
                what_changed,
                recommendations,
                raw_context
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                week_start,
                week_end,
                now_iso(),
                summary,
                what_happened,
                what_worked,
                what_did_not_work,
                what_changed,
                recommendations,
                json_dumps(raw_context or {}),
            ),
        )

        conn.commit()

        return cursor.lastrowid

    except Exception as exc:
        logger.error(
            "SAVE_WEEKLY_REPORT_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )
        return None

    finally:
        conn.close()


def get_weekly_reports(
    limit: int = 12,
) -> list[dict[str, Any]]:
    conn = get_db()

    try:
        rows = conn.execute(
            """
            SELECT *
            FROM weekly_reports
            ORDER BY week_end DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

        return [
            {
                "id": row["id"],
                "week_start": row["week_start"],
                "week_end": row["week_end"],
                "created_at": row["created_at"],
                "summary": row["summary"] or "",
                "what_happened": row["what_happened"] or "",
                "what_worked": row["what_worked"] or "",
                "what_did_not_work": (
                    row["what_did_not_work"] or ""
                ),
                "what_changed": row["what_changed"] or "",
                "recommendations": (
                    row["recommendations"] or ""
                ),
                "raw_context": json_loads_safe(
                    row["raw_context"],
                    {},
                ),
            }
            for row in rows
        ]

    finally:
        conn.close()


def get_weekly_report(
    report_id: int,
) -> dict[str, Any] | None:
    conn = get_db()

    try:
        row = conn.execute(
            """
            SELECT *
            FROM weekly_reports
            WHERE id = ?
            LIMIT 1
            """,
            (report_id,),
        ).fetchone()

        if row is None:
            return None

        return {
            "id": row["id"],
            "week_start": row["week_start"],
            "week_end": row["week_end"],
            "created_at": row["created_at"],
            "summary": row["summary"] or "",
            "what_happened": row["what_happened"] or "",
            "what_worked": row["what_worked"] or "",
            "what_did_not_work": (
                row["what_did_not_work"] or ""
            ),
            "what_changed": row["what_changed"] or "",
            "recommendations": (
                row["recommendations"] or ""
            ),
            "raw_context": json_loads_safe(
                row["raw_context"],
                {},
            ),
        }

    finally:
        conn.close()
def generate_weekly_report(
    week_start: str,
    week_end: str,
) -> dict[str, Any]:

    context = {
        "week_start": week_start,
        "week_end": week_end,
        "runs": [],
    }

    if SUPABASE_ENABLED and supabase is not None:
        try:
            result = (
                supabase
                .table("director_runs")
                .select("*")
                .gte("created_at", week_start)
                .lte(
                    "created_at",
                    f"{week_end}T23:59:59+00:00",
                )
                .order("id", desc=False)
                .limit(100)
                .execute()
            )

            rows = result.data or []

            for row in rows:
                data = row.get(
                    "data_json",
                    {},
                )

                if not isinstance(
                    data,
                    dict,
                ):
                    data = {}

                context["runs"].append(
                    {
                        "id": row.get("id"),
                        "created_at": row.get(
                            "created_at"
                        ),
                        "language": row.get(
                            "language"
                        ),
                        "region_code": row.get(
                            "region_code"
                        ),
                        "research_languages": data.get(
                            "research_languages",
                            [],
                        ),
                        "research_queries": data.get(
                            "research_queries",
                            [],
                        ),
                        "radar_count": data.get(
                            "radar_count",
                            0,
                        ),
                        "saved_count": data.get(
                            "saved_count",
                            0,
                        ),
                        "trending_count": data.get(
                            "trending_count",
                            0,
                        ),
                        "analysis": data.get(
                            "analysis",
                            {},
                        ),
                        "resource_plan": data.get(
                            "resource_plan",
                            {},
                        ),
                    }
                )

        except Exception as exc:
            logger.error(
                "WEEKLY_REPORT_CONTEXT_FAILED "
                "error_type=%s error=%s",
                type(exc).__name__,
                str(exc),
            )

    system_instruction = """
You are the Weekly Report analyst for an autonomous YouTube intelligence system.

Create a concise factual weekly report from the Director runs.

Return ONLY valid JSON with exactly these fields:

summary
what_happened
what_worked
what_did_not_work
what_changed
recommendations

Rules:
- Do not invent facts.
- Use only the supplied Director data.
- Mention meaningful topics, formats, signals and changes.
- Mention resource or quota issues when present.
- recommendations must be practical next steps for the Director.
- If there is not enough evidence for a conclusion, say so.
"""

    prompt = json_dumps(context)

    try:
        report = openrouter_generate_json(
            system_instruction=system_instruction,
            prompt=prompt,
        )
    except Exception as exc:
        logger.error(
            "WEEKLY_REPORT_AI_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        report = {
            "summary": (
                "Недостаточно данных для AI-отчёта."
            ),
            "what_happened": (
                f"За период {week_start} — "
                f"{week_end} выполнено "
                f"{len(context['runs'])} запусков Director."
            ),
            "what_worked": "",
            "what_did_not_work": "",
            "what_changed": "",
            "recommendations": (
                "Продолжить накопление данных "
                "для следующего отчёта."
            ),
        }

    report_id = save_weekly_report(
        week_start=week_start,
        week_end=week_end,
        summary=str(
            report.get(
                "summary",
                "",
            )
        ),
        what_happened=str(
            report.get(
                "what_happened",
                "",
            )
        ),
        what_worked=str(
            report.get(
                "what_worked",
                "",
            )
        ),
        what_did_not_work=str(
            report.get(
                "what_did_not_work",
                "",
            )
        ),
        what_changed=str(
            report.get(
                "what_changed",
                "",
            )
        ),
        recommendations=str(
            report.get(
                "recommendations",
                "",
            )
        ),
        raw_context=context,
    )

    return {
        "ok": True,
        "report_id": report_id,
        "week_start": week_start,
        "week_end": week_end,
        "report": report,
        "runs_count": len(
            context["runs"]
        ),
    }

# ============================================================
# SUPABASE MEMORY HELPERS
# ============================================================

def supabase_save_chat_message(
    role: str,
    message: str,
    data: dict[str, Any] | None = None,
    run_id: int | None = None,
) -> int | None:
    """
    Saves a Director chat message to Supabase.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:
        result = (
            supabase
            .table("chat_messages")
            .insert(
                {
                    "created_at": now_iso(),
                    "role": role,
                    "message": message,
                    "run_id": run_id,
                    "data_json": data or {},
                }
            )
            .execute()
        )

        rows = result.data or []

        if not rows:
            return None

        return rows[0].get("id")

    except Exception as exc:
        logger.error(
            "SUPABASE_SAVE_CHAT_MESSAGE_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None
def supabase_save_director_run(
    language: str,
    region_code: str,
    data: dict[str, Any],
) -> int | None:
    """
    Saves a Director run to Supabase.
    Returns the Supabase row ID.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:
        result = (
            supabase
            .table("director_runs")
            .insert(
                {
                    "created_at": now_iso(),
                    "language": language,
                    "region_code": region_code,
                    "data_json": data,
                }
            )
            .execute()
        )

        rows = result.data or []

        if not rows:
            return None

        return rows[0].get("id")

    except Exception as exc:
        logger.error(
            "SUPABASE_SAVE_DIRECTOR_RUN_FAILED error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None


def supabase_save_decision(
    decision: str,
    data: dict[str, Any],
    run_id: int | None = None,
) -> int | None:
    """
    Saves a user decision linked to a Director run.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:
        result = (
            supabase
            .table("decisions")
            .insert(
                {
                    "created_at": now_iso(),
                    "decision": decision,
                    "run_id": run_id,
                    "data_json": data,
                }
            )
            .execute()
        )

        rows = result.data or []

        if not rows:
            return None

        return rows[0].get("id")

    except Exception as exc:
        logger.error(
            "SUPABASE_SAVE_DECISION_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None

def supabase_save_action(
    description: str,
    action_type: str = "general",
    run_id: int | None = None,
    decision_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> int | None:
    """
    Creates a Director action.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:
        result = (
            supabase
            .table("director_actions")
            .insert(
                {
                    "created_at": now_iso(),
                    "run_id": run_id,
                    "decision_id": decision_id,
                    "action_type": action_type,
                    "description": description,
                    "status": "pending",
                    "data_json": data or {},
                }
            )
            .execute()
        )

        rows = result.data or []

        if not rows:
            return None

        return rows[0].get("id")

    except Exception as exc:
        logger.error(
            "SUPABASE_SAVE_ACTION_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None


def supabase_save_result(
    action_id: int,
    summary: str,
    result_type: str = "completed",
    run_id: int | None = None,
    data: dict[str, Any] | None = None,
) -> int | None:
    """
    Saves an action result and marks the action completed.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:

        # Get run_id from action when it was not supplied.
        if run_id is None:
            action_result = (
                supabase
                .table("director_actions")
                .select("run_id")
                .eq("id", action_id)
                .limit(1)
                .execute()
            )

            action_rows = (
                action_result.data or []
            )

            if action_rows:
                run_id = action_rows[0].get(
                    "run_id"
                )

        result = (
            supabase
            .table("director_results")
            .insert(
                {
                    "created_at": now_iso(),
                    "action_id": action_id,
                    "run_id": run_id,
                    "result_type": result_type,
                    "summary": summary,
                    "data_json": data or {},
                }
            )
            .execute()
        )

        rows = result.data or []

        if not rows:
            return None

        result_id = rows[0].get("id")

        # Mark action as completed.
        supabase.table(
            "director_actions"
        ).update(
            {
                "status": "completed",
                "completed_at": now_iso(),
            }
        ).eq(
            "id",
            action_id,
        ).execute()

        return result_id

    except Exception as exc:
        logger.error(
            "SUPABASE_SAVE_RESULT_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None

def supabase_save_event(
    event_type: str,
    data: dict[str, Any],
) -> int | None:
    """
    Saves a system event to Supabase.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:
        result = (
            supabase
            .table("system_events")
            .insert(
                {
                    "created_at": now_iso(),
                    "event_type": event_type,
                    "data_json": data,
                }
            )
            .execute()
        )

        rows = result.data or []

        if not rows:
            return None

        return rows[0].get("id")

    except Exception as exc:
        logger.error(
            "SUPABASE_SAVE_EVENT_FAILED error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None


def supabase_get_director_context(
    limit_runs: int = 10,
    limit_decisions: int = 20,
    limit_events: int = 30,
    limit_chat: int = 20,
    limit_actions: int = 20,
    limit_results: int = 20,
) -> dict[str, Any] | None:
    """
    Reads the complete Director memory from Supabase.
    """

    if not SUPABASE_ENABLED or supabase is None:
        return None

    try:

        runs_result = (
            supabase
            .table("director_runs")
            .select("*")
            .order("id", desc=True)
            .limit(limit_runs)
            .execute()
        )

        decisions_result = (
            supabase
            .table("decisions")
            .select("*")
            .order("id", desc=True)
            .limit(limit_decisions)
            .execute()
        )

        events_result = (
            supabase
            .table("system_events")
            .select("*")
            .order("id", desc=True)
            .limit(limit_events)
            .execute()
        )

        chat_result = (
            supabase
            .table("chat_messages")
            .select("*")
            .order("id", desc=True)
            .limit(limit_chat)
            .execute()
        )

        actions_result = (
            supabase
            .table("director_actions")
            .select("*")
            .order("id", desc=True)
            .limit(limit_actions)
            .execute()
        )

        results_result = (
            supabase
            .table("director_results")
            .select("*")
            .order("id", desc=True)
            .limit(limit_results)
            .execute()
        )

        runs = runs_result.data or []
        decisions = decisions_result.data or []
        events = events_result.data or []
        chat_messages = chat_result.data or []
        actions = actions_result.data or []
        results = results_result.data or []

        return {
            "recent_runs": [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "language": row.get("language"),
                    "region_code": row.get("region_code"),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in runs
            ],

            "recent_decisions": [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "run_id": row.get("run_id"),
                    "decision": row.get("decision"),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in decisions
            ],

            "recent_actions": [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "run_id": row.get("run_id"),
                    "decision_id": row.get("decision_id"),
                    "action_type": row.get("action_type"),
                    "description": row.get("description"),
                    "status": row.get("status"),
                    "completed_at": row.get("completed_at"),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in actions
            ],

            "recent_results": [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "action_id": row.get("action_id"),
                    "run_id": row.get("run_id"),
                    "result_type": row.get("result_type"),
                    "summary": row.get("summary"),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in results
            ],

            "recent_chat_messages": [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "run_id": row.get("run_id"),
                    "role": row.get("role"),
                    "message": row.get("message"),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in reversed(chat_messages)
            ],

            "recent_events": [
                {
                    "id": row.get("id"),
                    "created_at": row.get("created_at"),
                    "event_type": row.get("event_type"),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in events
            ],
        }

    except Exception as exc:
        logger.error(
            "SUPABASE_GET_DIRECTOR_CONTEXT_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return None
  

# ============================================================
# EVENTS
# ============================================================

def get_recent_system_context(
    limit_runs: int = 10,
    limit_decisions: int = 20,
    limit_events: int = 30,
) -> dict[str, Any]:

    # --------------------------------------------------------
    # PRIMARY MEMORY: SUPABASE
    # --------------------------------------------------------

    supabase_context = supabase_get_director_context(
    limit_runs=limit_runs,
    limit_decisions=limit_decisions,
    limit_events=limit_events,
    limit_chat=20,
    limit_actions=20,
    limit_results=20,
)

    if supabase_context is not None:
        supabase_context["system"] = {
            "free_mode": FREE_MODE,
            "autonomous": AUTONOMOUS,
            "ai_enabled": AI_ENABLED,
            "ai_provider": (
                "openrouter"
                if AI_ENABLED
                else "heuristic"
            ),
            "ai_model": AI_MODEL,
            "memory_provider": "supabase",
        }

        return supabase_context

    # --------------------------------------------------------
    # FALLBACK MEMORY: SQLITE
    # --------------------------------------------------------

    logger.warning(
        "DIRECTOR_MEMORY_FALLBACK_TO_SQLITE"
    )

    conn = get_db()

    runs = conn.execute(
        """
        SELECT *
        FROM director_runs
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit_runs,),
    ).fetchall()

    decisions = conn.execute(
        """
        SELECT *
        FROM decisions
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit_decisions,),
    ).fetchall()

    events = conn.execute(
        """
        SELECT *
        FROM system_events
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit_events,),
    ).fetchall()

    conn.close()

    return {
        "recent_runs": [
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
            for row in runs
        ],
        "recent_decisions": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "decision": row["decision"],
                "data": json_loads_safe(
                    row["data_json"],
                    {},
                ),
            }
            for row in decisions
        ],
        "recent_events": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "event_type": row["event_type"],
                "data": json_loads_safe(
                    row["data_json"],
                    {},
                ),
            }
            for row in events
        ],
        "system": {
            "free_mode": FREE_MODE,
            "autonomous": AUTONOMOUS,
            "ai_enabled": AI_ENABLED,
            "ai_provider": (
                "openrouter"
                if AI_ENABLED
                else "heuristic"
            ),
            "ai_model": AI_MODEL,
            "memory_provider": "sqlite",
        },
    }


def log_event(
    event_type: str,
    data: dict[str, Any] | None = None,
) -> None:

    event_data = data or {}

    # --------------------------------------------------------
    # PRIMARY STORAGE: SUPABASE
    # --------------------------------------------------------

    if SUPABASE_ENABLED and supabase is not None:

        event_id = supabase_save_event(
            event_type=event_type,
            data=event_data,
        )

        if event_id is not None:
            return

    # --------------------------------------------------------
    # FALLBACK STORAGE: SQLITE
    # --------------------------------------------------------

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
            json_dumps(event_data),
        ),
    )

    conn.commit()
    conn.close()
    

# ============================================================
# MCP
# ============================================================

def exception_details(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        parts: list[str] = []

        for child in exc.exceptions:
            detail = exception_details(child)

            if detail:
                parts.append(detail)

        if parts:
            return " | ".join(parts)

        return str(exc)

    message = str(exc).strip()

    if message:
        return f"{type(exc).__name__}: {message}"

    return type(exc).__name__


async def mcp_call(
    name: str,
    args: dict[str, Any],
) -> Any:

    logger.info(
        "MCP_CALL_START tool=%s url=%s",
        name,
        MCP_URL,
    )

    try:
        async with streamable_http_client(
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

                logger.info(
                    "MCP_INITIALIZED tool=%s",
                    name,
                )

                result = await session.call_tool(
                    name,
                    arguments=args,
                )

                logger.info(
                    "MCP_CALL_SUCCESS tool=%s",
                    name,
                )

                return result

    except Exception as exc:
        detail = exception_details(exc)

        logger.error(
            "MCP_CALL_FAILED tool=%s error=%s",
            name,
            detail,
        )

        log_event(
            "mcp_call_failed",
            {
                "tool": name,
                "error_type": type(exc).__name__,
                "error": detail[:1000],
            },
        )

        raise RuntimeError(
            f"MCP call failed for '{name}': {detail}"
        ) from exc


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
        items = structured.get("items")

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
                    items = parsed.get("items")

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
    """
    Save YouTube video observations to Supabase.

    Existing videos are updated in `videos`.
    Every observation is preserved in `video_snapshots`.
    """

    if not SUPABASE_ENABLED or supabase is None:
        raise RuntimeError(
            "Supabase is not configured"
        )

    if not videos:
        return 0

    created_at = now_iso()

    normalized_by_id: dict[
        str,
        dict[str, Any],
    ] = {}

    for video in videos:
        video_id = (
            video.get("video_id")
            or video.get("id")
        )

        if isinstance(video_id, dict):
            video_id = video_id.get(
                "videoId"
            )

        if not video_id:
            continue

        normalized_by_id[
            str(video_id)
        ] = {
            "video_id": str(video_id),
            "video": video,
        }

    normalized = list(
        normalized_by_id.values()
    )

    if not normalized:
        return 0

    video_ids = [
        item["video_id"]
        for item in normalized
    ]

    existing_result = (
        supabase
        .table("videos")
        .select(
            "video_id,first_seen"
        )
        .in_(
            "video_id",
            video_ids,
        )
        .execute()
    )

    existing_rows = (
        existing_result.data or []
    )

    first_seen_by_id = {
        str(row.get("video_id")): (
            row.get("first_seen")
            or created_at
        )
        for row in existing_rows
    }

    video_rows = []

    snapshot_rows = []

    for item in normalized:
        video_id = item["video_id"]
        video = item["video"]

        first_seen = (
            first_seen_by_id.get(
                video_id
            )
            or created_at
        )

        video_rows.append(
            {
                "video_id": video_id,
                "data_json": video,
                "first_seen": first_seen,
                "last_seen": created_at,
            }
        )

        snapshot_rows.append(
            {
                "created_at": created_at,
                "video_id": video_id,
                "data_json": video,
            }
        )

    supabase.table(
        "videos"
    ).upsert(
        video_rows,
        on_conflict="video_id",
    ).execute()

    supabase.table(
        "video_snapshots"
    ).insert(
        snapshot_rows
    ).execute()

    return len(
        snapshot_rows
    )

# ============================================================
# NORMALIZED VIDEO METRICS
# ============================================================

def get_video_title(
    video: dict[str, Any],
) -> str:
    snippet = video.get(
        "snippet",
        {},
    )

    if isinstance(snippet, dict):
        title = snippet.get(
            "title",
            "",
        )

        if title:
            return str(title)

    return str(
        video.get(
            "title",
            "",
        )
    )


def get_video_views(
    video: dict[str, Any],
) -> int:
    statistics = video.get(
        "statistics",
        {},
    )

    if isinstance(statistics, dict):
        value = statistics.get(
            "viewCount",
            0,
        )
    else:
        value = video.get(
            "views",
            video.get(
                "viewCount",
                0,
            ),
        )

    try:
        return int(value or 0)
    except Exception:
        return 0


def get_video_likes(
    video: dict[str, Any],
) -> int:
    statistics = video.get(
        "statistics",
        {},
    )

    if isinstance(statistics, dict):
        value = statistics.get(
            "likeCount",
            0,
        )
    else:
        value = video.get(
            "likes",
            video.get(
                "likeCount",
                0,
            ),
        )

    try:
        return int(value or 0)
    except Exception:
        return 0


def get_video_comments(
    video: dict[str, Any],
) -> int:
    statistics = video.get(
        "statistics",
        {},
    )

    if isinstance(statistics, dict):
        value = statistics.get(
            "commentCount",
            0,
        )
    else:
        value = video.get(
            "comments",
            video.get(
                "commentCount",
                0,
            ),
        )

    try:
        return int(value or 0)
    except Exception:
        return 0


# ============================================================
# HEURISTIC ANALYSIS
# ============================================================

def score(
    video: dict[str, Any],
) -> float:
    views = float(
        get_video_views(video)
    )

    likes = float(
        get_video_likes(video)
    )

    comments = float(
        get_video_comments(video)
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
        title = get_video_title(video)

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
# OPENROUTER AI
# ============================================================

def openrouter_error_message(
    response: requests.Response,
) -> str:

    try:
        data = response.json()

        error = data.get(
            "error",
            {},
        )

        if isinstance(error, dict):
            message = error.get(
                "message",
                "",
            )

            if message:
                return str(message)[:500]

    except Exception:
        pass

    return (
        f"HTTP {response.status_code}"
    )


def extract_json_from_text(
    text: str,
) -> dict[str, Any]:

    cleaned = text.strip()

    try:
        parsed = json.loads(cleaned)

        if isinstance(parsed, dict):
            return parsed

    except json.JSONDecodeError:
        pass

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(
            lines
        ).strip()

        try:
            parsed = json.loads(cleaned)

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")

    if start >= 0 and end > start:
        candidate = cleaned[
            start:end + 1
        ]

        try:
            parsed = json.loads(
                candidate
            )

            if isinstance(parsed, dict):
                return parsed

        except json.JSONDecodeError:
            pass

    raise RuntimeError(
        "OpenRouter returned non-JSON content"
    )

DIRECTOR_LANGUAGE_RULE = """
Язык общения с пользователем — русский.

Все сформированные тобой выводы, рекомендации, гипотезы,
предположения, объяснения, аналитические выводы, предложения,
решения и отчёты, предназначенные для пользователя, должны
быть написаны на русском языке.

Язык исследуемых материалов не должен менять язык общения
с пользователем. Исследовать YouTube и другие источники можно
на любом языке.

Не переводи и не изменяй оригинальные названия видео,
названия каналов, имена собственные, названия компаний,
брендов, продуктов, сервисов и другие оригинальные
идентификаторы исследуемых материалов.

Оригинальные названия и другие данные источников сохраняй
в их исходном виде. На русский переводятся только твои
собственные выводы, рекомендации, объяснения, гипотезы,
предположения и отчёты для пользователя.
""".strip()

def openrouter_generate_json(
    system_instruction: str,
    prompt: str,
) -> dict[str, Any]:
    system_instruction = (
        DIRECTOR_LANGUAGE_RULE
        + "\n\n"
        + system_instruction
    )

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured"
        )

    url = (
        OPENROUTER_BASE_URL.rstrip("/")
        + "/chat/completions"
    )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": AI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_instruction,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.2,
        "response_format": {
            "type": "json_object",
        },
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=90,
        )

    except requests.RequestException as exc:
        logger.error(
            "AI_REQUEST_ERROR provider=openrouter error_type=%s",
            type(exc).__name__,
        )

        raise RuntimeError(
            "OpenRouter request failed"
        ) from exc

    if not response.ok:
        safe_message = openrouter_error_message(
            response
        )

        logger.error(
            "AI_API_ERROR provider=openrouter status=%s message=%s",
            response.status_code,
            safe_message,
        )

        raise RuntimeError(
            f"OpenRouter API error: {safe_message}"
        )

    try:
        data = response.json()

    except ValueError as exc:
        logger.error(
            "AI_INVALID_JSON_RESPONSE provider=openrouter"
        )

        raise RuntimeError(
            "OpenRouter returned invalid JSON"
        ) from exc

    choices = data.get(
        "choices",
        [],
    )

    if not choices:
        raise RuntimeError(
            "OpenRouter returned no choices"
        )

    message = choices[0].get(
        "message",
        {},
    )

    if not isinstance(
        message,
        dict,
    ):
        raise RuntimeError(
            "OpenRouter returned invalid message"
        )

    content = message.get(
        "content",
        "",
    )

    if isinstance(content, list):
        text_parts = []

        for item in content:
            if isinstance(item, dict):
                text = item.get(
                    "text"
                )

                if text:
                    text_parts.append(
                        str(text)
                    )

        content = "\n".join(
            text_parts
        )

    text = str(
        content or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "OpenRouter returned empty content"
        )

    return extract_json_from_text(
        text
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
        snippet = video.get(
            "snippet",
            {},
        )

        radar = video.get(
            "_radar",
            {},
        )

        if not isinstance(
            snippet,
            dict,
        ):
            snippet = {}

        if not isinstance(
            radar,
            dict,
        ):
            radar = {}

        compact_videos.append(
            {
                "title": get_video_title(
                    video
                ),
                "channel": snippet.get(
                    "channelTitle",
                    video.get(
                        "channel_title",
                        "",
                    ),
                ),
                "views": get_video_views(
                    video
                ),
                "likes": get_video_likes(
                    video
                ),
                "comments": get_video_comments(
                    video
                ),
                "published_at": snippet.get(
                    "publishedAt",
                    video.get(
                        "published_at",
                        "",
                    ),
                ),
                "language": language,
                "query": radar.get(
                    "query",
                    video.get(
                        "query",
                        "",
                    ),
                ),
                "age_hours": radar.get(
                    "age_hours"
                ),
                "views_per_hour": radar.get(
                    "views_per_hour"
                ),
                "engagement": radar.get(
                    "engagement"
                ),
            }
        )

    compact_trends = []

    for video in ranked_trends:
        snippet = video.get(
            "snippet",
            {},
        )

        if not isinstance(
            snippet,
            dict,
        ):
            snippet = {}

        compact_trends.append(
            {
                "title": get_video_title(
                    video
                ),
                "channel": snippet.get(
                    "channelTitle",
                    video.get(
                        "channel_title",
                        "",
                    ),
                ),
                "views": get_video_views(
                    video
                ),
                "likes": get_video_likes(
                    video
                ),
                "comments": get_video_comments(
                    video
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
4. Treat views, likes, comments, views-per-hour and other metrics as signals.
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
14. Distinguish current popularity from signs of acceleration.
15. Do not use raw view count as the only criterion.
16. Do not treat one successful channel as proof that a topic will work
    for another channel.
17. Suggest experiments when evidence is promising but insufficient.

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

    result = openrouter_generate_json(
        system_instruction=system_instruction,
        prompt=prompt,
    )

    try:
        confidence = float(
            result.get(
                "confidence",
                0.0,
            )
            or 0.0
        )
    except Exception:
        confidence = 0.0

    confidence = max(
        0.0,
        min(
            confidence,
            1.0,
        ),
    )

    topics = result.get(
        "topics",
        [],
    )

    formats = result.get(
        "formats",
        [],
    )

    experiments = result.get(
        "experiments",
        [],
    )

    if not isinstance(
        topics,
        list,
    ):
        topics = []

    if not isinstance(
        formats,
        list,
    ):
        formats = []

    if not isinstance(
        experiments,
        list,
    ):
        experiments = []

    return {
        "provider": "openrouter",
        "model": AI_MODEL,
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
        "topics": topics[:10],
        "formats": formats[:10],
        "experiments": experiments[:10],
        "confidence": confidence,
    }

def generate_weekly_report(
    week_start: str,
    week_end: str,
) -> dict[str, Any]:

    runs: list[dict[str, Any]] = []

    if SUPABASE_ENABLED and supabase is not None:
        try:
            result = (
                supabase
                .table("director_runs")
                .select("*")
                .gte(
                    "created_at",
                    f"{week_start}T00:00:00+00:00",
                )
                .lte(
                    "created_at",
                    f"{week_end}T23:59:59+00:00",
                )
                .order(
                    "created_at",
                    desc=False,
                )
                .execute()
            )

            runs = result.data or []

        except Exception as exc:
            logger.error(
                "WEEKLY_REPORT_LOAD_RUNS_FAILED "
                "error_type=%s error=%s",
                type(exc).__name__,
                str(exc),
            )

    compact_runs: list[dict[str, Any]] = []

    for run in runs:
        run_data = run.get("run_data") or {}

        compact_runs.append(
            {
                "id": run.get("id"),
                "created_at": run.get(
                    "created_at"
                ),
                "research_languages": (
                    run_data.get(
                        "research_languages"
                    )
                ),
                "research_queries": (
                    run_data.get(
                        "research_queries"
                    )
                ),
                "radar_count": (
                    run_data.get(
                        "radar",
                        {},
                    ).get(
                        "count"
                    )
                ),
                "saved_count": (
                    run_data.get(
                        "radar",
                        {},
                    ).get(
                        "saved"
                    )
                ),
                "trending_count": (
                    run_data.get(
                        "trending",
                        {},
                    ).get(
                        "count"
                    )
                ),
                "analysis": run_data.get(
                    "ai"
                ),
                "resource_plan": run_data.get(
                    "resource_plan"
                ),
            }
        )

    system_prompt = """
You are the Weekly Report analyst for an autonomous YouTube intelligence system.

Create a concise, factual weekly report from the Director run data.

Do not invent facts.
Do not claim that a trend exists unless the supplied data supports it.
Focus on:
- what the Director researched,
- what was found,
- what worked,
- what did not work,
- what changed during the week,
- resource usage or constraints,
- useful recommendations for the next week.

Return ONLY valid JSON with exactly these keys:

summary
what_happened
what_worked
what_did_not_work
what_changed
recommendations
""".strip()

    user_prompt = json_dumps(
        {
            "week_start": week_start,
            "week_end": week_end,
            "director_runs": compact_runs,
        }
    )

    report: dict[str, Any] | None = None

    try:
        generated = openrouter_generate_json(
            system_prompt,
            user_prompt,
        )

        if isinstance(generated, dict):
            report = generated

    except Exception as exc:
        logger.error(
            "WEEKLY_REPORT_AI_FAILED "
            "error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

    if report is None:
        report = {
            "summary": (
                f"За период {week_start} — {week_end} "
                f"Director выполнил {len(compact_runs)} запусков."
            ),
            "what_happened": (
                f"Выполнено запусков Director: "
                f"{len(compact_runs)}."
            ),
            "what_worked": (
                "Данные запусков Director были "
                "собраны для недельного анализа."
            ),
            "what_did_not_work": (
                "Автоматический AI-анализ недельных "
                "данных недоступен."
            ),
            "what_changed": (
                "Изменения определены только на основе "
                "доступных запусков Director."
            ),
            "recommendations": (
                "Продолжить регулярные запуски Director "
                "и сравнивать результаты между неделями."
            ),
        }

    report_id = save_weekly_report(
        week_start=week_start,
        week_end=week_end,
        summary=str(
            report.get(
                "summary",
                "",
            )
        ),
        what_happened=str(
            report.get(
                "what_happened",
                "",
            )
        ),
        what_worked=str(
            report.get(
                "what_worked",
                "",
            )
        ),
        what_did_not_work=str(
            report.get(
                "what_did_not_work",
                "",
            )
        ),
        what_changed=str(
            report.get(
                "what_changed",
                "",
            )
        ),
        recommendations=str(
            report.get(
                "recommendations",
                "",
            )
        ),
        raw_context={
            "week_start": week_start,
            "week_end": week_end,
            "director_runs": compact_runs,
        },
    )

    return {
        "ok": True,
        "report_id": report_id,
        "week_start": week_start,
        "week_end": week_end,
        "runs_count": len(compact_runs),
        "report": report,
    }


def make_hypothesis(
    videos: list[dict[str, Any]],
    language: str,
    region_code: str,
    trends: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:

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
                "provider": "openrouter",
                "model": AI_MODEL,
            },
        )

        return result

    except Exception as exc:
        logger.error(
            "AI_ANALYSIS_FAILED provider=openrouter error_type=%s",
            type(exc).__name__,
        )

        log_event(
            "ai_analysis_failed",
            {
                "provider": "openrouter",
                "error_type": type(exc).__name__,
            },
        )

        fallback = make_heuristic_hypothesis(
            videos
        )

        fallback["ai_fallback_reason"] = (
            "OpenRouter analysis was unavailable; "
            "local heuristic used."
        )

        return fallback


def openrouter_generate_text(
    system_instruction: str,
    prompt: str,
) -> str:
    system_instruction = (
        DIRECTOR_LANGUAGE_RULE
        + "\n\n"
        + system_instruction
    )

    if not OPENROUTER_API_KEY:
        raise RuntimeError(
            "OPENROUTER_API_KEY is not configured"
        )

    url = (
        OPENROUTER_BASE_URL.rstrip("/")
        + "/chat/completions"
    )

    headers = {
        "Authorization": (
            f"Bearer {OPENROUTER_API_KEY}"
        ),
        "Content-Type": "application/json",
    }

    payload = {
        "model": AI_MODEL,
        "messages": [
            {
                "role": "system",
                "content": system_instruction,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
        "temperature": 0.3,
    }

    try:
        response = requests.post(
            url,
            headers=headers,
            json=payload,
            timeout=90,
        )

    except requests.RequestException as exc:
        logger.error(
            "AI_CHAT_REQUEST_ERROR provider=openrouter error_type=%s",
            type(exc).__name__,
        )

        raise RuntimeError(
            "OpenRouter chat request failed"
        ) from exc

    if not response.ok:
        safe_message = openrouter_error_message(
            response
        )

        logger.error(
            "AI_CHAT_API_ERROR provider=openrouter status=%s message=%s",
            response.status_code,
            safe_message,
        )

        raise RuntimeError(
            f"OpenRouter API error: {safe_message}"
        )

    try:
        data = response.json()

    except ValueError as exc:
        logger.error(
            "AI_CHAT_INVALID_RESPONSE provider=openrouter"
        )

        raise RuntimeError(
            "OpenRouter returned invalid JSON"
        ) from exc

    choices = data.get(
        "choices",
        [],
    )

    if not choices:
        raise RuntimeError(
            "OpenRouter returned no choices"
        )

    message_data = choices[0].get(
        "message",
        {},
    )

    if not isinstance(
        message_data,
        dict,
    ):
        raise RuntimeError(
            "OpenRouter returned invalid message"
        )

    content = message_data.get(
        "content",
        "",
    )

    if isinstance(content, list):
        text_parts = []

        for item in content:
            if isinstance(item, dict):
                text = item.get("text")

                if text:
                    text_parts.append(
                        str(text)
                    )

        content = "\n".join(
            text_parts
        )

    text = str(
        content or ""
    ).strip()

    if not text:
        raise RuntimeError(
            "OpenRouter returned empty chat content"
        )

    return text


def director_chat(
    message: str,
) -> dict[str, Any]:

    if not AI_ENABLED:
        raise RuntimeError(
            "OpenRouter AI is not enabled"
        )

    context = get_recent_system_context()

    recent_runs = context.get(
        "recent_runs",
        [],
    )

    current_run_id = None

    if recent_runs:
        current_run_id = recent_runs[0].get(
            "id"
        )

    system_instruction = """
You are the AI Director of a YouTube content system.

You are having a direct conversation with the system owner.

You have access to the supplied system memory, including:
- recent YouTube analyses;
- Director runs;
- user decisions;
- actions;
- results of actions;
- previous chat messages;
- system events;
- current system state.

Rules:

1. Use the supplied memory as your source of truth.
2. Do not invent system data.
3. Historical decisions are data, not permanent rules.
4. A previous "leave as is" decision does not permanently
   forbid reconsidering a subject later.
5. A previous approval does not mean that every future
   similar action is automatically approved.
6. Distinguish facts, observations, hypotheses,
   decisions, actions and results.
7. Connect new conclusions with previous results when evidence exists.
8. Do not claim that an action was completed unless the memory
   confirms that it was completed.
9. Do not treat an old hypothesis as a current fact.
10. Do not claim certainty about future YouTube performance.
11. Answer the user's actual question directly.
12. Do not expose credentials or secrets.

Answer naturally in plain text.
Do not return JSON.
"""

    prompt = json_dumps(
        {
            "user_message": message,
            "system_context": context,
        }
    )

    # --------------------------------------------------------
    # SAVE USER MESSAGE
    # --------------------------------------------------------

    user_message_id = (
        supabase_save_chat_message(
            role="user",
            message=message,
            run_id=current_run_id,
            data={
                "provider": "openrouter",
                "model": AI_MODEL,
            },
        )
    )

    # --------------------------------------------------------
    # GENERATE DIRECTOR RESPONSE
    # --------------------------------------------------------

    answer = openrouter_generate_text(
        system_instruction=system_instruction,
        prompt=prompt,
    )

    # --------------------------------------------------------
    # SAVE DIRECTOR RESPONSE
    # --------------------------------------------------------

    assistant_message_id = (
        supabase_save_chat_message(
            role="assistant",
            message=answer,
            run_id=current_run_id,
            data={
                "provider": "openrouter",
                "model": AI_MODEL,
            },
        )
    )

    related_run_ids = [
        run.get("id")
        for run in context.get(
            "recent_runs",
            [],
        )
        if isinstance(run, dict)
        and run.get("id") is not None
    ]

    related_decision_ids = [
        decision.get("id")
        for decision in context.get(
            "recent_decisions",
            [],
        )
        if isinstance(decision, dict)
        and decision.get("id") is not None
    ]

    log_event(
        "director_chat",
        {
            "message": message[:2000],
            "run_id": current_run_id,
            "user_message_id": user_message_id,
            "assistant_message_id": assistant_message_id,
            "provider": "openrouter",
            "model": AI_MODEL,
        },
    )

    return {
        "answer": answer,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "run_id": current_run_id,
        "related_run_ids": related_run_ids[:20],
        "related_decision_ids": related_decision_ids[:20],
        "suggested_actions": [],
    }

    # --------------------------------------------------------
    # SAVE USER MESSAGE
    # --------------------------------------------------------

    user_message_id = supabase_save_chat_message(
        role="user",
        message=message,
        data={
            "provider": "openrouter",
            "model": AI_MODEL,
        },
    )

    # --------------------------------------------------------
    # SAVE DIRECTOR RESPONSE
    # --------------------------------------------------------

    assistant_message_id = supabase_save_chat_message(
        role="assistant",
        message=answer,
        data={
            "provider": "openrouter",
            "model": AI_MODEL,
        },
    )
    
    related_run_ids = [
        run.get("id")
        for run in context.get(
            "recent_runs",
            [],
        )
        if isinstance(run, dict)
        and run.get("id") is not None
    ]

    related_decision_ids = [
        decision.get("id")
        for decision in context.get(
            "recent_decisions",
            [],
        )
        if isinstance(decision, dict)
        and decision.get("id") is not None
    ]

    log_event(
        "director_chat",
        {
            "message": message[:2000],
            "provider": "openrouter",
            "model": AI_MODEL,
        },
    )

    return {
        "answer": answer,
        "user_message_id": user_message_id,
        "assistant_message_id": assistant_message_id,
        "related_run_ids": related_run_ids[:20],
        "related_decision_ids": related_decision_ids[:20],
        "suggested_actions": [],
    }


# ============================================================
# SUPABASE STATUS
# ============================================================

@app.get("/supabase/status")
async def supabase_status():

    if not SUPABASE_ENABLED or supabase is None:
        return {
            "ok": False,
            "enabled": False,
            "message": "Supabase is not configured.",
        }

    try:
        result = (
            supabase
            .table("chat_messages")
            .select("id")
            .limit(1)
            .execute()
        )

        return {
            "ok": True,
            "enabled": True,
            "database_reachable": True,
        }

    except Exception as exc:

        logger.error(
            "SUPABASE_STATUS_FAILED error_type=%s error=%s",
            type(exc).__name__,
            str(exc),
        )

        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "enabled": True,
                "database_reachable": False,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

# ============================================================
# LOGIN
# ============================================================

class LoginRequest(BaseModel):
    login: str
    password: str


@app.get(
    "/login",
    response_class=HTMLResponse,
)
async def login_page():

    return HTMLResponse(
        content="""
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>Site Insight Engine — Login</title>

    <style>
        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
            background: #111;
            color: #fff;
            font-family: Arial, sans-serif;
        }

        .login-box {
            width: 320px;
            padding: 30px;
            background: #1c1c1c;
            border-radius: 14px;
            box-shadow: 0 10px 40px rgba(0,0,0,0.4);
        }

        h1 {
            margin-top: 0;
            margin-bottom: 25px;
            font-size: 22px;
            text-align: center;
        }

        input {
            width: 100%;
            box-sizing: border-box;
            padding: 12px;
            margin-bottom: 12px;
            border: 1px solid #444;
            border-radius: 8px;
            background: #111;
            color: #fff;
            font-size: 15px;
        }

        button {
            width: 100%;
            padding: 12px;
            border: 0;
            border-radius: 8px;
            background: #fff;
            color: #111;
            font-size: 15px;
            cursor: pointer;
        }

        button:hover {
            opacity: 0.9;
        }

        .error {
            display: none;
            margin-top: 15px;
            color: #ff6b6b;
            text-align: center;
            font-size: 14px;
        }
    </style>
</head>

<body>

<div class="login-box">

    <h1>Site Insight Engine</h1>

    <form id="login-form">

        <input
            id="login"
            type="text"
            placeholder="Логин"
            autocomplete="username"
            required
        >

        <input
            id="password"
            type="password"
            placeholder="Пароль"
            autocomplete="current-password"
            required
        >

        <button type="submit">
            Войти
        </button>

        <div id="error" class="error">
            Неверный логин или пароль
        </div>

    </form>

</div>

<script>

document
    .getElementById("login-form")
    .addEventListener("submit", async function(event) {

        event.preventDefault();

        const login =
            document.getElementById("login").value;

        const password =
            document.getElementById("password").value;

        const error =
            document.getElementById("error");

        error.style.display = "none";

        try {

            const response = await fetch(
                "/login",
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        login: login,
                        password: password
                    })
                }
            );

            if (response.ok) {
                window.location.href = "/";
                return;
            }

            error.style.display = "block";

        } catch (err) {

            error.textContent =
                "Ошибка соединения с сервером";

            error.style.display = "block";
        }
    });

</script>

</body>
</html>
"""
    )


@app.post("/login")
async def login(
    request: LoginRequest,
):

    if not auth_is_configured():
        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "error": "Authentication is not configured.",
            },
        )

    valid_login = secrets.compare_digest(
        request.login,
        SITE_LOGIN,
    )

    valid_password = secrets.compare_digest(
        request.password,
        SITE_PASSWORD,
    )

    if not (
        valid_login
        and valid_password
    ):
        logger.warning(
            "AUTH_LOGIN_FAILED"
        )

        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": "Invalid credentials",
            },
        )

    token = make_auth_token()

    response = JSONResponse(
        content={
            "ok": True,
            "authenticated": True,
        }
    )

    response.set_cookie(
        key="site_auth",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    logger.info(
        "AUTH_LOGIN_SUCCESS"
    )

    return response


@app.post("/logout")
async def logout():

    response = JSONResponse(
        content={
            "ok": True,
            "authenticated": False,
        }
    )

    response.delete_cookie(
        key="site_auth",
    )

    logger.info(
        "AUTH_LOGOUT"
    )

    return response

# ============================================================
# HOME
# ============================================================

@app.get(
    "/",
    response_class=HTMLResponse,
)
async def home():

    index_path = BASE_DIR / "index.html"

    if not index_path.exists():
        return HTMLResponse(
            content=(
                "<h1>Ошибка</h1>"
                "<p>index.html не найден.</p>"
            ),
            status_code=500,
        )

    with open(
        index_path,
        "r",
        encoding="utf-8",
    ) as file:
        return HTMLResponse(
            content=file.read()
        )


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
async def health():

    provider = (
        "openrouter"
        if AI_ENABLED
        else "heuristic"
    )

    return {
        "status": "ok",
        "service": "site-insight-engine",
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "ai_enabled": AI_ENABLED,
        "ai_provider": provider,
        "supabase_enabled": SUPABASE_ENABLED,
        "director_memory": (
            "supabase"
            if SUPABASE_ENABLED
            else "sqlite"
        ),
    }

@app.get("/system/status")
async def system_status():

    provider = (
        "openrouter"
        if AI_ENABLED
        else "heuristic"
    )

    return {
        "status": "ok",
        "service": "site-insight-engine",
        "mcp_url": MCP_URL,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
        "ai": {
            "enabled": AI_ENABLED,
            "provider": provider,
            "model": AI_MODEL,
        },
    }


# ============================================================
# AI STATUS
# ============================================================

@app.get("/ai/status")
async def ai_status():

    provider = (
        "openrouter"
        if AI_ENABLED
        else "heuristic"
    )

    return {
        "enabled": AI_ENABLED,
        "provider": provider,
        "model": AI_MODEL,
        "free_mode": FREE_MODE,
        "api_key_configured": bool(
            OPENROUTER_API_KEY
        ),
    }


@app.get("/ai/test")
async def ai_test():

    if not OPENROUTER_API_KEY:
        return {
            "ok": False,
            "enabled": False,
            "provider": "openrouter",
            "message": (
                "OpenRouter is not configured. "
                "Configure OPENROUTER_API_KEY."
            ),
        }

    try:
        result = openrouter_generate_json(
            system_instruction=(
                "Return valid JSON only. "
                "The JSON must contain exactly one "
                "key named message."
            ),
            prompt=(
                "Return a JSON object with "
                "message equal to AI connection works."
            ),
        )

        return {
            "ok": True,
            "provider": "openrouter",
            "model": AI_MODEL,
            "result": result,
        }

    except Exception as exc:

        logger.error(
            "AI_TEST_FAILED provider=openrouter error_type=%s",
            type(exc).__name__,
        )

        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
                "provider": "openrouter",
                "model": AI_MODEL,
                "error": str(exc),
            },
        )


# ============================================================
# DIRECTOR CHAT MODEL
# ============================================================

class DirectorChatRequest(BaseModel):
    message: str


# ============================================================
# DIRECTOR CHAT
# ============================================================

@app.post("/director/chat")
async def director_chat_endpoint(
    request: DirectorChatRequest,
):

    message = request.message

    if not message:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "message is required",
            },
        )

    if len(message) > 4000:
        return JSONResponse(
            status_code=400,
            content={
                "ok": False,
                "error": "message is too long",
            },
        )

    try:
        result = director_chat(
            message
        )

        return {
            "ok": True,
            "provider": "openrouter",
            "model": AI_MODEL,
            "result": result,
        }

    except Exception as exc:

        logger.error(
            "DIRECTOR_CHAT_FAILED error_type=%s",
            type(exc).__name__,
        )

        log_event(
            "director_chat_failed",
            {
                "error_type": type(exc).__name__,
            },
        )

        return JSONResponse(
            status_code=500,
            content={
                "ok": False,
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
    region_code: str = "RU",
):

    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "languages": [
                    language
                ],
                "max_results_per_query": (
                    max_results_per_query
                ),
            },
        )

        return {
            "items": extract_items(
                result
            ),
            "quota_exceeded": (
                result.get(
                    "quota_exceeded",
                    False,
                )
                if isinstance(
                    result,
                    dict,
                )
                else False
            ),
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
    region_code: str = "RU",
):

    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "languages": [
                    language
                ],
                "max_results_per_query": (
                    max_results_per_query
                ),
            },
        )

        items = extract_items(
            result
        )

        return {
            "ok": True,
            "count": len(items),
            "quota_exceeded": (
                result.get(
                    "quota_exceeded",
                    False,
                )
                if isinstance(
                    result,
                    dict,
                )
                else False
            ),
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
    region_code: str = "RU",
):

    try:
        result = await mcp_call(
            "search_radar_videos",
            {
                "languages": [
                    language
                ],
                "max_results_per_query": (
                    max_results_per_query
                ),
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
            "quota_exceeded": (
                result.get(
                    "quota_exceeded",
                    False,
                )
                if isinstance(
                    result,
                    dict,
                )
                else False
            ),
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

@app.get("/director/resources")
def director_resources():
    return {
        "ok": True,
        "resources": get_director_resource_status(),
    }
        
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
    region_code: str = "RU",
):

    try:
        radar_result = await mcp_call(
            "search_radar_videos",
            {
                "languages": [
                    language
                ],
                "max_results_per_query": (
                    max_results_per_query
                ),
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
    region_code: str = "RU",
):

    result = {
        "radar": None,
        "trending": None,
        "ai": {
            "enabled": AI_ENABLED,
            "provider": (
                "openrouter"
                if AI_ENABLED
                else "heuristic"
            ),
            "model": AI_MODEL,
        },
    }

    try:
        radar = await mcp_call(
            "search_radar_videos",
            {
                "languages": [
                    language
                ],
                "max_results_per_query": 10,
            },
        )

        result["radar"] = {
            "ok": True,
            "count": len(
                extract_items(radar)
            ),
            "quota_exceeded": (
                radar.get(
                    "quota_exceeded",
                    False,
                )
                if isinstance(
                    radar,
                    dict,
                )
                else False
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
# DIRECTOR RESEARCH PLANNER
# ============================================================

def choose_director_research_languages(
    language: str | None = None,
    region_code: str | None = None,
) -> list[str]:

    # --------------------------------------------------------
    # AUTONOMOUS GLOBAL RESEARCH
    # --------------------------------------------------------

    available_languages = [
        "en",
        "hi",
        "zh",
        "ja",
        "ko",
        "es",
        "pt",
        "ar",
        "de",
        "fr",
        "it",
        "tr",
        "id",
        "vi",
        "th",
        "pl",
        "ru",
    ]

    # --------------------------------------------------------
    # MANUAL TARGETED RESEARCH
    # --------------------------------------------------------

    if language:
        return [language]

    # --------------------------------------------------------
    # QUOTA-AWARE LANGUAGE SELECTION
    # --------------------------------------------------------

    quota = get_youtube_quota_status()

    search_remaining = int(
        quota.get(
            "search_remaining",
            0,
        )
    )

    if search_remaining <= 0:
        return []

    from datetime import datetime, timezone

    day_number = (
        datetime.now(timezone.utc).timetuple().tm_yday
    )

    offset = day_number % len(
        available_languages
    )

    rotated = (
        available_languages[offset:]
        + available_languages[:offset]
    )

    return rotated
def choose_director_research_queries(
    language: str | None = None,
    previous_analysis: dict[str, Any] | None = None,
) -> list[str]:

    previous_analysis = (
        previous_analysis
        if isinstance(
            previous_analysis,
            dict,
        )
        else {}
    )

    prompt = json_dumps(
        {
            "task": (
                "Choose the YouTube research directions "
                "that the Director should investigate next."
            ),
            "language": language,
            "previous_analysis": previous_analysis,
            "rules": [
                (
                    "There is no fixed topic catalog."
                ),
                (
                    "Do not restrict research to predefined "
                    "topics."
                ),
                (
                    "You may choose completely new topics."
                ),
                (
                    "You may investigate adjacent topics."
                ),
                (
                    "You may investigate unrelated topics "
                    "when that is useful for discovering "
                    "new opportunities."
                ),
                (
                    "Queries must be concrete YouTube search "
                    "queries."
                ),
                (
                    "Use the previous analysis when it provides "
                    "useful evidence."
                ),
                (
                    "Do not assume that previous topics are "
                    "the only topics worth researching."
                ),
                (
                    "Do not recommend news."
                ),
                (
                    "Do not recommend politics."
                ),
                (
                    "Do not recommend 18+ content."
                ),
                (
                    "Do not recommend gore, torture, graphic "
                    "injury, glorification or incitement "
                    "of violence."
                ),
            ],
        }
    )

    system_instruction = """
You are the research-planning brain of an autonomous
AI Director for YouTube.

Your job is to decide what the Director should search
for next.

There is NO fixed topic catalog.

The Director must be able to discover completely new
topics, niches, formats, audience interests and emerging
content directions.

Previous research is evidence, not a restriction.

You may:
- continue a promising direction;
- investigate an adjacent direction;
- compare different niches;
- test a hypothesis;
- investigate a completely new subject;
- investigate a new format;
- investigate a new audience interest.

Do not recommend:
- news;
- politics;
- 18+ content;
- gore;
- torture;
- graphic injury;
- glorification or incitement of violence.

Return ONLY valid JSON in this structure:

{
  "queries": [
    "concrete YouTube search query"
  ]
}

Do not return explanations.
"""

    if not AI_ENABLED:
        return []

    try:
        result = openrouter_generate_json(
            system_instruction=system_instruction,
            prompt=prompt,
        )

    except Exception as exc:

        logger.warning(
            "DIRECTOR_QUERY_PLANNER_FAILED "
            "error_type=%s",
            type(exc).__name__,
        )

        log_event(
            "director_query_planner_failed",
            {
                "error_type": type(exc).__name__,
            },
        )

        return []

    queries = result.get(
        "queries",
        [],
    )

    if not isinstance(
        queries,
        list,
    ):
        return []

    cleaned_queries = []

    for query in queries:

        if not isinstance(
            query,
            str,
        ):
            continue

        query = query.strip()

        if not query:
            continue

        if query not in cleaned_queries:
            cleaned_queries.append(
                query
            )

    return cleaned_queries     
# ============================================================
# DIRECTOR RUN
# ============================================================

@app.post("/director/run")
@app.get("/director/run")
async def director_run(
    language: str | None = None,
    region_code: str | None = None,
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
    # 1. DIRECTOR RESEARCH PLAN
    # --------------------------------------------------------

    research_languages = (
        choose_director_research_languages(
            language=language,
            region_code=region_code,
        )
    )
    
    research_queries = (
        choose_director_research_queries(
            language=language,
            previous_analysis=None,
        )
    )

    resources = get_director_resource_status()

    search_budget = int(
        resources["youtube_quota"].get(
            "search_available_for_research",
            0,
        )
    )

    if research_languages:

        max_queries = (
            search_budget
            // len(research_languages)
        )

        research_queries = (
            research_queries[:max_queries]
        )
    else:
        research_queries = []
    
    log_event(
        "director_research_plan_created",
        {
            "language": language,
            "region_code": region_code,
            "research_languages": research_languages,
            "research_queries": research_queries,
        },
    )

    # --------------------------------------------------------
    # 2. RADAR
    # --------------------------------------------------------

    radar_result = await mcp_call(
        "search_radar_videos",
        {
            "languages": research_languages,
            "queries": research_queries,
            "max_results_per_query": 10,
        },
    )

    radar_videos = extract_items(
        radar_result
    )

    radar_quota = (
        radar_result.get(
            "_quota",
            {},
        )
        if isinstance(
            radar_result,
            dict,
        )
        else {}
    )

    record_youtube_quota_usage(
        operation="director_radar",
        search_calls=int(
            radar_quota.get(
                "search_calls",
                0,
            )
        ),
        other_units=int(
            radar_quota.get(
                "other_units",
                0,
            )
        ),
        metadata={
            "languages": research_languages,
            "queries": research_queries,
        },
    )
    
    quota_exceeded = (
        radar_result.get(
            "quota_exceeded",
            False,
        )
        if isinstance(
            radar_result,
            dict,
        )
        else False
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

    trending_videos = []

    try:
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

    except Exception as exc:

        logger.warning(
            "TRENDING_FAILED error_type=%s",
            type(exc).__name__,
        )

        log_event(
            "trending_collection_failed",
            {
                "error_type": type(exc).__name__,
            },
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
        "research_languages": research_languages,
        "research_queries": research_queries,
        "resource_plan": get_director_resource_status(),
        "radar_count": len(
            radar_videos
        ),
        "radar_quota_exceeded": quota_exceeded,
        "saved_count": saved_count,
        "trending_count": len(
            trending_videos
        ),
        "analysis": analysis,
        "next_action": next_action,
        "free_mode": FREE_MODE,
        "autonomous": AUTONOMOUS,
    }

    # --------------------------------------------------------
    # SAVE DIRECTOR RUN TO SUPABASE
    # --------------------------------------------------------

    run_id = supabase_save_director_run(
        language=language,
        region_code=region_code,
        data=run_data,
    )

    # --------------------------------------------------------
    # FALLBACK TO SQLITE
    # --------------------------------------------------------

    if run_id is None:

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
        "research": {
            "languages": research_languages,
            "queries": research_queries,
        },
        "radar": {
            "count": len(
                radar_videos
            ),
            "saved": saved_count,
            "quota_exceeded": quota_exceeded,
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
# DIRECTOR AUTOMATIC SCHEDULER ENDPOINT
# ============================================================

@app.post("/director/cron")
async def director_cron(
    request: Request,
):
    if not DIRECTOR_CRON_SECRET:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "DIRECTOR_CRON_SECRET is not configured",
            },
        )

    provided_secret = request.headers.get(
        "X-Director-Cron-Secret",
        "",
    ).strip()

    if not hmac.compare_digest(
        provided_secret,
        DIRECTOR_CRON_SECRET,
    ):
        return JSONResponse(
            status_code=401,
            content={
                "ok": False,
                "error": "Invalid scheduler secret",
            },
        )

    log_event(
        "director_cron_started",
        {},
    )

    result = await director_run()

    log_event(
        "director_cron_completed",
        {
            "run_id": result.get(
                "run_id"
            )
            if isinstance(result, dict)
            else None,
        },
    )

    return result

@app.post("/api/weekly-reports/generate")
def api_generate_weekly_report(
    week_start: str | None = None,
    week_end: str | None = None,
):
    today = datetime.now(
        timezone.utc
    ).date()

    if week_end is None:
        week_end = today.isoformat()

    if week_start is None:
        start_date = (
            today
            - timedelta(
                days=today.weekday()
            )
        )
        week_start = start_date.isoformat()

    return generate_weekly_report(
        week_start=week_start,
        week_end=week_end,
    )
@app.post("/api/weekly-reports/generate")
def api_generate_weekly_report(
    week_start: str | None = None,
    week_end: str | None = None,
):
    today = datetime.now(timezone.utc).date()

    if week_end is None:
        week_end_date = today
    else:
        week_end_date = date.fromisoformat(
            week_end
        )

    if week_start is None:
        week_start_date = (
            week_end_date
            - timedelta(
                days=week_end_date.weekday()
            )
        )
    else:
        week_start_date = date.fromisoformat(
            week_start
        )

    return generate_weekly_report(
        week_start=week_start_date.isoformat(),
        week_end=week_end_date.isoformat(),
    )



# ============================================================
# WEEKLY REPORT API
# ============================================================

@app.get("/api/weekly-reports")
def api_weekly_reports(limit: int = 12):
    limit = max(1, min(limit, 100))

    return {
        "ok": True,
        "reports": get_weekly_reports(limit),
    }


@app.get("/api/weekly-reports/{report_id}")
def api_weekly_report(report_id: int):
    report = get_weekly_report(report_id)

    if report is None:
        raise HTTPException(
            status_code=404,
            detail="Weekly report not found",
        )

    return {
        "ok": True,
        "report": report,
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

    # --------------------------------------------------------
    # PRIMARY: SUPABASE
    # --------------------------------------------------------

    if SUPABASE_ENABLED and supabase is not None:

        try:
            result = (
                supabase
                .table("director_runs")
                .select("*")
                .order("id", desc=True)
                .limit(limit)
                .execute()
            )

            rows = result.data or []

            return [
                {
                    "id": row.get("id"),
                    "created_at": row.get(
                        "created_at"
                    ),
                    "language": row.get(
                        "language"
                    ),
                    "region_code": row.get(
                        "region_code"
                    ),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in rows
            ]

        except Exception as exc:

            logger.error(
                "SUPABASE_DIRECTOR_HISTORY_FAILED error_type=%s error=%s",
                type(exc).__name__,
                str(exc),
            )

    # --------------------------------------------------------
    # FALLBACK: SQLITE
    # --------------------------------------------------------

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
    request: Request,
    decision: str | None = None,
    run_id: int | None = None,
):

    body = {}

    content_type = (
        request.headers.get(
            "content-type",
            "",
        )
        .lower()
    )

    if "application/json" in content_type:
        try:
            body = await request.json()
        except Exception:
            body = {}

    decision = (
        body.get("decision")
        or decision
    )

    body_run_id = body.get(
        "run_id"
    )

    if body_run_id is not None:
        try:
            run_id = int(body_run_id)
        except Exception:
            run_id = None

    decision_data = body.get(
        "data"
    )

    if not isinstance(
        decision_data,
        dict,
    ):
        decision_data = {}

    if not decision:
        return JSONResponse(
            status_code=400,
            content={
                "error": "decision is required",
            },
        )

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

    # If no run was supplied, attach the decision
    # to the latest Director run.
    if run_id is None and SUPABASE_ENABLED and supabase is not None:
        try:
            latest_run = (
                supabase
                .table("director_runs")
                .select("id")
                .order("id", desc=True)
                .limit(1)
                .execute()
            )

            latest_rows = (
                latest_run.data or []
            )

            if latest_rows:
                run_id = latest_rows[0].get(
                    "id"
                )

        except Exception:
            run_id = None

    decision_id = supabase_save_decision(
        decision=decision,
        data=decision_data,
        run_id=run_id,
    )

    if decision_id is None:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": "Decision could not be saved to Supabase.",
            },
        )

    log_event(
        "director_decision",
        {
            "decision_id": decision_id,
            "run_id": run_id,
            "decision": decision,
        },
    )

    return {
        "ok": True,
        "decision_id": decision_id,
        "run_id": run_id,
        "decision": decision,
    }
class DirectorActionRequest(BaseModel):
    description: str
    action_type: str = "general"
    run_id: int | None = None
    decision_id: int | None = None
    data: dict[str, Any] = {}

# ============================================================
# DIRECTOR ACTION
# ============================================================

@app.post("/director/action")
async def director_action(
    request: DirectorActionRequest,
):

    action_id = supabase_save_action(
        description=request.description,
        action_type=request.action_type,
        run_id=request.run_id,
        decision_id=request.decision_id,
        data=request.data,
    )

    if action_id is None:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": (
                    "Action could not be saved "
                    "to Supabase."
                ),
            },
        )

    log_event(
        "director_action_created",
        {
            "action_id": action_id,
            "run_id": request.run_id,
            "decision_id": request.decision_id,
            "action_type": request.action_type,
        },
    )

    return {
        "ok": True,
        "action_id": action_id,
        "run_id": request.run_id,
        "decision_id": request.decision_id,
        "status": "pending",
    }

class DirectorResultRequest(BaseModel):
    action_id: int
    summary: str
    result_type: str = "completed"
    run_id: int | None = None
    data: dict[str, Any] = {}

# ============================================================
# DIRECTOR RESULT
# ============================================================

@app.post("/director/result")
async def director_result(
    request: DirectorResultRequest,
):

    result_id = supabase_save_result(
        action_id=request.action_id,
        summary=request.summary,
        result_type=request.result_type,
        run_id=request.run_id,
        data=request.data,
    )

    if result_id is None:
        return JSONResponse(
            status_code=503,
            content={
                "ok": False,
                "error": (
                    "Result could not be saved "
                    "to Supabase."
                ),
            },
        )

    log_event(
        "director_action_completed",
        {
            "action_id": request.action_id,
            "result_id": result_id,
            "run_id": request.run_id,
        },
    )

    return {
        "ok": True,
        "result_id": result_id,
        "action_id": request.action_id,
        "run_id": request.run_id,
        "status": "completed",
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

    # --------------------------------------------------------
    # PRIMARY: SUPABASE
    # --------------------------------------------------------

    if SUPABASE_ENABLED and supabase is not None:

        try:
            result = (
                supabase
                .table("system_events")
                .select("*")
                .order("id", desc=True)
                .limit(limit)
                .execute()
            )

            rows = result.data or []

            return [
                {
                    "id": row.get("id"),
                    "created_at": row.get(
                        "created_at"
                    ),
                    "event_type": row.get(
                        "event_type"
                    ),
                    "data": (
                        row.get("data_json")
                        if isinstance(
                            row.get("data_json"),
                            dict,
                        )
                        else json_loads_safe(
                            row.get("data_json"),
                            {},
                        )
                    ),
                }
                for row in rows
            ]

        except Exception as exc:

            logger.error(
                "SUPABASE_EVENTS_FAILED error_type=%s error=%s",
                type(exc).__name__,
                str(exc),
            )

    # --------------------------------------------------------
    # FALLBACK: SQLITE
    # --------------------------------------------------------

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
            "openrouter"
            if AI_ENABLED
            else "heuristic"
        ),
        "ai_model": AI_MODEL,
    }

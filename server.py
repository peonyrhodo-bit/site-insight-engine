import os
import json
from pathlib import Path

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

    return HTMLResponse(html)


# ============================================================
# COMMON MCP CALL
# ============================================================

async def call_mcp_tool(
    tool_name: str,
    arguments: dict,
):
    """
    Универсальный вызов MCP-инструмента.
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
# MCP TOOLS
# ============================================================

@app.get("/mcp-tools")
async def mcp_tools():

    try:

        data = await call_mcp_tool(
            "get_channel_stats",
            {
                "channel_id":
                    "UC_x5XG1OV2P6uZZ5FSM9Ttw"
            },
        )

        return {
            "status": "ok",
            "test": data,
        }

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

        return JSONResponse(data)

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

        arguments = {
            "query": query,
            "max_results": max_results,
            "published_after": published_after,
            "published_before": published_before,
            "region_code": region_code,
            "relevance_language": relevance_language,
            "order": order,
        }

        data = await call_mcp_tool(
            "search_videos",
            arguments,
        )

        return JSONResponse(data)

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

        return JSONResponse(data)

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

        return JSONResponse(data)

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
# CHANNEL ANALYSIS
# ============================================================

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

        return JSONResponse(data)

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
# START
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

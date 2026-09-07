import os
import json

from pathlib import Path

import aiofiles

from fastapi import FastAPI

from fastapi.middleware.cors import CORSMiddleware

from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
)

from mcp import ClientSession

from mcp.client.streamable_http import (
    streamablehttp_client
)


# =========================================================
# FASTAPI
# =========================================================

app = FastAPI()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================================================
# MCP
# =========================================================

MCP_URL = (
    "https://youtube-mcp-u39z.onrender.com/mcp"
)


# =========================================================
# ГЛАВНАЯ СТРАНИЦА
# =========================================================

@app.get("/")
async def home():

    html_path = (
        Path(__file__).parent
        / "index.html"
    )

    async with aiofiles.open(
        html_path,
        mode="r",
        encoding="utf-8"
    ) as f:

        html = await f.read()


    return HTMLResponse(html)


# =========================================================
# MCP TOOLS
# =========================================================

@app.get("/mcp-tools")
async def mcp_tools():

    try:

        async with streamablehttp_client(
            MCP_URL
        ) as (
            read_stream,
            write_stream,
            _,
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()

                tools = (
                    await session.list_tools()
                )


                return {

                    "tools": [

                        {
                            "name": tool.name,
                            "description": tool.description,
                        }

                        for tool in tools.tools

                    ]

                }


    except Exception as e:

        import traceback

        traceback.print_exc()

        return JSONResponse(
            {
                "error": str(e)
            },
            status_code=500
        )


# =========================================================
# ПОИСК КАНАЛОВ
# =========================================================

@app.get("/search-channels")
async def search_channels(
    query: str,
    max_results: int = 20
):

    try:

        async with streamablehttp_client(
            MCP_URL
        ) as (
            read_stream,
            write_stream,
            _,
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()


                result = await session.call_tool(
                    "search_channels",
                    {
                        "query": query,
                        "max_results": max_results,
                    },
                )


                if not result.content:

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул пустой ответ"
                        },
                        status_code=500
                    )


                content = result.content[0]


                if not hasattr(
                    content,
                    "text"
                ):

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул контент не текстового типа"
                        },
                        status_code=500
                    )


                data = json.loads(
                    content.text
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
            status_code=500
        )


# =========================================================
# ПОИСК ВИДЕО
# =========================================================

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

        async with streamablehttp_client(
            MCP_URL
        ) as (
            read_stream,
            write_stream,
            _,
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()


                arguments = {

                    "query": query,

                    "max_results":
                        max_results,

                    "order":
                        order,

                }


                if published_after:

                    arguments[
                        "published_after"
                    ] = published_after


                if published_before:

                    arguments[
                        "published_before"
                    ] = published_before


                if region_code:

                    arguments[
                        "region_code"
                    ] = region_code


                if relevance_language:

                    arguments[
                        "relevance_language"
                    ] = relevance_language


                result = await session.call_tool(
                    "search_videos",
                    arguments,
                )


                if not result.content:

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул пустой ответ"
                        },
                        status_code=500
                    )


                content = result.content[0]


                if not hasattr(
                    content,
                    "text"
                ):

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул контент не текстового типа"
                        },
                        status_code=500
                    )


                data = json.loads(
                    content.text
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
            status_code=500
        )


# =========================================================
# 🔥 ТРЕНДЫ YOUTUBE
# =========================================================

@app.get("/trending-videos")
async def trending_videos(
    max_results: int = 50,
    region_code: str = "US",
):

    try:

        async with streamablehttp_client(
            MCP_URL
        ) as (
            read_stream,
            write_stream,
            _,
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()


                result = await session.call_tool(
                    "search_trending_videos",
                    {
                        "max_results":
                            max_results,

                        "region_code":
                            region_code,
                    },
                )


                if not result.content:

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул пустой ответ"
                        },
                        status_code=500
                    )


                content = result.content[0]


                if not hasattr(
                    content,
                    "text"
                ):

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул контент не текстового типа"
                        },
                        status_code=500
                    )


                try:

                    data = json.loads(
                        content.text
                    )

                except json.JSONDecodeError:

                    return JSONResponse(
                        {
                            "error":
                                f"MCP вернул не JSON: {content.text}"
                        },
                        status_code=500
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
            status_code=500
        )


# =========================================================
# 🚀 РАДАР
# =========================================================

@app.get("/radar-videos")
async def radar_videos(
    max_results: int = 50,
    region_code: str = "US",
    hours_back: int = 72,
):

    try:

        async with streamablehttp_client(
            MCP_URL
        ) as (
            read_stream,
            write_stream,
            _,
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()


                result = await session.call_tool(
                    "search_radar_videos",
                    {
                        "max_results":
                            max_results,

                        "region_code":
                            region_code,

                        "hours_back":
                            hours_back,
                    },
                )


                if not result.content:

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул пустой ответ"
                        },
                        status_code=500
                    )


                content = result.content[0]


                if not hasattr(
                    content,
                    "text"
                ):

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул контент не текстового типа"
                        },
                        status_code=500
                    )


                try:

                    data = json.loads(
                        content.text
                    )

                except json.JSONDecodeError:

                    return JSONResponse(
                        {
                            "error":
                                f"MCP вернул не JSON: {content.text}"
                        },
                        status_code=500
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
            status_code=500
        )


# =========================================================
# АНАЛИЗ КАНАЛА
# =========================================================

@app.get("/analyze")
async def analyze(
    channel_id: str
):

    try:

        async with streamablehttp_client(
            MCP_URL
        ) as (
            read_stream,
            write_stream,
            _,
        ):

            async with ClientSession(
                read_stream,
                write_stream
            ) as session:

                await session.initialize()


                result = await session.call_tool(
                    "get_channel_stats",
                    {
                        "channel_id":
                            channel_id
                    },
                )


                if not result.content:

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул пустой ответ"
                        },
                        status_code=500
                    )


                content = result.content[0]


                if not hasattr(
                    content,
                    "text"
                ):

                    return JSONResponse(
                        {
                            "error":
                                "MCP вернул контент не текстового типа"
                        },
                        status_code=500
                    )


                data = json.loads(
                    content.text
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
            status_code=500
        )


# =========================================================
# ЗАПУСК
# =========================================================

if __name__ == "__main__":

    import uvicorn

    port = int(
        os.environ.get(
            "PORT",
            "10000"
        )
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )

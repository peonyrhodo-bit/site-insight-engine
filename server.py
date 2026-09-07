import os
import json
from pathlib import Path

import aiofiles
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

MCP_URL = "https://youtube-mcp-u39z.onrender.com/mcp"


@app.get("/")
async def home():
    html_path = Path(__file__).parent / "index.html"

    async with aiofiles.open(
        html_path,
        mode="r",
        encoding="utf-8",
    ) as f:
        html = await f.read()

    return HTMLResponse(html)


@app.get("/mcp-tools")
async def mcp_tools():
    try:
        async with streamablehttp_client(MCP_URL) as (
            read_stream,
            write_stream,
            _,
        ):
            async with ClientSession(
                read_stream,
                write_stream,
            ) as session:
                await session.initialize()

                tools = await session.list_tools()

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
            {"error": str(e)},
            status_code=500,
        )

@app.get("/search-channels")
async def search_channels(query: str, max_results: int = 20):
    try:
        async with streamablehttp_client(MCP_URL) as (
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
                    "search_channels",
                    {
                        "query": query,
                        "max_results": max_results,
                    },
                )

                if not result.content:
                    return JSONResponse(
                        {
                            "error": "MCP вернул пустой ответ"
                        },
                        status_code=500,
                    )

                content = result.content[0]

                if not hasattr(content, "text"):
                    return JSONResponse(
                        {
                            "error": "MCP вернул контент не текстового типа"
                        },
                        status_code=500,
                    )

                try:
                    data = json.loads(content.text)
                except json.JSONDecodeError:
                    return JSONResponse(
                        {
                            "error": (
                                "MCP вернул не JSON: "
                                f"{content.text}"
                            )
                        },
                        status_code=500,
                    )

                return JSONResponse(data)

    except Exception as e:
        import traceback
        traceback.print_exc()

        return JSONResponse(
            {"error": str(e)},
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
        async with streamablehttp_client(MCP_URL) as (
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

                if not result.content:
                    return JSONResponse(
                        {
                            "error": "MCP вернул пустой ответ"
                        },
                        status_code=500,
                    )

                content = result.content[0]

                if not hasattr(content, "text"):
                    return JSONResponse(
                        {
                            "error": (
                                "MCP вернул контент "
                                "не текстового типа"
                            )
                        },
                        status_code=500,
                    )

                try:
                    data = json.loads(content.text)
                except json.JSONDecodeError:
                    return JSONResponse(
                        {
                            "error": (
                                "MCP вернул не JSON: "
                                f"{content.text}"
                            )
                        },
                        status_code=500,
                    )

                return JSONResponse(data)

    except Exception as e:
        import traceback
        traceback.print_exc()

        return JSONResponse(
            {"error": str(e)},
            status_code=500,
        )

@app.get("/analyze")
async def analyze(channel_id: str):
    try:
        async with streamablehttp_client(MCP_URL) as (
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
                    "get_channel_stats",
                    {"channel_id": channel_id},
                )

                if not result.content:
                    return JSONResponse(
                        {
                            "result": {
                                "error": "MCP вернул пустой ответ"
                            }
                        },
                        status_code=500,
                    )

                content = result.content[0]

                if not hasattr(content, "text"):
                    return JSONResponse(
                        {
                            "result": {
                                "error": (
                                    "MCP вернул контент "
                                    "не текстового типа"
                                )
                            }
                        },
                        status_code=500,
                    )

                content_text = content.text

                try:
                    stats = json.loads(content_text)
                except json.JSONDecodeError:
                    return JSONResponse(
                        {
                            "result": {
                                "error": (
                                    "MCP вернул не JSON: "
                                    f"{content_text}"
                                )
                            }
                        },
                        status_code=500,
                    )

                return JSONResponse({"result": stats})

    except Exception as e:
        import traceback
        traceback.print_exc()

        return JSONResponse(
            {"result": {"error": str(e)}},
            status_code=500,
        )


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "10000"))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
    )

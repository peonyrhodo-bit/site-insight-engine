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
    async with aiofiles.open(html_path, mode="r", encoding="utf-8") as f:
        html = await f.read()
    return HTMLResponse(html)


@app.get("/analyze")
async def analyze(channel_id: str):
    try:
        async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                result = await session.call_tool(
                    "get_channel_stats",
                    {"channel_id": channel_id},
                )

                content_text = result.content[0].text

                try:
                    stats = json.loads(content_text)
                except json.JSONDecodeError:
                    return JSONResponse(
                        {"result": {"error": f"MCP вернул не JSON: {content_text}"}},
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
    uvicorn.run(app, host="0.0.0.0", port=port)

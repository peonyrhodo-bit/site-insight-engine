import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
def home():
    return {"status": "ok", "message": "YouTube AI backend работает"}


@app.get("/analyze")
async def analyze(channel_id: str):
    async with streamablehttp_client(MCP_URL) as (
        read_stream,
        write_stream,
        _,
    ):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            result = await session.call_tool(
                "get_channel_stats",
                {"channel_id": channel_id},
            )

            return {
                "result": result.content[0].text
            }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "10000")),
    )

import os
from pathlib import Path

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

# Адрес твоего MCP-агента (убедитесь, что он совпадает с твоим сервисом на Render)
MCP_URL = "https://youtube-mcp-u39z.onrender.com/mcp"

@app.get("/")
def home():
    # Пытаемся прочитать index.html из той же папки, где лежит server.py
    try:
        html_path = Path(__file__).parent / "index.html"
        html = html_path.read_text(encoding="utf-8")
        return HTMLResponse(html)
    except FileNotFoundError:
        return JSONResponse({"error": "Файл index.html не найден. Проверьте структуру репозитория."}, status_code=500)

@app.get("/analyze")
async def analyze(channel_id: str):
    try:
        async with streamablehttp_client(MCP_URL) as (read_stream, write_stream, _,):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()

                result = await session.call_tool(
                    "get_channel_stats",
                    {"channel_id": channel_id},
                )

                # result.content - это список объектов, берем первый и его текст
                return JSONResponse({"result": result.content.text})
    except Exception as e:
        return JSONResponse({"result": f"Ошибка при запросе к агенту: {str(e)}"}, status_code=500)

if __name__ == "__main__":
    import uvicorn
    # Render сам подставит правильный PORT, но дефолтное значение тоже полезно
    port = int(os.environ.get("PORT", "10000"))
    uvicorn.run(app, host="0.0.0.0", port=port)

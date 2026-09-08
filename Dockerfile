FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY index.html .

RUN mkdir -p /app/data

ENV PORT=10000
ENV MCP_URL=http://youtube-mcp:8000/mcp
ENV FREE_MODE=true
ENV AUTONOMOUS=false

EXPOSE 10000

CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "10000"]

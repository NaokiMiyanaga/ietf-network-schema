FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV CMDB_DB_PATH=/data/cmdb.sqlite3
ENV AIOPS_LOG_DIR=/data/logs
ENV REQUIRE_AUTH=1
ENV MCP_TOKEN=secret123
EXPOSE 9101
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9101"]

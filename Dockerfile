FROM python:3.11-slim
WORKDIR /app/cmdb-mcp
# COPY requirements.txt .
# RUN pip install --no-cache-dir -r requirements.txt
RUN pip install --no-cache-dir "fastapi>=0.112.2" "uvicorn>=0.30.6" "pydantic>=2.9" "PyYAML>=6.0" 

#COPY . .
#ENV CMDB_DB_PATH=/data/cmdb.sqlite3
#ENV AIOPS_LOG_DIR=/data/logs
#ENV REQUIRE_AUTH=1
#ENV MCP_TOKEN=secret123
EXPOSE 9001
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "9001"]

from __future__ import annotations
import os, json, datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from db import get_conn, init_db, upsert as db_upsert, get as db_get, search as db_search, select_sql

app = FastAPI(title="CMDB MCP Server")

# --- config ---------------------------------------------------------------
REQUIRE_AUTH = (os.getenv("REQUIRE_AUTH", "1") not in ["0", "false", "off"])
MCP_TOKEN = os.getenv("MCP_TOKEN", "secret123")
BASE_DIR = str(Path.cwd())

# --- logging (JSONL, JST timestamp, 10-event spec) -----------------------
LOG_DIR = Path(os.getenv("AIOPS_LOG_DIR", "./data/logs")).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / "cmdb_mcp_access.jsonl"

def now_jst_iso() -> str:
    return datetime.datetime.utcnow().astimezone(datetime.timezone(datetime.timedelta(hours=9))).isoformat()

def log_json(no: int, actor: str, content: str, tag: str):
    rec = {"ts_jst": now_jst_iso(), "no": no, "actor": actor, "content": content, "tag": tag}
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# --- auth middleware ------------------------------------------------------
@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.url.path in ["/health", "/openapi.json"]:
        return await call_next(request)
    if REQUIRE_AUTH:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            return JSONResponse({"ok": False, "error": "missing bearer"}, status_code=401)
        token = auth.split(" ", 1)[1].strip()
        if token != MCP_TOKEN:
            return JSONResponse({"ok": False, "error": "invalid token"}, status_code=403)
    return await call_next(request)

# --- DB init --------------------------------------------------------------
conn = get_conn()
init_db(conn)

# --- Schemas --------------------------------------------------------------
class ToolCall(BaseModel):
    name: str
    arguments: dict = Field(default_factory=dict)

# --- health ---------------------------------------------------------------
@app.get("/health")
def health():
    payload = {
        "ok": True,
        "ts_jst": now_jst_iso(),
        "id": None,
        "server_version": "v1",
        "mode": "cmdb",
        "mode_reason": "sqlite/json1/fts5",
        "require_auth": REQUIRE_AUTH,
        "base_dir": BASE_DIR,
    }
    return JSONResponse(payload)

# --- tools ---------------------------------------------------------------
@app.get("/tools/list")
def tools_list():
    tools = [
        {
            "name": "cmdb.query",
            "description": "Execute a read-only SQL (SELECT only).",
            "input_schema": {"type": "object","properties": {"sql": {"type": "string"}},"required": ["sql"]},
        },
        {
            "name": "cmdb.get",
            "description": "Get a CMDB object by (kind, id).",
            "input_schema": {"type": "object","properties": {"kind": {"type": "string"},"id": {"type": "string"}},"required": ["kind", "id"]},
        },
        {
            "name": "cmdb.upsert",
            "description": "Insert or update (kind, id) with JSON data.",
            "input_schema": {"type": "object","properties": {"kind": {"type": "string"},"id": {"type": "string"},"data": {"type": "object"}},"required": ["kind", "id", "data"]},
        },
        {
            "name": "cmdb.search",
            "description": "Full-text search across CMDB objects (FTS5).",
            "input_schema": {"type": "object","properties": {"q": {"type": "string"},"limit": {"type": "integer"},"offset": {"type": "integer"}},"required": ["q"]},
        },
    ]
    log_json(1, "mcp", "list tools", "mcp tools list")
    return {"ok": True, "result": {"tools": tools, "count": len(tools)}}

@app.post("/tools/call")
def tools_call(call: ToolCall):
    name = call.name
    args = call.arguments or {}
    log_json(5, "mcp", json.dumps({"name": name, "arguments": args}, ensure_ascii=False), "mcp request")
    try:
        if name == "cmdb.query":
            sql = args.get("sql") or ""
            result = select_sql(conn, sql)
            return {"ok": True, "result": result}
        elif name == "cmdb.get":
            kind = args.get("kind")
            id_ = args.get("id")
            if not kind or not id_:
                raise HTTPException(status_code=400, detail="kind and id are required")
            obj = db_get(conn, kind, id_)
            return {"ok": True, "result": obj}
        elif name == "cmdb.upsert":
            kind = args.get("kind")
            id_ = args.get("id")
            data = args.get("data")
            if not (kind and id_ and isinstance(data, dict)):
                raise HTTPException(status_code=400, detail="kind, id, data(object) required")
            res = db_upsert(conn, kind, id_, json.dumps(data, ensure_ascii=False))
            log_json(8, "mcp", f"upsert {kind}:{id_}", "mcp reply")
            return {"ok": True, "result": res}
        elif name == "cmdb.search":
            q = args.get("q") or ""
            limit = int(args.get("limit") or 20)
            offset = int(args.get("offset") or 0)
            res = db_search(conn, q, limit, offset)
            return {"ok": True, "result": res}
        else:
            raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
    except Exception as e:
        return {"ok": False, "error": str(e)}

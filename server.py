from __future__ import annotations
import os, json, datetime
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from db import get_conn, init_db, upsert as db_upsert, get as db_get, search as db_search, select_sql
from typing import Optional
import logging


app = FastAPI(title="CMDB MCP Server")

# --- config (auth & base dir) --------------------------------------------
REQUIRE_AUTH = (os.getenv("REQUIRE_AUTH", "1").lower() not in ["0", "false", "off"])
# Accept multiple env names for the shared token (no breaking change)
MCP_TOKEN = (
    os.getenv("MCP_TOKEN")
    or os.getenv("AIOPS_MCP_TOKEN")
    or os.getenv("AIOPS_MCP_TOKEN_CMDB")
    or "secret123"
)
BASE_DIR = str(Path.cwd())

JST = datetime.timezone(datetime.timedelta(hours=9))
START_TS = datetime.datetime.now(tz=JST)
START_TS_STR = START_TS.strftime("%Y%m%d-%H%M%S")

# --- logger & masking helper ---------------------------------------------
logger = logging.getLogger("cmdb-mcp")

def _mask(tok: str | None) -> str:
    if not tok:
        return "(none)"
    if len(tok) <= 6:
        return tok[0] + "*" * (len(tok) - 2) + tok[-1]
    return tok[:3] + "***" + tok[-3:]

# --- logging (JSONL, JST timestamp, 10-event spec) -----------------------
# Default log directory is /app/logs inside container (host ./logs)
LOG_DIR = Path(os.getenv("AIOPS_LOG_DIR", "/app/logs")).expanduser()
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOG_DIR / f"mcp_events_{START_TS_STR}.jsonl"
MCP_LOG_HEALTH = os.getenv("MCP_LOG_HEALTH", "0").lower() not in ["0", "false", "off"]

try:
    logger.info("log: dir=%s path=%s health_log=%s", str(LOG_DIR), str(LOG_PATH), str(MCP_LOG_HEALTH))
except Exception:
    pass

def now_jst_iso() -> str:
  return datetime.datetime.utcnow().astimezone(JST).isoformat()

def log_json(no: int, actor: str, content: str | dict, tag: str, request_id: Optional[str] = None):
  try:
    # Normalize content to string
    if isinstance(content, dict):
      try:
        content = json.dumps(content, ensure_ascii=False)
      except Exception:
        content = str(content)
    elif not isinstance(content, str):
      content = str(content)

    # Bound the log size (avoid megabyte bursts)
    MAX_LEN = 8192  # 8KB per record
    if len(content) > MAX_LEN:
      content = content[:MAX_LEN] + "…(truncated)"

    rec = {"ts_jst": now_jst_iso(), "no": no, "actor": actor, "content": content, "tag": tag}
    if request_id:
      rec["request_id"] = request_id

    with open(LOG_PATH, "a", encoding="utf-8") as f:
      f.write(json.dumps(rec, ensure_ascii=False) + "\n")
  except Exception as e:
      # Logging must never break serving; optional fallback print for debug
      if os.getenv("AIOPS_DEBUG_LOG"):
          try:
              print(f"[LOG_WRITE_FAIL] path={LOG_PATH} err={e}")
          except Exception:
              pass
      pass

# --- auth middleware ------------------------------------------------------
@app.middleware("http")
async def auth_mw(request: Request, call_next):
    if request.url.path in ["/health", "/openapi.json"]:
        return await call_next(request)
    if REQUIRE_AUTH:
        auth = request.headers.get("authorization", "")
        if not auth.lower().startswith("bearer "):
            try:
                logger.warning("auth: missing bearer path=%s", request.url.path)
            except Exception:
                pass
            return JSONResponse({"ok": False, "error": "missing bearer"}, status_code=401)
        token = auth.split(" ", 1)[1].strip()
        if token != MCP_TOKEN:
            try:
                logger.warning(
                    "auth: invalid token path=%s got=%s expect=%s",
#                    request.url.path, _mask(token), _mask(MCP_TOKEN)
                    request.url.path, token, MCP_TOKEN
                )
            except Exception:
                pass
            return JSONResponse({"ok": False, "error": "invalid token"}, status_code=403)
        else:
            # Optional debug on success
            if os.getenv("AIOPS_DEBUG_AUTH"):
                try:
                    logger.info("auth: ok path=%s got=%s", request.url.path, _mask(token))
                except Exception:
                    pass
    return await call_next(request)

# --- DB init --------------------------------------------------------------
@app.on_event("startup")
def _init_db_on_startup():
    try:
        logger.info(
            "auth: REQUIRE_AUTH=%s MCP_TOKEN(masked)=%s len=%s",
            str(REQUIRE_AUTH), _mask(MCP_TOKEN), len(MCP_TOKEN) if MCP_TOKEN else 0,
        )
    except Exception:
        pass
    _c = get_conn()
    try:
        init_db(_c)
    finally:
        try:
            _c.close()
        except Exception:
            pass

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
    if MCP_LOG_HEALTH:
      log_json(-1, "cmdb-mcp", payload, "cmdb-mcp health")
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
    log_json(1, "cmdb-mcp", "list tools", "cmdb-mcp tools list")
    return {"ok": True, "result": {"tools": tools, "count": len(tools)}}

@app.post("/tools/call")
def tools_call(call: ToolCall):
    # Open a fresh SQLite connection per request to avoid cross-thread reuse errors
    conn = get_conn()
    if os.getenv("AIOPS_DEBUG_LOG"):
        try:
            logger.info("log: writing to %s", str(LOG_PATH))
        except Exception:
            pass
    try:
        name = call.name
        args = call.arguments or {}
        req_id = None
        try:
          # Prefer explicit request_id; fall back to id inside arguments
          rid = args.get("request_id") or args.get("id")
          if isinstance(rid, str):
            req_id = rid
          elif isinstance(rid, (int, float)):
            req_id = str(rid)
        except Exception:
          pass
        log_json(6, "cmdb-mcp", {"name": name, "arguments": args}, "cmdb-mcp request", request_id=req_id)
        try:
            if name == "cmdb.query":
                sql = args.get("sql") or ""
                result = select_sql(conn, sql)
                log_json(11, "cmdb-mcp", result, "cmdb-mcp reply", request_id=req_id)
                return {"ok": True, "result": result}
            elif name == "cmdb.get":
                kind = args.get("kind")
                id_ = args.get("id")
                if not kind or not id_:
                    raise HTTPException(status_code=400, detail="kind and id are required")
                obj = db_get(conn, kind, id_)
                log_json(11, "cmdb-mcp", obj, "cmdb-mcp reply", request_id=req_id)
                return {"ok": True, "result": obj}
            elif name == "cmdb.upsert":
                kind = args.get("kind")
                id_ = args.get("id")
                data = args.get("data")
                if not (kind and id_ and isinstance(data, dict)):
                    raise HTTPException(status_code=400, detail="kind, id, data(object) required")
                res = db_upsert(conn, kind, id_, json.dumps(data, ensure_ascii=False))
                log_json(11, "cmdb-mcp", res, "cmdb-mcp reply", request_id=req_id)
                return {"ok": True, "result": res}
            elif name == "cmdb.search":
                q = args.get("q") or ""
                limit = int(args.get("limit") or 20)
                offset = int(args.get("offset") or 0)
                res = db_search(conn, q, limit, offset)
                log_json(11, "cmdb-mcp", res, "cmdb-mcp reply", request_id=req_id)
                return {"ok": True, "result": res}
            else:
                raise HTTPException(status_code=404, detail=f"unknown tool: {name}")
        except Exception as e:
            log_json(11, "cmdb-mcp", {"error": str(e)}, "cmdb-mcp reply", request_id=req_id)
            return {"ok": False, "error": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass

#!/usr/bin/env python3
# cmdb-mcp/server.py
import os
import sqlite3
from typing import Any, Dict, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
JST = timezone(timedelta(hours=9))
import hashlib, time

__DISPATCHER_TAG__ = hashlib.sha256(open(__file__,'rb').read()).hexdigest()[:12]
print(f"[dispatcher] import tag={__DISPATCHER_TAG__} t={time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}")

DB_PATH = os.getenv("CMDB_DB", "/app/cmdb-mcp/rag.db")
app = FastAPI(title="cmdb-mcp")

@app.get("/health")
def health():
    # Minimal health for ctrl.sh
    info = {}
    try:
        st = os.stat(DB_PATH)
        info["db_path"] = DB_PATH
        info["db_size"] = st.st_size
        info["db_mtime"] = datetime.fromtimestamp(st.st_mtime, JST).isoformat()
    except Exception as e:
        info["db_error"] = str(e)
    return {
        "ok": True,
        "ts_jst": datetime.now(JST).isoformat(),
        "id": None,
        "server_version": "v1",
        "mode": "cmdb",
        "mode_reason": "sqlite/json1/fts5",
        "require_auth": True,
        "base_dir": os.getcwd(),
        "info": info,
    }

class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = {}

def open_db() -> sqlite3.Connection:
    if not os.path.exists(DB_PATH):
        raise RuntimeError(f"CMDB_DB not found: {DB_PATH}")
    cx = sqlite3.connect(DB_PATH, check_same_thread=False)
    cx.row_factory = sqlite3.Row
    return cx

cx = None

def sanity_check(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT name, type FROM sqlite_master WHERE name IN ('docs','docs_fts','objects') ORDER BY name")
    rows = cur.fetchall()
    have = {r["name"]: r["type"] for r in rows}
    # Require docs table strictly (strict mode)
    if "docs" not in have:
        raise RuntimeError("Sanity check failed: 'docs' table not found in SQLite DB.")
    # Log current DB details
    try:
        import time
        st = os.stat(DB_PATH)
        print(f"[cmdb-mcp] CMDB_DB={DB_PATH} size={st.st_size} mtime={time.strftime('%F %T', time.localtime(st.st_mtime))}")
        print(f"[cmdb-mcp] sqlite_master subset={have}")
    except Exception as e:
        print(f"[cmdb-mcp] stat/log error: {e}")

@app.on_event("startup")
def _startup():
    global cx
    cx = open_db()
    sanity_check(cx)

def only_select(sql: str) -> bool:
    s = sql.strip().lower()
    # 許可: SELECT もしくは CTE (WITH ...) から開始
    if s.startswith("select "):
        return True
    if s.startswith("with "):
        # CTE -> 後段に select が含まれるか簡易チェック
        return " select " in s or s.rstrip().endswith(" select")
    return False

@app.post("/tools/call")
def tools_call(payload: ToolCall):
    global cx
    if payload.name == "cmdb.query":
        sql = payload.arguments.get("sql") or ""
        if not only_select(sql):
            if os.getenv("CMDB_DEBUG"):
                print(f"[cmdb-mcp] reject non-select sql={sql[:120]!r}")
            return {"ok": False, "error": "Only SELECT is allowed (or WITH CTE)"}
        try:
            cur = cx.cursor()
            cur.execute(sql)
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
            return {"ok": True, "result": {"columns": cols, "rows": [dict(r) for r in rows], "count": len(rows)}}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    elif payload.name == "diag.db":
        try:
            cur = cx.cursor()
            cur.execute("PRAGMA database_list")
            dblist = [dict(r) for r in cur.fetchall()]
            cur.execute("SELECT name,type FROM sqlite_master ORDER BY name LIMIT 50")
            master = [dict(r) for r in cur.fetchall()]
            return {"ok": True, "result": {"database_list": dblist, "sqlite_master": master, "db_path": DB_PATH}}
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        raise HTTPException(status_code=400, detail=f"Unknown tool: {payload.name}")

# For local run: uvicorn server:app --host 0.0.0.0 --port 9001

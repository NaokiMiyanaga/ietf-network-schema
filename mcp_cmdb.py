import os, json, subprocess, tempfile
from pathlib import Path
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from datetime import datetime
from zoneinfo import ZoneInfo

BASE_DIR = Path(__file__).resolve().parent
APP_DIR = BASE_DIR
SCRIPTS_DIR = BASE_DIR / "scripts"

# ---- JSONL logger (MCP CMDB) ----
_START_TS = datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y%m%d-%H%M%S")
_LOG_DIR = Path(os.getenv("MCP_LOG_DIR", str(BASE_DIR / "logs"))).resolve()
_LOG_DIR.mkdir(parents=True, exist_ok=True)
_LOG_FILE = _LOG_DIR / f"mcp_cmdb_events_{_START_TS}.jsonl"
_REQ_ID: Optional[str] = None

REQUIRE_AUTH = os.getenv("REQUIRE_AUTH", "1") == "1"
MCP_TOKEN = os.getenv("MCP_TOKEN", "")
DEFAULT_DB = os.getenv("IETF_DB", str(BASE_DIR / "rag.db"))

app = FastAPI(title="MCP CMDB (ietf-network-schema)")

def _now_jst():
    return datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()

def _mcp_log(no: int, tag: str, content: Any):
    rec = {"ts_jst": _now_jst(), "no": int(no), "actor": "mcp", "tag": tag, "content": content}
    if _REQ_ID:
        rec["request_id"] = _REQ_ID
    try:
        with _LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass

def _unauth(msg='missing bearer token'):
    body = {"ok": False, "error": {"code": "unauthorized", "message": msg}}
    return JSONResponse(body, status_code=401)

async def _auth(request: Request):
    if not REQUIRE_AUTH:
        return True, None
    got = request.headers.get("authorization", "")
    if not got.startswith("Bearer "):
        return False, _unauth("missing bearer token")
    token = got.split(" ", 1)[1].strip()
    if not MCP_TOKEN or token != MCP_TOKEN:
        return False, _unauth("invalid token")
    return True, None

@app.get("/health")
def health():
    info = {
        "ok": True, "ts_jst": _now_jst(),
        "base_dir": str(BASE_DIR),
        "scripts_dir": str(SCRIPTS_DIR),
        "default_db": DEFAULT_DB,
        "require_auth": REQUIRE_AUTH,
        "token_set": bool(MCP_TOKEN),
    }
    try:
        if os.getenv("MCP_LOG_HEALTH", "0") == "1":
            _mcp_log(-1, "health", info)
    except Exception:
        pass
    return info

@app.get("/tools/list")
def tools_list():
    tools = [
        {
            "id": "cmdb.jp_query",
            "title": "Japanese prompt → CMDB FTS query",
            "description": "Parse a Japanese prompt into FTS5 query + filters and search SQLite (docs table).",
            "tags": ["cmdb", "query", "fts", "ietf-network"],
            "inputs_schema": {
                "type": "object",
                "properties": {
                    "q": {"type": "string", "description": "Japanese prompt (e.g., L3SW1 の MTU 1500)"},
                    "db": {"type": "string", "description": "Path to SQLite DB (default: ietf-network-schema/rag.db)"},
                    "k": {"type": "integer", "description": "Top-K hits", "default": 5}
                },
                "required": ["q"]
            },
            "examples": ["L3SW1:ae1 の状態は？", "リンクの遅延 2ms 以上"],
            "version": "v1"
        }
    ]
    return JSONResponse({"ok": True, "tools": tools, "ts_jst": _now_jst(), "server_version": "v1"})

def _run_jp_query(db: str, q: str, k: int | None = None) -> Dict[str, Any]:
    py = Path("/usr/bin/python3")
    if not py.exists():
        py = Path("/usr/local/bin/python3")
    if not py.exists():
        py = Path("python3")
    script = SCRIPTS_DIR / "jp_query.py"
    args = [str(py), str(script), "--db", db, "--q", q]
    if isinstance(k, int) and k > 0:
        args += ["--k", str(k)]
    p = subprocess.Popen(args, cwd=str(BASE_DIR), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    out, err = p.communicate()
    try:
        data = json.loads(out)
    except Exception:
        data = {"raw": out}
    return {"rc": p.returncode, "stdout": out, "stderr": err, "data": data}

@app.post("/run")
async def run(request: Request):
    ok, resp = await _auth(request)
    if not ok:
        return resp
    body = await request.json()
    # capture request_id for correlation (if provided by client)
    global _REQ_ID
    try:
        _REQ_ID = body.get("request_id") if isinstance(body, dict) else None
    except Exception:
        _REQ_ID = None
    _mcp_log(6, "mcp request", {"body": body})
    # Accept both {payload:{tool,vars}} and legacy {payload:{playbook,vars}}
    payload = (body.get("payload") or {}) if isinstance(body, dict) else {}
    tool = payload.get("tool") or payload.get("playbook")
    vars_obj = payload.get("vars") if isinstance(payload, dict) else None
    if not tool:
        err = {"ok": False, "error": {"code": "invalid_args", "message": "payload.tool is required"}}
        _mcp_log(11, "mcp reply", {"status": 400, **err})
        return JSONResponse(err, status_code=400)
    if tool != "cmdb.jp_query":
        err = {"ok": False, "error": {"code": "unknown_tool", "message": f"unsupported tool: {tool}"}}
        _mcp_log(11, "mcp reply", {"status": 400, **err})
        return JSONResponse(err, status_code=400)
    q = (vars_obj or {}).get("q") if isinstance(vars_obj, dict) else None
    if not isinstance(q, str) or not q.strip():
        err = {"ok": False, "error": {"code": "invalid_args", "message": "vars.q (prompt) is required"}}
        _mcp_log(11, "mcp reply", {"status": 400, **err})
        return JSONResponse(err, status_code=400)
    db = (vars_obj or {}).get("db") if isinstance(vars_obj, dict) else None
    if not isinstance(db, str) or not db.strip():
        db = DEFAULT_DB
    k = (vars_obj or {}).get("k") if isinstance(vars_obj, dict) else None
    try:
        k_val = int(k) if k is not None else None
    except Exception:
        k_val = None
    # No.8 equivalent: SQL/FTS リクエスト（cmdb）
    _mcp_log(8, "mcp sql request", {"tool": tool, "vars": {"db": db, "q": q, **({"k": k_val} if k_val else {})}})
    rep = _run_jp_query(db, q.strip(), k_val)
    summary = None
    try:
        d = rep.get("data") or {}
        hits = d.get("hits") if isinstance(d, dict) else None
        n = len(hits) if isinstance(hits, list) else 0
        summary = f"CMDB 検索: 上位 {n} 件を返しました。"
    except Exception:
        summary = "CMDB 検索を実行しました。"
    out = {
        "ok": rep.get("rc") == 0,
        "summary": summary,
        "ts_jst": _now_jst(),
        "debug": {"no8_request": {"tool": tool, "vars": {"db": db, "q": q, **({"k": k_val} if k_val else {})}},
                  "no9_reply": rep},
    }
    try:
        _mcp_log(9, "mcp sql reply", rep)
        _mcp_log(10, "mcp cmdb output", {"summary": summary})
        slim = dict(out)
        if isinstance(slim.get("debug"), dict):
            slim.pop("debug")
        _mcp_log(11, "mcp reply", {"status": 200, **slim})
    except Exception:
        pass
    return out

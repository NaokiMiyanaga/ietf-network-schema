import os, json, subprocess, tempfile, sqlite3, re, time
from pathlib import Path
from typing import Dict, Any, Optional, Tuple, List
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
CMDB_USE_GPT = os.getenv("CMDB_USE_GPT", "0") == "1"
CMDB_GPT_MODEL = os.getenv("CMDB_GPT_MODEL", os.getenv("OPENAI_MODEL", "gpt-4o-mini"))
SERVER_VERSION = os.getenv("MCP_SERVER_VERSION", "v1")
MAX_ROWS = max(1, int(os.getenv("CMDB_QUERY_MAX_ROWS", "1000")))
_SQL_FORBIDDEN = re.compile(r"\b(UPDATE|DELETE|INSERT|DROP|ALTER|ATTACH|REINDEX|VACUUM|CREATE|REPLACE|PRAGMA|TRIGGER)\b", re.IGNORECASE)

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


@app.get("/schema")
async def schema(request: Request):
    ok, resp = await _auth(request)
    if not ok:
        return resp
    rid = None
    try:
        rid = request.headers.get("X-Request-Id")
    except Exception:
        rid = None
    body = {
        "ok": True,
        "id": rid,
        "ts_jst": _now_jst(),
        "result": {
            "protocol": "mcp/1.0",
            "transport": "http",
            "server_version": SERVER_VERSION,
            "capabilities": {"tools": True},
            "endpoints": [
                {"path": "/tools/list", "method": "GET"},
                {"path": "/tools/call", "method": "POST"},
            ],
        },
    }
    return JSONResponse(body, status_code=200)

@app.get("/tools/list")
def tools_list():
    tools = [
        {
            "id": "cmdb.query",
            "title": "Execute read-only SQL against CMDB",
            "description": "Run SELECT/CTE statements on the CMDB SQLite database (read-only).",
            "tags": ["cmdb", "query", "sql"],
            "inputs_schema": {
                "type": "object",
                "properties": {
                    "sql": {"type": "string", "description": "SELECT ... statement"},
                    "db": {"type": "string", "description": "Optional SQLite DB override"},
                },
                "required": ["sql"],
            },
            "version": SERVER_VERSION,
        },
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
            "version": SERVER_VERSION
        },
    ]
    return JSONResponse({"ok": True, "tools": tools, "ts_jst": _now_jst(), "server_version": SERVER_VERSION})


def _gpt_rewrite_query(orig_q: str) -> dict | None:
    """Optional: rewrite natural language into better FTS terms/filters via OpenAI.
    Returns a dict like {"q": "...", "k": int?} or None on failure/disabled.
    """
    if not CMDB_USE_GPT:
        return None
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    try:
        import urllib.request, json as _json
        url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com") + "/v1/chat/completions"
        sys_prompt = (
            "You translate Japanese/NL network questions into a concise SQLite FTS5 text query. "
            "Return a compact JSON object with keys: q (string), k (int optional). "
            "Prefer ascii-ish tokens present in CMDB like mtu, duplex, up, down, L3SW1, r1, r2, r1-mgmt. "
            "If a node:tp like L3SW1:ae1 is implied, include it verbatim in q. "
            "If unsure, echo back the important tokens only."
        )
        user_prompt = f"Input: {orig_q}\nReturn JSON only: {{\"q\":<fts terms>,\"k\":<int?>}}"
        body = {
            "model": CMDB_GPT_MODEL,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
        }
        req = urllib.request.Request(
            url,
            data=_json.dumps(body).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=float(os.getenv("CMDB_GPT_TIMEOUT", "15"))) as resp:
            raw = resp.read().decode("utf-8")
        try:
            rep = _json.loads(raw)
            content = rep.get("choices", [{}])[0].get("message", {}).get("content", "{}")
            out = _json.loads(content)
            # sanity
            if isinstance(out, dict) and out.get("q"):
                return out
        except Exception:
            pass
    except Exception:
        return None
    return None

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


def _sanitize_sql(raw_sql: Any) -> Tuple[str, Optional[str]]:
    if not isinstance(raw_sql, str):
        return "", "sql must be a string"
    sql = raw_sql.strip()
    if not sql:
        return "", "sql must not be empty"
    sql = re.sub(r";\s*$", "", sql)
    lowered = sql.lower()
    if not (lowered.startswith("select") or lowered.startswith("with ")):
        return "", "only SELECT or WITH statements are allowed"
    if _SQL_FORBIDDEN.search(sql):
        return "", "detected forbidden keyword in sql"
    return sql, None


def _execute_select(db_path: str, sql: str) -> Tuple[List[Dict[str, Any]], List[str], bool, float]:
    started = time.time()
    truncated = False
    rows: List[Dict[str, Any]] = []
    columns: List[str] = []
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(sql)
        description = cur.description or []
        columns = [col[0] for col in description]
        for idx, row in enumerate(cur):
            if idx < MAX_ROWS:
                row_dict = {col: row[col] for col in columns} if columns else dict(row)
                rows.append(row_dict)
            else:
                truncated = True
                break
    finally:
        conn.close()
    duration_ms = (time.time() - started) * 1000
    return rows, columns, truncated, duration_ms


def _handle_cmdb_query(args: Dict[str, Any], rid: Optional[str]) -> Tuple[Dict[str, Any], int]:
    sql_raw = args.get("sql") if isinstance(args, dict) else None
    sql, err = _sanitize_sql(sql_raw)
    if err:
        body: Dict[str, Any] = {
            "ok": False,
            "id": rid,
            "ts_jst": _now_jst(),
            "error": {"code": "invalid_sql", "message": err},
        }
        if _REQ_ID:
            body["request_id"] = _REQ_ID
        _mcp_log(11, "mcp reply", {"status": 400, **body})
        return body, 400
    db_path = args.get("db") if isinstance(args, dict) else None
    if not isinstance(db_path, str) or not db_path.strip():
        db_path = DEFAULT_DB
    db_path = db_path.strip()
    _mcp_log(8, "mcp sql request", {"tool": "cmdb.query", "sql": sql, "db": db_path})
    try:
        rows, columns, truncated, duration_ms = _execute_select(db_path, sql)
    except Exception as exc:
        body = {
            "ok": False,
            "id": rid,
            "ts_jst": _now_jst(),
            "error": {"code": "query_failed", "message": str(exc)},
        }
        if _REQ_ID:
            body["request_id"] = _REQ_ID
        _mcp_log(11, "mcp reply", {"status": 500, **body})
        return body, 500
    summary = f"Returned {len(rows)} row(s)"
    result: Dict[str, Any] = {
        "sql": sql,
        "rows": rows,
        "columns": columns,
        "count": len(rows),
        "duration_ms": round(duration_ms, 2),
        "db": db_path,
    }
    if truncated:
        result["truncated"] = True
        result["notice"] = f"results truncated to {MAX_ROWS} row(s)"
    _mcp_log(9, "mcp sql reply", {"rows": len(rows), "duration_ms": round(duration_ms, 2), "truncated": truncated})
    _mcp_log(10, "mcp cmdb output", {"summary": summary})
    body = {
        "ok": True,
        "id": rid,
        "ts_jst": _now_jst(),
        "result": result,
        "summary": summary,
    }
    if _REQ_ID:
        body["request_id"] = _REQ_ID
    _mcp_log(11, "mcp reply", {"status": 200, **{k: body[k] for k in body if k != "result"}, "count": len(rows)})
    return body, 200


def _handle_cmdb_jp_query(args: Dict[str, Any], rid: Optional[str]) -> Tuple[Dict[str, Any], int]:
    tool = "cmdb.jp_query"
    q = args.get("q") if isinstance(args, dict) else None
    if not isinstance(q, str) or not q.strip():
        body: Dict[str, Any] = {
            "ok": False,
            "id": rid,
            "ts_jst": _now_jst(),
            "error": {"code": "invalid_args", "message": "vars.q (prompt) is required"},
        }
        if _REQ_ID:
            body["request_id"] = _REQ_ID
        _mcp_log(11, "mcp reply", {"status": 400, **body})
        return body, 400
    db = args.get("db") if isinstance(args, dict) else None
    if not isinstance(db, str) or not db.strip():
        db = DEFAULT_DB
    k = args.get("k") if isinstance(args, dict) else None
    try:
        k_val = int(k) if k is not None else None
    except Exception:
        k_val = None
    plan = None
    try:
        plan = _gpt_rewrite_query(q)
    except Exception:
        plan = None
    q_eff = str((plan or {}).get("q") or q).strip()
    if isinstance(plan, dict) and isinstance(plan.get("k"), int) and not k_val:
        k_val = int(plan.get("k"))
    if plan:
        _mcp_log(7, "mcp gpt input", {"prompt": q, "rewrite": plan})
    req_vars = {"db": db, "q": q_eff}
    if k_val:
        req_vars["k"] = k_val
    _mcp_log(8, "mcp sql request", {"tool": tool, "vars": req_vars})
    rep = _run_jp_query(db, q_eff, k_val)
    summary = None
    try:
        d = rep.get("data") or {}
        hits = d.get("hits") if isinstance(d, dict) else None
        n = len(hits) if isinstance(hits, list) else 0
        summary = f"CMDB 検索: 上位 {n} 件を返しました。"
    except Exception:
        summary = "CMDB 検索を実行しました。"
    body: Dict[str, Any] = {
        "ok": rep.get("rc") == 0,
        "id": rid,
        "ts_jst": _now_jst(),
        "summary": summary,
        "debug": {
            "no8_request": {"tool": tool, "vars": req_vars},
            "no9_reply": rep,
        },
    }
    if _REQ_ID:
        body["request_id"] = _REQ_ID
    _mcp_log(9, "mcp sql reply", rep)
    _mcp_log(10, "mcp cmdb output", {"summary": summary})
    slim = dict(body)
    slim.pop("result", None)
    slim.pop("debug", None)
    _mcp_log(11, "mcp reply", {"status": 200 if rep.get("rc") == 0 else 500, **slim})
    return body, (200 if rep.get("rc") == 0 else 500)


@app.post("/tools/call")
async def tools_call(request: Request):
    ok, resp = await _auth(request)
    if not ok:
        return resp
    body = await request.json()
    global _REQ_ID
    try:
        _REQ_ID = body.get("id") or body.get("request_id")
    except Exception:
        _REQ_ID = None
    _mcp_log(6, "mcp request", {"body": body})
    name = body.get("name") or body.get("tool")
    args = body.get("arguments") or body.get("vars") or {}
    if not isinstance(args, dict):
        args = {"value": args}
    rid = body.get("id")
    if name == "cmdb.query":
        result_body, status = _handle_cmdb_query(args, rid)
        return JSONResponse(result_body, status_code=status)
    if name == "cmdb.jp_query":
        result_body, status = _handle_cmdb_jp_query(args, rid)
        return JSONResponse(result_body, status_code=status)
    err = {
        "ok": False,
        "id": rid,
        "ts_jst": _now_jst(),
        "error": {"code": "unknown_tool", "message": f"unsupported tool: {name}"},
    }
    if _REQ_ID:
        err["request_id"] = _REQ_ID
    _mcp_log(11, "mcp reply", {"status": 400, **err})
    return JSONResponse(err, status_code=400)


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
    args = vars_obj if isinstance(vars_obj, dict) else {}
    rid = payload.get("id") if isinstance(payload, dict) else None
    if tool == "cmdb.query":
        result_body, status = _handle_cmdb_query(args, rid)
        return JSONResponse(result_body, status_code=status)
    if tool == "cmdb.jp_query":
        result_body, status = _handle_cmdb_jp_query(args, rid)
        return JSONResponse(result_body, status_code=status)
    err = {"ok": False, "error": {"code": "unknown_tool", "message": f"unsupported tool: {tool}"}}
    _mcp_log(11, "mcp reply", {"status": 400, **err})
    return JSONResponse(err, status_code=400)

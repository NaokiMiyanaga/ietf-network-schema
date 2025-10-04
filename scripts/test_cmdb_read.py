#!/usr/bin/env python3
"""Read-only CMDB test helper analogous to test_network_overview.

Features:
  - Health check (/health)
  - cmdb.query execution (SELECT / WITH) via /tools/call
  - Optional diag.db call for schema introspection
  - Offline SQLite fallback if API unreachable (read-only)
  - JSON summary output (success, counts, columns)

Exit codes:
  0 success
  2 HTTP / connection failure unrecoverable
  3 Query error / invalid SQL (non-select rejected)
  4 Offline fallback used but DB path invalid

Usage examples:
  python scripts/test_cmdb_read.py --base-url http://localhost:9001 \
      --sql "SELECT name FROM sqlite_master WHERE type='table'" --json

  Offline fallback:
  python scripts/test_cmdb_read.py --sqlite ./rag.db --sql "SELECT COUNT(*) AS docs FROM docs" --json
"""
from __future__ import annotations
import argparse, json, os, sys, sqlite3, urllib.request, urllib.error
from typing import Any, Dict

DEFAULT_SQL = "SELECT name,type FROM sqlite_master ORDER BY name LIMIT 20"

def http_json(url: str, method: str = "GET", data: Dict[str, Any] | None = None, timeout: int = 10) -> Dict[str, Any]:
    try:
        if data is not None:
            payload = json.dumps(data).encode("utf-8")
            req = urllib.request.Request(url, method=method, data=payload, headers={"Content-Type": "application/json"})
        else:
            req = urllib.request.Request(url, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code} {e.reason}"}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def is_select_sql(sql: str) -> bool:
    s = sql.strip().lower()
    if s.startswith("select "):
        return True
    if s.startswith("with "):
        return " select " in s or s.endswith(" select")
    return False


def run_api(base: str, sql: str, do_diag: bool) -> Dict[str, Any]:
    health = http_json(base.rstrip('/') + "/health")
    if not health.get("ok"):
        return {"ok": False, "phase": "health", "error": health.get("error")}
    diag = None
    if do_diag:
        diag = http_json(base.rstrip('/') + "/tools/call", method="POST", data={"name": "diag.db", "arguments": {}})
    if not is_select_sql(sql):
        return {"ok": False, "phase": "sql-validate", "error": "Only SELECT/CTE allowed"}
    query_payload = {"name": "cmdb.query", "arguments": {"sql": sql}}
    query = http_json(base.rstrip('/') + "/tools/call", method="POST", data=query_payload)
    return {"ok": bool(query.get("ok")), "phase": "query", "health": health, "diag": diag, "query": query}


def run_sqlite(path: str, sql: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"ok": False, "error": f"sqlite path not found: {path}"}
    if not is_select_sql(sql):
        return {"ok": False, "error": "Only SELECT/CTE allowed"}
    try:
        cx = sqlite3.connect(path)
        cx.row_factory = sqlite3.Row
        cur = cx.cursor()
        cur.execute(sql)
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return {"ok": True, "result": {"columns": cols, "rows": [dict(r) for r in rows], "count": len(rows)}}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def summarize_query(result: Dict[str, Any]) -> Dict[str, Any]:
    if not result.get("ok"):
        return {"ok": False, "error": result.get("error"), "phase": result.get("phase")}
    q = result.get("query") or result.get("result") or {}
    if not q:
        return {"ok": False, "error": "no query result"}
    # unify structure for API vs sqlite path
    rows = q.get("result", {}).get("rows") if "result" in q else q.get("rows")
    cols = q.get("result", {}).get("columns") if "result" in q else q.get("columns")
    count = q.get("result", {}).get("count") if "result" in q else q.get("count")
    return {"ok": True, "columns": cols, "count": count, "sample": rows[:5] if rows else []}


def main():
    ap = argparse.ArgumentParser(description="CMDB read-only test helper")
    ap.add_argument("--base-url", default="http://localhost:9001")
    ap.add_argument("--sql", default=DEFAULT_SQL)
    ap.add_argument("--diag", action="store_true", help="Include diag.db call")
    ap.add_argument("--sqlite", help="Offline fallback sqlite path")
    ap.add_argument("--json", action="store_true", help="Print full raw structures")
    args = ap.parse_args()

    used_offline = False
    result: Dict[str, Any]
    api_result = run_api(args.base_url, args.sql, args.diag)
    if not api_result.get("ok"):
        # Try offline if provided
        if args.sqlite:
            offline = run_sqlite(args.sqlite, args.sql)
            offline_sum = summarize_query(offline)
            used_offline = True
            result = {"api": api_result, "offline": offline, "summary": offline_sum, "ok": offline_sum.get("ok"), "offline_mode": True}
        else:
            print(json.dumps({"ok": False, "error": api_result.get("error"), "phase": api_result.get("phase", "api"), "offline_mode": False}, ensure_ascii=False))
            sys.exit(2)
    else:
        summary = summarize_query(api_result)
        result = {"ok": summary.get("ok"), "summary": summary, "api": api_result, "offline_mode": False}

    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    else:
        if result.get("ok"):
            print(json.dumps({"ok": True, "count": result["summary"]["count"], "columns": result["summary"]["columns"], "offline_mode": used_offline}, ensure_ascii=False))
        else:
            print(json.dumps(result, ensure_ascii=False))

    if not result.get("ok"):
        # Differentiate exit codes
        if used_offline and not result.get("ok"):
            sys.exit(4)
        else:
            sys.exit(3)

if __name__ == "__main__":
    main()

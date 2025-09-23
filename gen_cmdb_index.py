#!/usr/bin/env python3
"""Generate a simple cmdb_index.yaml for the CMDB MCP server directory.

Purpose:
  Run INSIDE the cmdb-mcp build context (same dir as server.py) so that
  server.py can load `cmdb_index.yaml` without depending on assistant repo paths.

Usage:
  python gen_cmdb_index.py --init        # create cmdb_index.yaml if absent
  python gen_cmdb_index.py --force       # overwrite existing after backup
  python gen_cmdb_index.py --show        # print current (if exists)
  python gen_cmdb_index.py --add id 'SELECT ...' --desc '...' [--params a,b]

Format (list):
- id: device_list
  kind: cmdb
  description: "List devices"
  params: []
  op_class: cmdb-read
  side_effect: false
  sql: "SELECT id, hostname FROM devices ORDER BY id LIMIT 50;"

Notes:
  * Keeps backup: cmdb_index.yaml.bak-YYYYMMDD-HHMMSS on overwrite.
  * Duplicate id on --add will update existing entry unless --no-update is given.
"""
from __future__ import annotations
import argparse, sys, yaml, datetime, os
from pathlib import Path
from typing import List, Dict, Any

INDEX_PATH = Path("cmdb_index.yaml")
TS_FMT = "%Y%m%d-%H%M%S"


def load_index() -> List[Dict[str, Any]]:
    if not INDEX_PATH.exists():
        return []
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or []
    return data if isinstance(data, list) else []


def write_index(items: List[Dict[str, Any]]):
    with INDEX_PATH.open("w", encoding="utf-8") as f:
        yaml.safe_dump(items, f, allow_unicode=True, sort_keys=False)


def ensure_backup():
    if INDEX_PATH.exists():
        ts = datetime.datetime.now().strftime(TS_FMT)
        bak = INDEX_PATH.with_suffix(INDEX_PATH.suffix + f".bak-{ts}")
        INDEX_PATH.rename(bak)
        print(f"[INFO] backup: {bak}", file=sys.stderr)


def cmd_init(force: bool):
    if INDEX_PATH.exists() and not force:
        print("[SKIP] cmdb_index.yaml already exists (use --force to overwrite)")
        return
    ensure_backup() if INDEX_PATH.exists() else None
    sample = [
        {
            "id": "device_list",
            "kind": "cmdb",
            "description": "List devices (sample)",
            "params": [],
            "op_class": "cmdb-read",
            "side_effect": False,
            "sql": "SELECT id, hostname FROM devices ORDER BY id LIMIT 50;",
        }
    ]
    write_index(sample)
    print("[OK] initialized cmdb_index.yaml (1 sample)")


def cmd_add(id_: str, sql: str, desc: str, params: List[str], allow_update: bool):
    items = load_index()
    found = None
    for it in items:
        if it.get("id") == id_:
            found = it
            break
    if found and not allow_update:
        print(f"[ERR] id '{id_}' already exists (use --allow-update to modify)", file=sys.stderr)
        sys.exit(2)
    if found:
        found.update({
            "sql": sql,
            "description": desc or found.get("description") or "",
            "params": params or found.get("params") or [],
        })
        print(f"[OK] updated id '{id_}'")
    else:
        items.append({
            "id": id_,
            "kind": "cmdb",
            "description": desc,
            "params": params,
            "op_class": "cmdb-read",
            "side_effect": False,
            "sql": sql,
        })
        print(f"[OK] added id '{id_}'")
    write_index(sorted(items, key=lambda x: x.get("id") or ""))


def main():
    ap = argparse.ArgumentParser(description="Manage cmdb_index.yaml inside cmdb-mcp directory")
    ap.add_argument("--init", action="store_true", help="Create sample index if absent")
    ap.add_argument("--force", action="store_true", help="Force overwrite on --init")
    ap.add_argument("--show", action="store_true", help="Print current index to stdout")
    ap.add_argument("--add", metavar="ID", help="Add or update an intent id")
    ap.add_argument("--sql", metavar="SQL", help="SQL for --add")
    ap.add_argument("--desc", metavar="TEXT", default="", help="Description for --add")
    ap.add_argument("--params", metavar="CSV", help="Comma separated params")
    ap.add_argument("--allow-update", action="store_true", help="Permit updating existing id")
    args = ap.parse_args()

    if args.init:
        cmd_init(force=args.force)
    if args.add:
        if not args.sql:
            print("--sql required with --add", file=sys.stderr)
            sys.exit(1)
        params = [p.strip() for p in (args.params.split(",") if args.params else []) if p.strip()]
        cmd_add(args.add, args.sql, args.desc, params, args.allow_update)
    if args.show:
        items = load_index()
        import yaml as _y
        _y.safe_dump(items, sys.stdout, allow_unicode=True, sort_keys=False)

    if not any([args.init, args.add, args.show]):
        ap.print_help()

if __name__ == "__main__":
    main()

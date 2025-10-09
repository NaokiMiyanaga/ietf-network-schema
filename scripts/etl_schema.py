#!/usr/bin/env python3
"""Schema ensure helper for CMDB routing extensions.

Usage:
    from etl_schema import ensure_schema
    ensure_schema(conn)

Idempotent: runs DDL in cmdb_schema.sql once per version.
Tracks version using schema_meta.version (INTEGER).

Future: append migration blocks (version > 1) to this file or an accompanying migrations dir.
"""
from __future__ import annotations
import sqlite3, pathlib, re
from typing import Optional

SCHEMA_SQL_PATHS = [
    pathlib.Path(__file__).resolve().parent.parent.parent / 'ietf-network-schema' / 'cmdb_schema.sql',  # project root variant
    pathlib.Path(__file__).resolve().parent / 'cmdb_schema.sql',  # local fallback
]

_VERSION_RE = re.compile(r"INSERT OR REPLACE INTO schema_meta\(version, applied_at\)\s+VALUES\s*\((\d+),")

_cached_applied_version: Optional[int] = None

def _read_sql() -> str:
    for p in SCHEMA_SQL_PATHS:
        if p.exists():
            return p.read_text(encoding='utf-8')
    raise FileNotFoundError("cmdb_schema.sql not found in expected paths")

def _extract_target_version(sql: str) -> int:
    m = _VERSION_RE.search(sql)
    if m:
        return int(m.group(1))
    return 1

def _current_version(conn: sqlite3.Connection) -> int:
    try:
        cur = conn.execute("SELECT version FROM schema_meta ORDER BY version DESC LIMIT 1")
        row = cur.fetchone()
        if row:
            return int(row[0])
    except sqlite3.Error:
        return 0
    return 0

def ensure_schema(conn: sqlite3.Connection, verbose: bool = False) -> int:
    global _cached_applied_version
    if _cached_applied_version is not None:
        return _cached_applied_version
    sql = _read_sql()
    target = _extract_target_version(sql)
    current = _current_version(conn)
    if current >= target:
        _cached_applied_version = current
        if verbose:
            print(f"[schema] already at version {current}")
        return current
    if verbose:
        print(f"[schema] applying schema version {target} (current={current})")
    # Execute whole SQL script
    try:
        conn.executescript(sql)
    except sqlite3.Error as e:
        raise RuntimeError(f"schema apply failed: {e}")
    applied = _current_version(conn)
    _cached_applied_version = applied
    if verbose:
        print(f"[schema] done version={applied}")
    return applied

if __name__ == '__main__':  # manual test
    import sys
    path = pathlib.Path(sys.argv[1] if len(sys.argv)>1 else './test_cmdb.sqlite3')
    cx = sqlite3.connect(str(path))
    v = ensure_schema(cx, verbose=True)
    print('version', v)

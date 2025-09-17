from __future__ import annotations
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_DB = Path(os.getenv("CMDB_DB_PATH", "./data/cmdb.sqlite3")).expanduser()

DDL = [
    """CREATE TABLE IF NOT EXISTS objects (
        kind TEXT NOT NULL,
        id   TEXT NOT NULL,
        data TEXT NOT NULL,
        PRIMARY KEY(kind, id)
    ) WITHOUT ROWID;""",

    """CREATE VIRTUAL TABLE IF NOT EXISTS objects_fts USING fts5(
        kind, id, text,
        content='',
        tokenize='porter'
    );""",

    """CREATE TRIGGER IF NOT EXISTS trg_objects_ai AFTER INSERT ON objects BEGIN
        INSERT INTO objects_fts(rowid, kind, id, text)
        VALUES ((SELECT COALESCE(MAX(rowid)+1,1) FROM objects_fts),
                NEW.kind, NEW.id, json_extract(NEW.data, '$'));
    END;""",

    """CREATE TRIGGER IF NOT EXISTS trg_objects_au AFTER UPDATE ON objects BEGIN
        DELETE FROM objects_fts WHERE kind=OLD.kind AND id=OLD.id;
        INSERT INTO objects_fts(rowid, kind, id, text)
        VALUES ((SELECT COALESCE(MAX(rowid)+1,1) FROM objects_fts),
                NEW.kind, NEW.id, json_extract(NEW.data, '$'));
    END;""",

    """CREATE TRIGGER IF NOT EXISTS trg_objects_ad AFTER DELETE ON objects BEGIN
        DELETE FROM objects_fts WHERE kind=OLD.kind AND id=OLD.id;
    END;""",
]

def get_conn(path: Path = DEFAULT_DB) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI のスレッドプールで別スレッドから使われる可能性があるため
    # スレッドチェックを無効化して安全に共有できるようにする
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    for stmt in DDL:
        conn.executescript(stmt)

def upsert(conn: sqlite3.Connection, kind: str, id_: str, data_json: str) -> Dict[str, Any]:
    conn.execute(
        "INSERT INTO objects(kind,id,data) VALUES(?,?,?) "
        "ON CONFLICT(kind,id) DO UPDATE SET data=excluded.data",
        (kind, id_, data_json),
    )
    conn.commit()
    return {"ok": True, "kind": kind, "id": id_}

def get(conn: sqlite3.Connection, kind: str, id_: str) -> Optional[Dict[str, Any]]:
    cur = conn.execute("SELECT kind,id,data FROM objects WHERE kind=? AND id=?", (kind, id_))
    row = cur.fetchone()
    if not row:
        return None
    return {"kind": row["kind"], "id": row["id"], "data": row["data"]}

def search(conn: sqlite3.Connection, q: str, limit: int = 20, offset: int = 0):
    cur = conn.execute(
        "SELECT kind,id FROM objects_fts WHERE objects_fts MATCH ? LIMIT ? OFFSET ?",
        (q, limit, offset),
    )
    hits = [{"kind": r["kind"], "id": r["id"]} for r in cur.fetchall()]
    return {"items": hits, "count": len(hits)}

def select_sql(conn: sqlite3.Connection, sql: str):
    if sql.strip().split()[0].lower() != "select":
        raise ValueError("Only SELECT is allowed")
    cur = conn.execute(sql)
    cols = [c[0] for c in cur.description]
    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"columns": cols, "rows": rows, "count": len(rows)}

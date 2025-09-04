#!/usr/bin/env python3
"""
Load objects.jsonl into SQLite with FTS5 (saved-content mode).
- Creates two tables:
  - objects(id, json) : raw JSON per line
  - docs(fts5)        : searchable columns + json, stores its own content (NO contentless)
- Builds robust search text even if obj['text'] is missing.
"""

import json
import sqlite3
import pathlib
import os
import argparse
from typing import Dict

DB_PATH = "rag.db"
JSONL_PATH = "outputs/objects.jsonl"  # ETL で作成されたファイル

def make_text(obj: Dict) -> str:
    """
    Build FTS text:
      - Always include: type, network-id, node-id, tp-id, link-id
      - If obj['text'] exists, append it
      - Append compact JSON string so attribute names/values are searchable
    """
    parts = []
    for k in ["type", "network-id", "node-id", "tp-id", "link-id"]:
        v = obj.get(k)
        if v:
            parts.append(str(v))
    t = obj.get("text")
    if t:
        parts.append(str(t))
    parts.append(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
    return " ".join(parts)

def ensure_schema(cur: sqlite3.Cursor) -> None:
    # Raw storage
    cur.execute("""
    CREATE TABLE IF NOT EXISTS objects (
      id INTEGER PRIMARY KEY,
      json TEXT NOT NULL
    );
    """)
    # FTS5 with saved content (NO content='')
    cur.execute("""
    CREATE VIRTUAL TABLE IF NOT EXISTS docs
    USING fts5(
      text,
      type,
      network_id,
      node_id,
      tp_id,
      link_id,
      json
    );
    """)

def load_jsonl(cur: sqlite3.Cursor, jsonl_path: pathlib.Path) -> int:
    n = 0
    with jsonl_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            blob = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

            # objects（元データ）
            cur.execute("INSERT INTO objects(json) VALUES (?)", [blob])

            # docs（FTS用）
            text = make_text(obj)
            typ  = str(obj.get("type") or "")
            net  = str(obj.get("network-id") or "")
            node = str(obj.get("node-id") or "")
            tpid = str(obj.get("tp-id") or "")
            link = str(obj.get("link-id") or "")
            cur.execute(
                "INSERT INTO docs(text,type,network_id,node_id,tp_id,link_id,json) VALUES (?,?,?,?,?,?,?)",
                [text, typ, net, node, tpid, link, blob]
            )
            n += 1
    return n

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DB_PATH, help="SQLite DB path (default: rag.db)")
    ap.add_argument("--jsonl", default=JSONL_PATH, help="JSONL path (default: outputs/objects.jsonl)")
    ap.add_argument("--reset", action="store_true", help="Remove existing DB before loading")
    args = ap.parse_args()

    db = str(args.db)
    jsonl = pathlib.Path(args.jsonl)

    if not jsonl.exists():
        raise SystemExit(f"[ERROR] JSONL not found: {jsonl}")

    if args.reset and os.path.exists(db):
        os.remove(db)

    conn = sqlite3.connect(db)
    cur = conn.cursor()
    ensure_schema(cur)

    # すでに docs にデータがあればスキップ（必要なら削除して再投入）
    cur.execute("SELECT COUNT(*) FROM docs;")
    before = cur.fetchone()[0]

    if before == 0:
        inserted = load_jsonl(cur, jsonl)
        conn.commit()
        print(f"Loaded {inserted} rows into {db}")
    else:
        print(f"{db} already has {before} rows; skip loading")

    # 確認用のサンプル出力
    cur.execute("SELECT rowid,type,network_id,node_id,tp_id, substr(text,1,80) FROM docs LIMIT 5;")
    rows = cur.fetchall()
    print("[SAMPLE]")
    for r in rows:
        print(" ", r)

    conn.close()

if __name__ == "__main__":
    main()

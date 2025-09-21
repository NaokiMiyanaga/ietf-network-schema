#!/usr/bin/env python3
"""Seed the CMDB with a minimal fixture set.

Usage:
  python scripts/seed_cmdb.py --db ./data/cmdb.sqlite3

Idempotent: upserts same objects.
"""
import json, argparse, time
from pathlib import Path
from db import get_conn, init_db, upsert

FIXTURES = [
    ("node", "r1", {"role":"router","vendor":"cisco","asn":65001,"interfaces":["ge-0/0/0","ge-0/0/1"]}),
    ("node", "r2", {"role":"router","vendor":"juniper","asn":65002,"interfaces":["ge-0/0/0","ge-0/0/1"]}),
    ("node", "l2a", {"role":"switch","vendor":"arista","stack":1}),
    ("node", "l2b", {"role":"switch","vendor":"arista","stack":2}),
    ("link", "r1-r2", {"a":"r1","b":"r2","type":"p2p"}),
]

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="./data/cmdb.sqlite3")
    args = ap.parse_args()
    db_path = Path(args.db)
    conn = get_conn(db_path)
    init_db(conn)
    for kind, id_, data in FIXTURES:
        upsert(conn, kind, id_, json.dumps(data, ensure_ascii=False))
    print(f"Seeded {len(FIXTURES)} objects into {db_path}")

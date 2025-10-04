#!/usr/bin/env python3
"""CMDB Ingest Tool (network overview artifact)

Usage:
  python tools/cmdb_ingest_network.py --db path/to/rag.db --file artifacts/network_overview.json

Reads a normalized network overview JSON (see assistant/network_overview_schema.md) and upserts rows
into a generic `objects` table (created if missing) with columns:
  id INTEGER PRIMARY KEY AUTOINCREMENT
  kind TEXT NOT NULL
  ext_id TEXT NOT NULL
  updated_at TEXT NOT NULL
  payload TEXT NOT NULL (raw json)
  UNIQUE(kind, ext_id)

Kinds used:
  network-host, network-link, network-segment (or vrf/vlan), network-bgp-session, network-ospf-area

This is phase-1 minimal ingest; no diff calc, no deletion of stale rows.
"""
from __future__ import annotations
import argparse, json, os, sqlite3, sys, hashlib
from datetime import datetime, timezone

JST = timezone.utc  # store in UTC (display conversion elsewhere)

KIND_MAP = {
    'host': 'network-host',
    'link': 'network-link',
    'network': 'network-segment',  # generic (may refine by kind field later)
    'bgp': 'network-bgp-session',
    'ospf': 'network-ospf-area',
}

CREATE_OBJECTS_SQL = """
CREATE TABLE IF NOT EXISTS objects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  kind TEXT NOT NULL,
  ext_id TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  payload TEXT NOT NULL,
  UNIQUE(kind, ext_id)
)"""

UPSERT_SQL = """
INSERT INTO objects(kind, ext_id, updated_at, payload) VALUES(?,?,?,?)
ON CONFLICT(kind, ext_id) DO UPDATE SET updated_at=excluded.updated_at, payload=excluded.payload
"""

def open_db(path: str) -> sqlite3.Connection:
    cx = sqlite3.connect(path)
    return cx


def ensure_schema(cx: sqlite3.Connection):
    cx.execute(CREATE_OBJECTS_SQL)
    cx.commit()


def iso_now() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()


def upsert(cx: sqlite3.Connection, kind: str, ext_id: str, obj: dict):
    cx.execute(UPSERT_SQL, (kind, ext_id, iso_now(), json.dumps(obj, ensure_ascii=False, separators=(',',':'))))


def derive_host_ext_id(h: dict) -> str:
    return h.get('id') or h.get('hostname') or hashlib.sha1(json.dumps(h,sort_keys=True).encode()).hexdigest()[:10]


def derive_link_ext_id(l: dict) -> str:
    return l.get('id') or hashlib.sha1(json.dumps(l,sort_keys=True).encode()).hexdigest()[:12]


def derive_network_ext_id(n: dict) -> str:
    return n.get('id') or f"{n.get('kind','segment')}:{hashlib.sha1(json.dumps(n,sort_keys=True).encode()).hexdigest()[:10]}"


def derive_bgp_ext_id(b: dict) -> str:
    return b.get('id') or f"{b.get('local_asn')}:{b.get('peer_asn')}:{b.get('peer_ip')}"


def derive_ospf_ext_id(o: dict) -> str:
    return o.get('id') or f"area:{o.get('area_id')}"


def ingest(artifact: dict, cx: sqlite3.Connection) -> dict:
    counts = {k:0 for k in ['host','link','network','bgp','ospf']}

    for h in artifact.get('hosts', []) or []:
        ext_id = derive_host_ext_id(h)
        upsert(cx, KIND_MAP['host'], ext_id, h)
        counts['host'] += 1

    for l in artifact.get('links', []) or []:
        ext_id = derive_link_ext_id(l)
        upsert(cx, KIND_MAP['link'], ext_id, l)
        counts['link'] += 1

    for n in artifact.get('networks', []) or []:
        ext_id = derive_network_ext_id(n)
        upsert(cx, KIND_MAP['network'], ext_id, n)
        counts['network'] += 1

    routing = artifact.get('routing') or {}
    for b in routing.get('bgp', []) or []:
        ext_id = derive_bgp_ext_id(b)
        upsert(cx, KIND_MAP['bgp'], ext_id, b)
        counts['bgp'] += 1
    for o in routing.get('ospf', []) or []:
        ext_id = derive_ospf_ext_id(o)
        upsert(cx, KIND_MAP['ospf'], ext_id, o)
        counts['ospf'] += 1

    cx.commit()
    return counts


def main():
    ap = argparse.ArgumentParser(description='CMDB network overview ingest')
    ap.add_argument('--db', required=True, help='Path to SQLite DB (rag.db)')
    ap.add_argument('--file', required=True, help='Path to normalized network_overview.json')
    ap.add_argument('--dry-run', action='store_true', help='Parse but do not write DB')
    args = ap.parse_args()

    if not os.path.exists(args.file):
        print(json.dumps({'ok': False, 'error': f'artifact not found: {args.file}'}))
        return 2
    with open(args.file, encoding='utf-8') as f:
        try:
            artifact = json.load(f)
        except Exception as e:
            print(json.dumps({'ok': False, 'error': f'json parse error: {e}'}))
            return 3

    cx = open_db(args.db)
    ensure_schema(cx)

    if args.dry_run:
        counts = ingest(artifact, sqlite3.connect(':memory:'))
        print(json.dumps({'ok': True, 'dry_run': True, 'counts': counts}))
        return 0

    counts = ingest(artifact, cx)
    print(json.dumps({'ok': True, 'counts': counts}))
    return 0

if __name__ == '__main__':
    sys.exit(main())

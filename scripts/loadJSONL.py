#!/usr/bin/env python3
# scripts/loadJSONL.py
# Load JSONL into SQLite (docs + docs_fts) and expose legacy-compatible views.

import sys, os, json, argparse, sqlite3
from typing import Any, Dict

def _get_db_path(db_path):
    return db_path or os.getenv("CMDB_DB_PATH", "rag.db")

# ---------------------- helpers ----------------------

def _coalesce(d: Dict[str, Any], *keys):
    for k in keys:
        if isinstance(d, dict) and (k in d) and d[k] not in (None, ""):
            return d[k]
    return None

TYPE_ALIASES = {
    # IETF-style → canonical
    "termination-point": "tp",
    "ietf-network-topology:termination-point": "tp",
    "ietf-network-topology:link": "link",
    "ietf-network-topology:node": "node",
    "ietf-network:node": "node",
    "ietf-network:network": "network",
    # pass-through canonical
    "node": "node",
    "tp": "tp",
    "link": "link",
    "network": "network",
    # status/operational kinds (accepted as metadata)
    "frr_status": "frr_status",
}

def canonical_type(t: Any) -> Any:
    if t is None:
        return None
    ts = str(t)
    return TYPE_ALIASES.get(ts, ts)

# ---------------------- schema ----------------------

def ensure_schema(conn: sqlite3.Connection):
    DDL = (
        """
        PRAGMA journal_mode = WAL;
        CREATE TABLE IF NOT EXISTS docs (
            rowid INTEGER PRIMARY KEY,
            type TEXT,
            node_id TEXT,
            tp_id TEXT,
            link_id TEXT,
            json TEXT NOT NULL,
            text TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
            type, node_id, tp_id, link_id, text
        );
        """
    )
    conn.executescript(DDL)


def ensure_compat_views(conn: sqlite3.Connection):
    """Create legacy-compatible views so cmdb-mcp queries keep working.
    - objects(kind, id, data): data.interfaces is an array of TP summaries per node
    """
    # Best-effort cleanup to avoid view/table name conflicts
    try:
        conn.execute("DROP TABLE IF EXISTS objects")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("DROP VIEW IF EXISTS objects")
    except sqlite3.OperationalError:
        pass

    # 1) Clean up any pre-existing view quietly
    try:
        conn.execute("DROP VIEW IF EXISTS objects")
    except sqlite3.OperationalError:
        pass

    # 2) If a TABLE named objects exists, prefer renaming it (preserve legacy data)
    row = conn.execute("SELECT type FROM sqlite_master WHERE name='objects'").fetchone()
    if row and row[0] == 'table':
        try:
            conn.execute("ALTER TABLE objects RENAME TO objects_legacy")
        except sqlite3.OperationalError:
            conn.execute("DROP TABLE objects")

    # 3) In rare case objects_legacy is a VIEW, drop it (we only keep table backups)
    try:
        t = conn.execute("SELECT type FROM sqlite_master WHERE name='objects_legacy'").fetchone()
        if t and t[0] == 'view':
            conn.execute("DROP VIEW objects_legacy")
    except sqlite3.OperationalError:
        pass

    # 4) Create the compatibility VIEW
    conn.executescript(
        """
        CREATE VIEW objects AS
        WITH tp AS (
            SELECT
                node_id,
                json_object(
                    'tp_id', tp_id,
                    'ipv4', json_extract(json,'$.ipv4'),
                    'ipv6', json_extract(json,'$.ipv6'),
                    'mac',  json_extract(json,'$.mac')
                ) AS tp_json
            FROM docs
            WHERE type='tp'
        ),
        ifs AS (
            SELECT node_id, json_group_array(tp_json) AS ifs_json
            FROM tp
            GROUP BY node_id
        ),
        nodes AS (
            SELECT DISTINCT node_id FROM docs WHERE type='node'
        )
        SELECT
            'node' AS kind,
            n.node_id AS id,
            json_object('interfaces', COALESCE(i.ifs_json, json('[]'))) AS data
        FROM nodes n
        LEFT JOIN ifs i USING (node_id);
        """
    )


def reset_db(conn: sqlite3.Connection):
    # Drop legacy/object artifacts first using guarded statements in a safe order
    try:
        conn.execute("DROP TABLE IF EXISTS objects")  # drop table first if it exists
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("DROP VIEW IF EXISTS objects")   # then drop view if it exists
    except sqlite3.OperationalError:
        pass
    # Drop our own tables
    try:
        conn.execute("DROP TABLE IF EXISTS docs")
    except sqlite3.OperationalError:
        pass
    try:
        conn.execute("DROP TABLE IF EXISTS docs_fts")
    except sqlite3.OperationalError:
        pass
    ensure_schema(conn)
    ensure_compat_views(conn)

# ---------------------- validation ----------------------

def validate_record(obj: Dict[str, Any]) -> None:
    t = canonical_type(obj.get("type"))
    if t == "node":
        nid = _coalesce(obj, "node_id", "node-id")
        if not nid:
            raise ValueError("node: node_id (or node-id) required")
    elif t == "tp":
        nid = _coalesce(obj, "node_id", "node-id")
        tpid = _coalesce(obj, "tp_id", "tp-id")
        if not (nid and tpid):
            raise ValueError("tp: node_id(node-id) and tp_id(tp-id) required")
    elif t == "link":
        link_id = _coalesce(obj, "link_id", "link-id")
        src_node = _coalesce(obj, "a_node", "source-node")
        src_tp   = _coalesce(obj, "a_tp", "source-tp")
        dst_node = _coalesce(obj, "b_node", "dest-node")
        dst_tp   = _coalesce(obj, "b_tp", "dest-tp")
        if not (link_id or (src_node and src_tp and dst_node and dst_tp)):
            raise ValueError("link: link_id(link-id) or full source/dest required")
    else:
        # Accept other record types as metadata
        return

# ---------------------- loading ----------------------

def load_jsonl(conn: sqlite3.Connection, path: str):
    with open(path, "r", encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            json_obj = obj.get("json") or obj

            # normalize type (outer first, fallback to inner)
            outer_type = canonical_type(obj.get("type") or (json_obj.get("type") if isinstance(json_obj, dict) else None))
            obj["type"] = outer_type
            if isinstance(json_obj, dict) and json_obj.get("type") in (None, ""):
                json_obj["type"] = outer_type

            # merged view for validation
            merged: Dict[str, Any] = {}
            if isinstance(json_obj, dict):
                merged.update(json_obj)
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k not in merged or merged[k] in (None, ""):
                        merged[k] = v

            if os.getenv('LOADJSONL_SKIP_VALIDATE') != '1':
                try:
                    validate_record(merged)
                except Exception:
                    print("[loadJSONL][DEBUG] validation failed", file=sys.stderr)
                    print(f"  outer_type={outer_type}", file=sys.stderr)
                    print(f"  merged_type={canonical_type(merged.get('type'))}", file=sys.stderr)
                    print(f"  keys(merged)={sorted(list(merged.keys()))}", file=sys.stderr)
                    from pprint import pformat
                    preview = pformat({k: merged.get(k) for k in ('type','node_id','node-id','tp_id','tp-id','link_id','link-id','source-node','source-tp','dest-node','dest-tp')})
                    print(f"  preview={preview}", file=sys.stderr)
                    raise

            rec = {
                "type": canonical_type(obj.get("type")),
                "node_id": _coalesce(obj, "node_id", "node-id") or _coalesce(json_obj, "node_id", "node-id"),
                "tp_id": _coalesce(obj, "tp_id", "tp-id") or _coalesce(json_obj, "tp_id", "tp-id"),
                "link_id": _coalesce(obj, "link_id", "link-id") or _coalesce(json_obj, "link_id", "link-id"),
                "json": json.dumps(obj.get("json") or obj, ensure_ascii=False),
                "text": obj.get("text"),
            }

            conn.execute(
                "INSERT INTO docs(type,node_id,tp_id,link_id,json,text) VALUES (?,?,?,?,?,?)",
                (rec["type"], rec["node_id"], rec["tp_id"], rec["link_id"], rec["json"], rec["text"]),
            )
            conn.execute(
                "INSERT INTO docs_fts(type,node_id,tp_id,link_id,text) VALUES (?,?,?,?,?)",
                (
                    rec["type"],
                    rec["node_id"],
                    rec["tp_id"],
                    rec["link_id"],
                    rec["text"] or ""
                ),
            )
    conn.commit()

# ---------------------- main ----------------------

def main():
    print(f"[loadJSONL] running: {__file__} | sqlite3 {sqlite3.sqlite_version}")
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.getenv("CMDB_DB_PATH", "rag.db"))
    ap.add_argument("--jsonl", default=os.getenv("CMDB_JSONL"))
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    # DBパスは引数→環境変数→デフォルトの順で決定
    db_path = _get_db_path(args.db)
    jsonl_path = args.jsonl
    if not jsonl_path:
        print("[loadJSONL] ERROR: --jsonl or CMDB_JSONL must be provided", file=sys.stderr)
        sys.exit(2)
    print(f"[loadJSONL] DB={db_path} | JSONL={jsonl_path} | reset={args.reset}")

    conn = sqlite3.connect(db_path)
    try:
        if args.reset:
            reset_db(conn)
        else:
            ensure_schema(conn)
            ensure_compat_views(conn)
        load_jsonl(conn, jsonl_path)
    finally:
        conn.close()
    print(f"[loadJSONL] loaded {jsonl_path} -> {db_path}")

if __name__ == "__main__":
    main()

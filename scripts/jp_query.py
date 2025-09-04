#!/usr/bin/env python3
"""
Japanese NL → FTS5 query runner for this repo.

- Parses a Japanese prompt and derives:
  * MATCH query terms for SQLite FTS5
  * Optional equality filters for columns: {type, network_id, node_id, tp_id, link_id}
- Runs the search against `docs` (FTS5) in rag.db and prints JSON with hits and a context string.

Usage examples (repo root):
  python3 scripts/jp_query.py --db rag.db --q "L3SW1:ae1 の状態は？"
  python3 scripts/jp_query.py --db rag.db --q "L3SW1 の MTU 1500 を探して" --k 5
  python3 scripts/jp_query.py --db rag.db --q "リンクの遅延 2ms 以上"

Note:
  - This is heuristic and offline (no OpenAI). It favors ASCII-ish tokens used in the DB
    like mtu/duplex/up/down, L3SW1:ae1, delay-ms, bandwidth, speed-bps, etc.
  - For precise answering, pair with scripts/rag_qa.py once retrieval looks good.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
from typing import Dict, List, Tuple

# Columns allowed for equality filters
COLS = {"type", "network_id", "node_id", "tp_id", "link_id"}


# ----------------- Japanese → intent heuristics -----------------
TYPE_SYNONYMS = {
    "node": {"node", "ノード"},
    "tp": {"tp", "ポート", "インターフェース", "インタフェース", "if", "IF"},
    "link": {"link", "リンク"},
    "route": {"route", "routes", "ルート", "経路"},
}

FIELD_SYNONYMS = {
    # Japanese keyword to canonical token used in docs.text/json
    "mtu": {"mtu", "エムティーユー"},
    "duplex": {"duplex", "デュプレックス", "フル", "ハーフ"},
    "admin-status": {"admin", "管理", "管理状態"},
    "oper-status": {"oper", "運用", "運用状態", "状態"},
    "delay-ms": {"遅延", "delay", "レイテンシ"},
    "bandwidth": {"帯域", "band幅", "bandwidth"},
    "speed-bps": {"速度", "スピード", "bps", "speed"},
    "up": {"up", "有効", "リンクアップ", "稼働"},
    "down": {"down", "無効", "ダウン", "障害", "断"},
    "prefix": {"prefix", "プレフィックス", "経路", "ルート"},
    "next-hop": {"next-hop", "ネクストホップ", "次ホップ", "次のホップ"},
}

# ----------------- Count intent detection -----------------
COUNT_TRIGGERS = {"いくつ", "何台", "台数", "何個", "本数", "数"}
SUBJECT_NODES = {"デバイス", "ノード", "device", "devices", "node", "nodes"}
SUBJECT_IFS = {"インターフェース", "インタフェース", "ポート", "IF", "if", "interfaces", "interface", "ports", "port"}
SUBJECT_ROUTES = {"ルート", "経路", "route", "routes"}
LIST_TRIGGERS = {"一覧", "リスト", "全部", "すべて", "全て", "list"}
SUMMARY_TRIGGERS = {"どんなネットワーク", "ネットワーク概要", "このネットワーク", "ネットワークって"}
ADDR_TRIGGERS = {"アドレス", "IPアドレス", "IP", "ip address"}
ROUTING_TRIGGERS = {"ルーティング", "routing"}
VLAN_TRIGGERS = {"VLAN", "vlan", "SVI", "svi"}


def _has_any(prompt: str, words: set[str]) -> bool:
    p = prompt
    for w in words:
        if w in p:
            return True
    return False


def _extract_node_token(prompt: str) -> Tuple[str | None, str | None]:
    """Return (node_id_exact, node_prefix) if detectable.
    - If token like L3SW1 exists → exact
    - Else token like L3SW or L2SW (letters+digits optional) without digit tail → prefix
    """
    # Exact like L3SW1 (token ending in a digit)
    m = re.search(r"\b([A-Za-z][A-Za-z0-9_.\-]*\d)\b", prompt)
    if m:
        return m.group(1), None
    # Class-like prefix such as L3SW or L2SW (not followed by a digit)
    m = re.search(r"(L[23]SW)(?!\d)", prompt, re.IGNORECASE)
    if m:
        return None, m.group(1)
    return None, None


def detect_count_intent(prompt: str) -> Dict[str, str] | None:
    """
    Detect count intents like:
      - ネットワークデバイスがいくつ / ノードが何台 → count nodes
      - L3SW がいくつ → count nodes with node_id LIKE 'L3SW%'
      - L3SW1 にインターフェースはいくつ → count tp for node_id='L3SW1'
      - L3SW にインターフェースはいくつ → count tp for node_id LIKE 'L3SW%'
    Returns dict with keys:
      {action: 'count_nodes'|'count_tps', node_id?, node_prefix?}
    """
    p = prompt
    if not _has_any(p, COUNT_TRIGGERS):
        return None

    want_nodes = _has_any(p, SUBJECT_NODES)
    want_ifs = _has_any(p, SUBJECT_IFS)
    want_routes = _has_any(p, SUBJECT_ROUTES)
    node_id, node_prefix = extract_ids(prompt).get("node_id"), None
    if not node_id:
        exact, prefix = _extract_node_token(prompt)
        node_id = exact
        node_prefix = prefix

    if want_nodes and not (want_ifs or want_routes):
        return {"action": "count_nodes", **({"node_id": node_id} if node_id else {}), **({"node_prefix": node_prefix} if node_prefix else {})}
    if want_ifs:
        return {"action": "count_tps", **({"node_id": node_id} if node_id else {}), **({"node_prefix": node_prefix} if node_prefix else {})}
    if want_routes:
        return {"action": "count_routes", **({"node_id": node_id} if node_id else {}), **({"node_prefix": node_prefix} if node_prefix else {})}
    # If subject unspecified but triggers present, default to nodes
    return {"action": "count_nodes", **({"node_id": node_id} if node_id else {}), **({"node_prefix": node_prefix} if node_prefix else {})}


def detect_list_intent(prompt: str) -> Dict[str, str] | None:
    """
    Detect list intents like:
      - デバイスの一覧 / ノードの一覧 → list nodes
      - L3SW の一覧 / L2SW の一覧 → list nodes with prefix
      - (ノード)のインターフェース一覧 / L3SW1 のインターフェース一覧 → list tps filtered by node
      - インターフェースの一覧 → list all tps
    Returns:
      {action: 'list_nodes'|'list_tps', node_id?, node_prefix?}
    """
    p = prompt
    if not _has_any(p, LIST_TRIGGERS):
        return None
    want_nodes = _has_any(p, SUBJECT_NODES)
    want_ifs = _has_any(p, SUBJECT_IFS)
    want_routes = _has_any(p, SUBJECT_ROUTES)
    ids = extract_ids(prompt)
    node_id = ids.get("node_id")
    exact, prefix = _extract_node_token(prompt)
    node_id = node_id or exact
    node_prefix = prefix
    if want_ifs:
        return {"action": "list_tps", **({"node_id": node_id} if node_id else {}), **({"node_prefix": node_prefix} if node_prefix else {})}
    if want_routes:
        return {"action": "list_routes", **({"node_id": node_id} if node_id else {}), **({"node_prefix": node_prefix} if node_prefix else {})}
    # default to nodes
    return {"action": "list_nodes", **({"node_prefix": node_prefix} if node_prefix else {})}


# ----------------- Count SQL helpers -----------------
def count_nodes(db_path: str, node_id: str | None = None, node_prefix: str | None = None) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if node_id:
        n = cur.execute("SELECT COUNT(*) FROM docs WHERE type='node' AND node_id=?", (node_id,)).fetchone()[0]
    elif node_prefix:
        like = f"{node_prefix}%"
        n = cur.execute("SELECT COUNT(DISTINCT node_id) FROM docs WHERE type='node' AND node_id LIKE ?", (like,)).fetchone()[0]
    else:
        n = cur.execute("SELECT COUNT(DISTINCT node_id) FROM docs WHERE type='node'", ()).fetchone()[0]
    conn.close()
    return int(n)


def count_tps(db_path: str, node_id: str | None = None, node_prefix: str | None = None) -> Tuple[int, List[Tuple[str, int]]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if node_id:
        total = cur.execute("SELECT COUNT(*) FROM docs WHERE type='tp' AND node_id=?", (node_id,)).fetchone()[0]
        by_node = [(node_id, int(total))]
    elif node_prefix:
        like = f"{node_prefix}%"
        rows = cur.execute("SELECT node_id, COUNT(*) FROM docs WHERE type='tp' AND node_id LIKE ? GROUP BY node_id", (like,)).fetchall()
        by_node = [(r[0], int(r[1])) for r in rows]
        total = sum(c for _, c in by_node)
    else:
        total = cur.execute("SELECT COUNT(*) FROM docs WHERE type='tp'", ()).fetchone()[0]
        rows = cur.execute("SELECT node_id, COUNT(*) FROM docs WHERE type='tp' GROUP BY node_id", ()).fetchall()
        by_node = [(r[0], int(r[1])) for r in rows]
    conn.close()
    return int(total), by_node


def count_routes(db_path: str, node_id: str | None = None, node_prefix: str | None = None) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    params = []
    where = ["type='route'"]
    if node_id:
        where.append("node_id = ?"); params.append(node_id)
    elif node_prefix:
        where.append("node_id LIKE ?"); params.append(f"{node_prefix}%")
    sql = f"SELECT COUNT(*) FROM docs WHERE {' AND '.join(where)}"
    n = cur.execute(sql, params).fetchone()[0]
    conn.close()
    return int(n)


def count_links(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    n = cur.execute("SELECT COUNT(*) FROM docs WHERE type='link'").fetchone()[0]
    conn.close()
    return int(n)


def detect_summary_intent(prompt: str) -> bool:
    p = prompt
    for w in SUMMARY_TRIGGERS:
        if w in p:
            return True
    return False


def list_nodes(db_path: str, node_prefix: str | None = None, limit: int | None = None) -> List[str]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if node_prefix:
        like = f"{node_prefix}%"
        sql = "SELECT DISTINCT node_id FROM docs WHERE type='node' AND node_id LIKE ? ORDER BY node_id"
        rows = cur.execute(sql, (like,)).fetchall()
    else:
        sql = "SELECT DISTINCT node_id FROM docs WHERE type='node' ORDER BY node_id"
        rows = cur.execute(sql).fetchall()
    conn.close()
    out = [r[0] for r in rows]
    if limit is not None:
        out = out[: int(limit)]
    return out


def list_tps(db_path: str, node_id: str | None = None, node_prefix: str | None = None, limit: int | None = None) -> List[Tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    params = []
    where = ["type='tp'"]
    if node_id:
        where.append("node_id = ?"); params.append(node_id)
    elif node_prefix:
        where.append("node_id LIKE ?"); params.append(f"{node_prefix}%")
    sql = f"SELECT node_id, tp_id FROM docs WHERE {' AND '.join(where)} ORDER BY node_id, tp_id"
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    out = [(r[0], r[1]) for r in rows]
    if limit is not None:
        out = out[: int(limit)]
    return out


def list_addresses(db_path: str, node_id: str | None = None, node_prefix: str | None = None) -> List[Tuple[str, str, str | None, int | None]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    where = ["type='tp'",
             "json_extract(json,'$.tp.""ietf-l3-unicast-topology:l3-termination-point-attributes"".""ip-address""') IS NOT NULL"]
    params: List[object] = []
    if node_id:
        where.append("node_id = ?"); params.append(node_id)
    elif node_prefix:
        where.append("node_id LIKE ?"); params.append(f"{node_prefix}%")
    sql = f"""
        SELECT node_id,
               tp_id,
               json_extract(json,'$.tp."ietf-l3-unicast-topology:l3-termination-point-attributes"."ip-address"') AS ip,
               json_extract(json,'$.tp."ietf-l3-unicast-topology:l3-termination-point-attributes"."prefix-length"') AS plen
        FROM docs
        WHERE {' AND '.join(where)}
        ORDER BY node_id, tp_id
    """
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return [(r[0], r[1], r[2], int(r[3]) if r[3] is not None else None) for r in rows]


def list_svis(db_path: str, node_id: str | None = None, node_prefix: str | None = None) -> List[Tuple[str, str, str | None, int | None]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    where = ["type='tp'", "tp_id LIKE 'vlan%'"]
    params: List[object] = []
    if node_id:
        where.append("node_id = ?"); params.append(node_id)
    elif node_prefix:
        where.append("node_id LIKE ?"); params.append(f"{node_prefix}%")
    sql = f"""
        SELECT node_id,
               tp_id,
               json_extract(json,'$.tp."ietf-l3-unicast-topology:l3-termination-point-attributes"."ip-address"') AS ip,
               json_extract(json,'$.tp."ietf-l3-unicast-topology:l3-termination-point-attributes"."prefix-length"') AS plen
        FROM docs
        WHERE {' AND '.join(where)}
        ORDER BY node_id, tp_id
    """
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    return [(r[0], r[1], r[2], int(r[3]) if r[3] is not None else None) for r in rows]


def list_vlan_tps(db_path: str, vlan_id: int) -> List[Tuple[str, str]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    sql = (
        "SELECT node_id, tp_id FROM docs "
        "WHERE type='tp' AND json_extract(json,'$.tp.""ietf-l2-topology:l2-termination-point-attributes"".""vlan-id""') = ? "
        "ORDER BY node_id, tp_id"
    )
    rows = cur.execute(sql, (int(vlan_id),)).fetchall()
    conn.close()
    return [(r[0], r[1]) for r in rows]


def detect_address_intent(prompt: str) -> Dict[str, str] | None:
    if not _has_any(prompt, ADDR_TRIGGERS):
        return None
    ids = extract_ids(prompt)
    exact, prefix = _extract_node_token(prompt)
    node_id = ids.get("node_id") or exact
    out: Dict[str, str] = {"action": "list_addresses"}
    if node_id:
        out["node_id"] = node_id
    elif prefix:
        out["node_prefix"] = prefix
    return out


def detect_routing_overview_intent(prompt: str) -> Dict[str, str] | None:
    if not _has_any(prompt, ROUTING_TRIGGERS):
        return None
    ids = extract_ids(prompt)
    exact, prefix = _extract_node_token(prompt)
    node_id = ids.get("node_id") or exact
    out: Dict[str, str] = {"action": "list_routes"}
    if node_id:
        out["node_id"] = node_id
    elif prefix:
        out["node_prefix"] = prefix
    return out


def detect_vlan_intent(prompt: str) -> Dict[str, object] | None:
    if not _has_any(prompt, VLAN_TRIGGERS):
        return None
    m = re.search(r"(?i)vlan\s*(\d+)", prompt)
    vlan = int(m.group(1)) if m else None
    ids = extract_ids(prompt)
    exact, prefix = _extract_node_token(prompt)
    node_id = ids.get("node_id") or exact
    if vlan is not None:
        return {"action": "list_vlan_tps", "vlan": vlan}
    out: Dict[str, object] = {"action": "list_svis"}
    if node_id:
        out["node_id"] = node_id
    elif prefix:
        out["node_prefix"] = prefix
    return out


def list_routes(db_path: str, node_id: str | None = None, node_prefix: str | None = None, limit: int | None = None) -> List[Tuple[str, str, str, str, str]]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    params = []
    where = ["type='route'"]
    if node_id:
        where.append("node_id = ?"); params.append(node_id)
    elif node_prefix:
        where.append("node_id LIKE ?"); params.append(f"{node_prefix}%")
    sql = f"SELECT node_id, COALESCE(json_extract(json,'$.vrf'),'default'), json_extract(json,'$.prefix'), json_extract(json,'$.next_hop'), COALESCE(json_extract(json,'$.protocol'),'') FROM docs WHERE {' AND '.join(where)} ORDER BY node_id, json_extract(json,'$.vrf'), json_extract(json,'$.prefix')"
    rows = cur.execute(sql, params).fetchall()
    conn.close()
    out = [(r[0], r[1], r[2], r[3], r[4]) for r in rows]
    if limit is not None:
        out = out[: int(limit)]
    return out


def resolve_tp_by_ip(db_path: str, ip: str) -> Tuple[str, str] | None:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    row = cur.execute(
        """
        SELECT node_id, tp_id
        FROM docs
        WHERE type='tp'
          AND json_extract(json,'$.tp."ietf-l3-unicast-topology:l3-termination-point-attributes"."ip-address"') = ?
        LIMIT 1
        """,
        (ip,),
    ).fetchone()
    conn.close()
    if row:
        return row[0], row[1]
    return None


def detect_type(prompt: str) -> str | None:
    p = prompt.lower()
    for t, keys in TYPE_SYNONYMS.items():
        for k in keys:
            if k.lower() in p:
                return t
    return None


def extract_ids(prompt: str) -> Dict[str, str]:
    """Extract node_id/tp_id/link_id from variants like:
    - L3SW1:ae1 → node_id=L3SW1, tp_id=ae1
    - ノード L3SW1, node L3SW1 → node_id=L3SW1
    - ポート ae1, IF ae1, tp ae1 → tp_id=ae1
    - リンク link-1 → link_id=link-1
    """
    out: Dict[str, str] = {}

    # node:tp like L3SW1:ae1
    m = re.search(r"([A-Za-z0-9_.\-]+):([A-Za-z0-9_.\-]+)", prompt)
    if m:
        out["node_id"] = m.group(1)
        out["tp_id"] = m.group(2)

    # Node only
    if "node_id" not in out:
        m = re.search(r"(?:ノード|node)\s*([A-Za-z0-9_.\-]+)", prompt, re.IGNORECASE)
        if m:
            out["node_id"] = m.group(1)

    # TP only
    if "tp_id" not in out:
        m = re.search(r"(?:ポート|インターフェース|インタフェース|IF|if|tp)\s*([A-Za-z0-9_.\-]+)", prompt)
        if m:
            out["tp_id"] = m.group(1)

    # Link
    m = re.search(r"(?:リンク|link)\s*([A-Za-z0-9_.\-]+)", prompt, re.IGNORECASE)
    if m:
        out["link_id"] = m.group(1)

    return out


def build_match_terms(prompt: str, ids: Dict[str, str]) -> str:
    # Keep ascii-ish tokens for FTS; map JP words to canonical field tokens
    tokens: List[str] = []

    # Strong signal: exact node:tp string if present
    if "node_id" in ids and "tp_id" in ids:
        tokens.append(f'"{ids["node_id"]}:{ids["tp_id"]}"')

    # Collect ascii tokens in prompt (mtu, 1500, up, down, etc.)
    for t in re.findall(r"[A-Za-z0-9_:\-]+", prompt):
        # If looks like key:value and key is unknown column, quote it
        if ":" in t and t.split(":", 1)[0] not in {"type", "network_id", "node_id", "tp_id", "link_id"}:
            tokens.append(f'"{t}"')
            continue
        # If contains non-word operator-ish char like '-' (and is not a col:term), quote to avoid FTS parsing errors
        if ("-" in t) and (":" not in t):
            tokens.append(f'"{t}"')
            continue
        tokens.append(t)

    # Map JP keywords to canonical field tokens
    pl = prompt.lower()
    for canon, synonyms in FIELD_SYNONYMS.items():
        for s in synonyms:
            if s.lower() in pl:
                # Quote canon terms with '-' to avoid FTS treating '-' as operator
                if "-" in canon:
                    tokens.append(f'"{canon}"')
                else:
                    tokens.append(canon)
                break

    # Fallbacks
    if not tokens:
        for k in ["node_id", "tp_id", "link_id"]:
            if k in ids:
                tokens.append(ids[k])
    if not tokens:
        tokens = ["node", "tp", "link"]

    # Deduplicate but keep order
    tokens = list(dict.fromkeys(tokens))
    return " OR ".join(tokens)


# ----------------- DB query -----------------
def build_where(filters: Dict[str, str], alias: str = "d") -> Tuple[str, Dict[str, str]]:
    if not filters:
        return "", {}
    clauses: List[str] = []
    params: Dict[str, str] = {}
    for k, v in filters.items():
        if k in COLS and v:
            clauses.append(f"{alias}.{k} = :{k}")
            params[k] = v
    return (" AND ".join(clauses), params)


def retrieve(db_path: str, match_q: str, filters: Dict[str, str], k: int = 5) -> List[Dict]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    where_sql, where_params = build_where(filters, alias="d")
    sql = (
        "WITH match_rows AS ("
        "  SELECT rowid FROM docs WHERE docs MATCH :q"
        ") "
        "SELECT d.rowid, d.type, d.network_id, d.node_id, d.tp_id, d.link_id, d.text, d.json, bm25(docs) AS score "
        "FROM docs AS d JOIN match_rows m ON m.rowid = d.rowid "
    )
    params: Dict[str, object] = {"q": match_q, "k": int(k)}
    if where_sql:
        sql += "WHERE " + where_sql + " "
        params.update(where_params)
    sql += "ORDER BY score ASC LIMIT :k"

    rows = cur.execute(sql, params).fetchall()
    conn.close()

    hits: List[Dict] = []
    for row in rows:
        obj = json.loads(row["json"])
        hits.append({
            "rowid": row["rowid"],
            "score": float(row["score"]) if row["score"] is not None else None,
            "type": row["type"],
            "network-id": row["network_id"],
            "node-id": row["node_id"],
            "tp-id": row["tp_id"],
            "link-id": row["link_id"],
            "object": obj,
        })
    return hits


def make_context(hits: List[Dict]) -> str:
    lines: List[str] = []
    for i, h in enumerate(hits, 1):
        obj = h["object"]
        label = f"[{i}] {h['type']}"
        if h.get("node-id"):
            label += f" node={h['node-id']}"
        if h.get("tp-id"):
            label += f" tp={h['tp-id']}"
        if h.get("link-id"):
            label += f" link={h['link-id']}"
        lines.append(label)
        if obj.get("text"):
            lines.append(f"text: {obj['text']}")
        lines.append("json: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        lines.append("")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rag.db")
    ap.add_argument("--q", required=True, help="Japanese natural language prompt")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    intent_type = detect_type(args.q)
    ids = extract_ids(args.q)

    filters: Dict[str, str] = {}
    if intent_type:
        filters["type"] = intent_type
    for k in ("node_id", "tp_id", "link_id"):
        if k in ids:
            filters[k] = ids[k]

    match_q = build_match_terms(args.q, ids)

    if args.debug:
        print("---- DEBUG ----")
        print("type:", intent_type)
        print("ids:", ids)
        print("filters:", filters)
        print("match_q:", match_q)

    hits = retrieve(args.db, match_q, filters, k=args.k)
    context = make_context(hits)
    print(json.dumps({"hits": hits, "context": context}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

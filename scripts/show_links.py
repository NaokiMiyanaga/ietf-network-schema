#!/usr/bin/env python3
"""
Show interface-to-interface connections from SQLite (rag.db).

Extracts links from docs (type='link') and prints:
  <src-node>:<src-tp> -> <dst-node>:<dst-tp>  (link-id, oper, bw, delay)

Usage:
  python3 scripts/show_links.py --db rag.db                     # list all
  python3 scripts/show_links.py --db rag.db --node L3SW1        # links involving node
  python3 scripts/show_links.py --db rag.db --tp L3SW1:ae1      # links involving specific interface
  python3 scripts/show_links.py --db rag.db --format json       # JSON output
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import os
from typing import Dict, List, Optional, Tuple


def _get_db_path(db_path):
    return db_path or os.getenv("CMDB_DB_PATH", "rag.db")


def _row_to_edge(obj: Dict) -> Dict:
    link = obj.get("link") or {}
    src = (link.get("ietf-network-topology:source") or {})
    dst = (link.get("ietf-network-topology:destination") or {})
    op = (obj.get("operational") or {}).get("link-state") or (link.get("operational:link-state") or {})
    l2 = (link.get("ietf-l2-topology:l2-link-attributes") or {})
    return {
        "link_id": obj.get("link-id") or obj.get("link_id") or link.get("link-id"),
        "src_node": src.get("source-node"),
        "src_tp": src.get("source-tp"),
        "dst_node": dst.get("dest-node"),
        "dst_tp": dst.get("dest-tp"),
        "oper_status": op.get("oper-status"),
        "bandwidth": op.get("bandwidth"),
        "delay_ms": op.get("delay-ms"),
        # Prefer explicit L2 link attribute if present
        "vlan_id": l2.get("vlan-id"),
        # Enriched later: src/dst VLANs resolved via TP docs (if available)
        "src_vlan": None,
        "dst_vlan": None,
    }


def _get_tp_vlan(cur: sqlite3.Cursor, node_id: str, tp_id: str) -> Optional[int]:
    row = cur.execute(
        "SELECT json FROM docs WHERE type='tp' AND node_id=? AND tp_id=? LIMIT 1",
        (node_id, tp_id),
    ).fetchone()
    if not row:
        return None
    try:
        obj = json.loads(row[0])
    except Exception:
        return None
    tp = (obj.get("tp") or {})
    l2tp = tp.get("ietf-l2-topology:l2-termination-point-attributes") or {}
    vid = l2tp.get("vlan-id")
    try:
        return int(vid) if vid is not None else None
    except Exception:
        return None


def _fallback_vlan_from_link_id(link_id: Optional[str]) -> Optional[int]:
    if not link_id:
        return None
    m = __import__("re").search(r"(?:^|[^0-9])vlan(\d+)$", str(link_id))
    if m:
        try:
            return int(m.group(1))
        except Exception:
            return None
    return None


def load_edges(db_path: str) -> list:
    db_path = _get_db_path(db_path)
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT json FROM docs WHERE type='link'").fetchall()
    edges: List[Dict] = []
    for (js,) in rows:
        try:
            obj = json.loads(js)
        except Exception:
            continue
        edge = _row_to_edge(obj)
        if not (edge.get("src_node") and edge.get("dst_node")):
            continue
        # Enrich VLANs from TP docs when possible
        sn, st = edge.get("src_node"), edge.get("src_tp")
        dn, dt = edge.get("dst_node"), edge.get("dst_tp")
        if sn and st:
            edge["src_vlan"] = _get_tp_vlan(cur, sn, st)
        if dn and dt:
            edge["dst_vlan"] = _get_tp_vlan(cur, dn, dt)
        # If no link-level vlan, infer from src/dst if equal; else fallback to link-id suffix
        if edge.get("vlan_id") is None:
            if edge.get("src_vlan") is not None and edge.get("src_vlan") == edge.get("dst_vlan"):
                edge["vlan_id"] = edge.get("src_vlan")
            else:
                edge["vlan_id"] = _fallback_vlan_from_link_id(edge.get("link_id"))
        edges.append(edge)
    conn.close()
    return edges


def load_nodes(db_path: str) -> List[str]:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    rows = cur.execute("SELECT DISTINCT node_id FROM docs WHERE type='node' ORDER BY node_id").fetchall()
    conn.close()
    return [r[0] for r in rows]


def filter_edges(edges: List[Dict], node: str | None = None, tp: str | None = None) -> List[Dict]:
    if not node and not tp:
        return edges
    out: List[Dict] = []
    node_q = None
    tp_node = tp_tp = None
    if node:
        node_q = node
    if tp and ":" in tp:
        tp_node, tp_tp = tp.split(":", 1)
    for e in edges:
        keep = True
        if node_q:
            keep = e.get("src_node") == node_q or e.get("dst_node") == node_q
        if keep and tp_node and tp_tp:
            keep = ((e.get("src_node") == tp_node and e.get("src_tp") == tp_tp) or
                    (e.get("dst_node") == tp_node and e.get("dst_tp") == tp_tp))
        if keep:
            out.append(e)
    return out


def _format_edge(e: Dict) -> str:
    left = f"{e['src_node']}:{e['src_tp']}"
    right = f"{e['dst_node']}:{e['dst_tp']}"
    tail = []
    if e.get("oper_status"):
        tail.append(f"oper={e['oper_status']}")
    if e.get("bandwidth") is not None:
        tail.append(f"bw={e['bandwidth']}")
    if e.get("delay_ms") is not None:
        tail.append(f"delay-ms={e['delay_ms']}")
    # VLAN formatting: prefer uniform link vlan; otherwise show src|dst if asymmetric/unknown
    if e.get("vlan_id") is not None:
        tail.append(f"vlan={e['vlan_id']}")
    else:
        sv, dv = e.get("src_vlan"), e.get("dst_vlan")
        if sv is not None or dv is not None:
            def _fmt(x):
                return str(x) if x is not None else "?"
            tail.append(f"vlan={_fmt(sv)}|{_fmt(dv)}")
    meta = (" (" + ", ".join(tail) + ")") if tail else ""
    link_id = e.get("link_id")
    if link_id:
        meta = f" [{link_id}]" + meta
    # Use symmetric arrow for readability
    return f"{left} <-> {right}{meta}"


def print_edges(edges: List[Dict], fmt: str = "list") -> None:
    if fmt == "json":
        print(json.dumps(edges, ensure_ascii=False, indent=2))
        return
    for e in edges:
        print(_format_edge(e))


def summarize_by_node(edges: List[Dict]) -> Dict[str, List[str]]:
    """Return adjacency lists: node -> [formatted pairs involving node]."""
    adj: Dict[str, List[str]] = {}
    for e in edges:
        for node, tp in [(e.get("src_node"), e.get("src_tp")), (e.get("dst_node"), e.get("dst_tp"))]:
            if not node:
                continue
            adj.setdefault(node, [])
            adj[node].append(_format_edge(e))
    # Deduplicate lines per node while keeping order
    for k, v in adj.items():
        seen = set(); out = []
        for line in v:
            if line in seen:
                continue
            seen.add(line); out.append(line)
        adj[k] = out
    return adj


def print_adjacency(edges: List[Dict], node: str | None = None) -> None:
    adj = summarize_by_node(edges)
    if node:
        lines = adj.get(node, [])
        if not lines:
            print("(no links)"); return
        print(f"接続（{node} 関連）:")
        for line in lines:
            print("- " + line)
        return
    # All nodes present in edges
    if not adj:
        print("(no links)"); return
    for n in sorted(adj.keys()):
        print(f"{n}:")
        for line in adj[n]:
            print("  - " + line)


def print_adjacency_full(db_path: str, node: str | None = None) -> None:
    edges = load_edges(db_path)
    nodes = load_nodes(db_path)
    adj = summarize_by_node(edges)
    if node:
        if node not in nodes:
            print("(unknown node)"); return
        lines = adj.get(node, [])
        print(f"{node}:")
        if lines:
            for line in lines:
                print("  - " + line)
        else:
            print("  - (no links)")
        return
    # All nodes, including isolated ones
    for n in nodes:
        print(f"{n}:")
        lines = adj.get(n, [])
        if lines:
            for line in lines:
                print("  - " + line)
        else:
            print("  - (no links)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.getenv("CMDB_DB_PATH", "rag.db"))
    ap.add_argument("--node", help="Show links that involve this node_id")
    ap.add_argument("--tp", help="Show links that involve this interface as NODE:TP")
    ap.add_argument("--format", choices=["list", "json"], default="list")
    args = ap.parse_args()

    edges = load_edges(args.db)
    edges = filter_edges(edges, node=args.node, tp=args.tp)
    print_edges(edges, fmt=args.format)


if __name__ == "__main__":
    main()

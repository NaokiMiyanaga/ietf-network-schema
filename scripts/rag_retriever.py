#!/usr/bin/env python3
"""Minimal RAG retriever over SQLite FTS5.
Usage:
  python3 rag_retriever.py --db rag.db --q "ae1 latency" --k 5 --filters type=tp node_id=L3SW1
Output:
  JSON with 'hits' (ordered by bm25) and a 'context' string you can drop into an LLM prompt.
"""
import argparse, sqlite3, json, re
import os
from typing import List, Dict

def _get_db_path(db):
    return db or os.getenv("CMDB_DB_PATH", "rag.db")

def parse_filters(items: List[str]) -> Dict[str, str]:
    out = {}
    for it in items or []:
        if "=" in it:
            k, v = it.split("=", 1)
            out[k.strip()] = v.strip()
    return out

def build_sql(filters: Dict[str, str]) -> str:
    clauses = []
    params = []
    for k, v in filters.items():
        if k not in {"type", "network_id", "node_id", "tp_id", "link_id"}:
            continue
        clauses.append(f"{k} = ?")
        params.append(v)
    where = " AND ".join(clauses) if clauses else "1=1"
    return where, params

def query(db: str, q: str, k: int, filters: Dict[str, str]):
    db = _get_db_path(db)
    conn = sqlite3.connect(db)
    cur = conn.cursor()
    where, params = build_sql(filters)
    sql = f"""
        SELECT rowid, bm25(docs) AS score, type, network_id, node_id, tp_id, link_id, json
        FROM docs
        WHERE {where} AND docs MATCH ?
        ORDER BY score ASC
        LIMIT ?
    """
    cur.execute(sql, (*params, q, k))
    rows = cur.fetchall()
    conn.close()

    hits = []
    for row in rows:
        rowid, score, typ, net, node, tp, link, js = row
        obj = json.loads(js)
        hits.append({
            "rowid": rowid,
            "score": float(score) if score is not None else None,
            "type": typ, "network-id": net, "node-id": node, "tp-id": tp, "link-id": link,
            "object": obj
        })
    return hits

def make_context(hits: List[Dict]) -> str:
    lines = []
    for i,h in enumerate(hits, 1):
        obj = h["object"]
        # Short label
        label = f"[{i}] {obj.get('type','')}"
        if obj.get('node-id'):
            label += f" node={obj['node-id']}"
        if obj.get('tp-id'):
            label += f" tp={obj['tp-id']}"
        if obj.get('link-id'):
            label += f" link={obj['link-id']}"
        lines.append(label)
        # Prefer human text, then compact JSON
        if obj.get("text"):
            lines.append(f"text: {obj['text']}")
        lines.append("json: " + json.dumps(obj, ensure_ascii=False, separators=(',',':')))
        lines.append("")  # blank line
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.getenv("CMDB_DB_PATH", "rag.db"))
    ap.add_argument("--q", required=True, help="Query string for FTS5 MATCH")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--filters", nargs="*", default=[], help="key=value pairs, keys in {type,network_id,node_id,tp_id,link_id}")
    args = ap.parse_args()

    filters = parse_filters(args.filters)
    hits = query(args.db, args.q, args.k, filters)
    context = make_context(hits)
    print(json.dumps({"hits": hits, "context": context}, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

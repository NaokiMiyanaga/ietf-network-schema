#!/usr/bin/env python3
"""
RAG QA runner (SQLite FTS5 + optional OpenAI)

Usage (repo root):
  # Dry-run（プロンプト表示＋SQL/パラメータのデバッグ）
  python3 scripts/rag_qa.py --db rag.db --q "L3SW1:ae1 の状態は？" --filters type=tp node_id=L3SW1 --k 3 --dry-run --debug
"""
import argparse
import json
import os
import re
import sqlite3
from typing import Dict, List, Tuple, Optional

try:
    from openai import OpenAI  # optional dependency
except Exception:
    OpenAI = None  # SDK 未インストールでも動くように

# 検索やフィルタで許可する列
WHITELIST_COLS = {"type", "network_id", "node_id", "tp_id", "link_id"}
KNOWN_COLS = set(WHITELIST_COLS)

# ----------------- ユーティリティ -----------------
def parse_filters(filter_list: Optional[List[str]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not filter_list:
        return out
    for f in filter_list:
        if "=" not in f:
            continue
        k, v = f.split("=", 1)
        k = k.strip(); v = v.strip()
        if k in WHITELIST_COLS:
            out[k] = v
    return out

def build_where_qualified(filters: Dict[str, str], alias: str = "d") -> Tuple[str, Dict[str, str]]:
    if not filters:
        return "", {}
    clauses: List[str] = []
    params: Dict[str, str] = {}
    for k, v in filters.items():
        clauses.append(f"{alias}.{k} = :{k}")
        params[k] = v
    return " AND ".join(clauses), params

def preprocess_match_query(q: str) -> str:
    """
    X:Y を自動クォート。ただし X が既知の列名（type/node_id 等）の場合はそのまま。
    """
    def repl(m):
        left, right = m.group(1), m.group(2)
        if left in KNOWN_COLS:
            return f"{left}:{right}"
        return f"\"{left}:{right}\""
    return re.sub(r'(\S+):(\S+)', repl, q)

def build_match_query(q: str, filters: Dict[str, str]) -> str:
    """
    FTS5 に渡す MATCH クエリを構築。
    - q から英数と _:- を含むトークンだけを抽出し OR で接続
    - ':' を含む語は preprocess でクォート（列名:語 以外）
    - それでも空になったら、filters の値から候補（node_id/tp_id/link_id/type）を使う
    """
    q = preprocess_match_query(q)

    # 英数・記号（_: - :）のみ抽出（日本語などは除外）
    raw_tokens = re.findall(r'[A-Za-z0-9_:\-]+', q)
    tokens: List[str] = []
    for t in raw_tokens:
        # 列名:語 の場合はそのまま、それ以外で ':' を含むときはクォート
        if ':' in t and t.split(':', 1)[0] not in KNOWN_COLS:
            tokens.append(f"\"{t}\"")
        else:
            tokens.append(t)

    # 何も残らない場合はフィルタ値から作る（優先度順）
    if not tokens:
        for key in ["node_id", "tp_id", "link_id", "type", "network_id"]:
            if key in filters and filters[key]:
                tokens.append(filters[key])
        # それでも無ければ、無難な単語
        if not tokens:
            tokens = ["node", "tp", "link"]

    # 重複排除して OR 結合
    tokens = list(dict.fromkeys(tokens))
    return " OR ".join(tokens)

# ----------------- 検索（Retriever） -----------------
def retrieve(db_path: str, query_text: str, filters: Optional[Dict[str, str]] = None,
             k: int = 5, debug: bool = False) -> List[Dict]:
    """
    FTS5 (BM25) 検索：
      - MATCH は CTE に隔離
      - '=' フィルタはテーブル別名 'd.' を付けて適用
      - 名前付きパラメータで明確にバインド
      - クエリ文字列は build_match_query() で整形
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    filters = filters or {}
    where_sql, where_params = build_where_qualified(filters, alias="d")
    match_q = build_match_query(query_text, filters)

    sql = (
        "WITH match_rows AS ("
        "  SELECT rowid FROM docs WHERE docs MATCH :q"
        ") "
        "SELECT d.rowid, d.type, d.network_id, d.node_id, d.tp_id, d.link_id, d.text, d.json, "
        "       bm25(docs) AS score "
        "FROM docs AS d "
        "JOIN match_rows m ON m.rowid = d.rowid "
    )
    params: Dict[str, object] = {"q": match_q, "k": int(k)}
    if where_sql:
        sql += "WHERE " + where_sql + " "
        params.update(where_params)
    sql += "ORDER BY score ASC LIMIT :k"

    if debug:
        print("---- SQL ----"); print(sql)
        print("---- PARAMS ----"); print(params)

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

# ----------------- プロンプト生成 -----------------
def build_prompt(question: str, hits: List[Dict]) -> str:
    ctx_lines: List[str] = []
    for i, h in enumerate(hits, 1):
        obj = h["object"]
        label = f"[{i}] {h['type']}"
        if h.get("node-id"):
            label += f" node={h['node-id']}"
        if h.get("tp-id"):
            label += f" tp={h['tp-id']}"
        if h.get("link-id"):
            label += f" link={h['link-id']}"
        ctx_lines.append(label)
        if obj.get("text"):
            ctx_lines.append(f"text: {obj['text']}")
        ctx_lines.append("json: " + json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
        ctx_lines.append("")
    context = "\n".join(ctx_lines)

    prompt = f"""あなたはネットワーク運用のアシスタントです。以下の「コンテキスト」だけを根拠に、
日本語で簡潔・正確に回答してください。推測は避け、根拠となる [n] 番号も必ず併記してください。

コンテキスト:
{context}

質問: {question}
回答（根拠の [n] を明記）:
"""
    return prompt

# ----------------- LLM 呼び出し -----------------
def call_openai(prompt: str, model: str = "gpt-4o-mini") -> Optional[str]:
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key or OpenAI is None:
        return None
    client = OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "You are a helpful assistant for network operations."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    return resp.choices[0].message.content.strip()

# ----------------- CLI -----------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--q", required=True, help="ユーザー質問（MATCH 用には英数トークンへ整形されます）")
    ap.add_argument("--filters", nargs="*", help="key=value among: type,network_id,node_id,tp_id,link_id")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true", help="print SQL and params")
    args = ap.parse_args()

    filters = parse_filters(args.filters)
    hits = retrieve(args.db, args.q, filters=filters, k=args.k, debug=args.debug)

    prompt = build_prompt(args.q, hits)
    if args.dry_run or not os.getenv("OPENAI_API_KEY") or OpenAI is None:
        print("=== PROMPT (dry-run) ===")
        print(prompt)
        return

    answer = call_openai(prompt, model=args.model)
    print(answer or prompt)

if __name__ == "__main__":
    main()

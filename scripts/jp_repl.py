#!/usr/bin/env python3
"""
Japanese NL search REPL for ietf-network-schema.

- Prompts for a Japanese query repeatedly
- Converts to FTS5 MATCH + filters using jp_query heuristics
- Prints concise results (or JSON/context with flags)
- Optional QA: build prompt from hits and call OpenAI (if API key present)
- Type 'exit' or 'quit' (or ':q') to leave

Usage (repo root):
  python3 scripts/jp_repl.py --db rag.db --k 5

Options:
  --mode summary|json|context   Output format (default: summary)
  --k K                         Number of hits (default: 5)
  --debug                       Show derived filters and MATCH query
  --qa                          Generate answer via OpenAI using retrieved context
  --dry-run                     With --qa, print prompt instead of calling the API
  --model MODEL                 OpenAI model name (default: gpt-4o-mini)
"""
from __future__ import annotations

import argparse
import sys
from typing import Dict

# Import sibling module
from pathlib import Path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
import jp_query  # noqa: E402
try:
    import rag_qa  # noqa: E402
except Exception:
    rag_qa = None
try:
    import show_links  # noqa: E402
except Exception:
    show_links = None


def one_turn(db: str, question: str, k: int, mode: str, debug: bool, qa: bool, dry_run: bool, model: str) -> None:
    # 1) Count intent?
    cnt = jp_query.detect_count_intent(question)
    if cnt:
        action = cnt.get("action")
        node_id = cnt.get("node_id")
        node_prefix = cnt.get("node_prefix")
        if action == "count_nodes":
            n = jp_query.count_nodes(db, node_id=node_id, node_prefix=node_prefix)
            if node_id:
                print(f"ノード {node_id} の存在数: {n}")
            elif node_prefix:
                print(f"{node_prefix}* のノード数: {n}")
            else:
                print(f"ノード数: {n}")
            return
        if action == "count_routes":
            n = jp_query.count_routes(db, node_id=node_id, node_prefix=node_prefix)
            if node_id:
                print(f"{node_id} のルート数: {n}")
            elif node_prefix:
                print(f"{node_prefix}* のルート数: {n}")
            else:
                print(f"ルート数: {n}")
            return
        if action == "count_tps":
            total, by_node = jp_query.count_tps(db, node_id=node_id, node_prefix=node_prefix)
            if node_id:
                print(f"{node_id} のインターフェース数: {total}")
            elif node_prefix:
                detail = ", ".join([f"{nid}:{c}" for nid, c in by_node])
                print(f"{node_prefix}* のインターフェース合計: {total} ({detail})")
            else:
                print(f"全ノードのインターフェース合計: {total}")
            return

    # 2) List intent?
    lst = jp_query.detect_list_intent(question)
    if lst:
        action = lst.get("action")
        node_prefix = lst.get("node_prefix")
        node_id = lst.get("node_id")
        if action == "list_nodes":
            nodes = jp_query.list_nodes(db, node_prefix=node_prefix)
            if not nodes:
                print("(no nodes)")
                return
            if node_prefix:
                print(f"{node_prefix}* のデバイス一覧:")
            else:
                print("デバイス一覧:")
            for n in nodes:
                print(f"- {n}")
            return
        if action == "list_tps":
            tps = jp_query.list_tps(db, node_id=node_id, node_prefix=lst.get("node_prefix"))
            if not tps:
                print("(no interfaces)")
                return
            if node_id:
                print(f"{node_id} のインターフェース一覧:")
            elif node_prefix:
                print(f"{node_prefix}* のインターフェース一覧:")
            else:
                print("インターフェース一覧:")
            for nid, tid in tps:
                print(f"- {nid}:{tid}")
            return
        if action == "list_routes":
            routes = jp_query.list_routes(db, node_id=node_id, node_prefix=node_prefix)
            if not routes:
                print("(no routes)")
                return
            if node_id:
                print(f"{node_id} のルート一覧:")
            elif node_prefix:
                print(f"{node_prefix}* のルート一覧:")
            else:
                print("ルート一覧:")
            for nid, vrf, prefix, nh, proto in routes:
                nh_label = nh or "?"
                if nh:
                    peer = jp_query.resolve_tp_by_ip(db, nh)
                    if peer:
                        nh_label += f" ({peer[0]}:{peer[1]})"
                tail = f" ({proto})" if proto else ""
                print(f"- {nid} vrf={vrf} {prefix} -> {nh_label}{tail}")
            return

    # 2.5) Address intent?
    addr = jp_query.detect_address_intent(question)
    if addr:
        rows = jp_query.list_addresses(db, node_id=addr.get("node_id"), node_prefix=addr.get("node_prefix"))
        if not rows:
            print("(no addresses)"); return
        if addr.get("node_id"):
            print(f"{addr['node_id']} のアドレス一覧:")
        elif addr.get("node_prefix"):
            print(f"{addr['node_prefix']}* のアドレス一覧:")
        else:
            print("アドレス一覧:")
        for nid, tid, ip, plen in rows:
            mask = f"/{plen}" if plen is not None else ""
            iptxt = ip + mask if ip else "-"
            print(f"- {nid}:{tid} {iptxt}")
        return

    # 2.6) VLAN/SVI intent?
    v = jp_query.detect_vlan_intent(question)
    if v:
        action = v.get("action")
        if action == "list_vlan_tps":
            tps = jp_query.list_vlan_tps(db, int(v.get("vlan")))
            if not tps:
                print("(no interfaces)"); return
            print(f"VLAN{v.get('vlan')} のインターフェース一覧:")
            for nid, tid in tps:
                print(f"- {nid}:{tid}")
            return
        if action == "list_svis":
            svis = jp_query.list_svis(db, node_id=v.get("node_id"), node_prefix=v.get("node_prefix"))
            if not svis:
                print("(no SVI)"); return
            if v.get("node_id"):
                print(f"{v['node_id']} のSVI一覧:")
            elif v.get("node_prefix"):
                print(f"{v['node_prefix']}* のSVI一覧:")
            else:
                print("SVI一覧:")
            for nid, tid, ip, plen in svis:
                mask = f"/{plen}" if plen is not None else ""
                iptxt = ip + mask if ip else "-"
                print(f"- {nid}:{tid} {iptxt}")
            return

    # 2.7) Routing overview intent without '一覧'
    rsum = jp_query.detect_routing_overview_intent(question)
    if rsum:
        routes = jp_query.list_routes(db, node_id=rsum.get("node_id"), node_prefix=rsum.get("node_prefix"))
        if not routes:
            print("(no routes)"); return
        if rsum.get("node_id"):
            print(f"{rsum['node_id']} のルート一覧:")
        elif rsum.get("node_prefix"):
            print(f"{rsum['node_prefix']}* のルート一覧:")
        else:
            print("ルート一覧:")
        for nid, vrf, prefix, nh, proto in routes:
            nh_label = nh or "?"
            if nh:
                peer = jp_query.resolve_tp_by_ip(db, nh)
                if peer:
                    nh_label += f" ({peer[0]}:{peer[1]})"
            tail = f" ({proto})" if proto else ""
            print(f"- {nid} vrf={vrf} {prefix} -> {nh_label}{tail}")
        return

    # 3) Network summary intent?
    if jp_query.detect_summary_intent(question):
        try:
            nodes = jp_query.list_nodes(db)
            n_nodes = len(nodes)
            n_links = jp_query.count_links(db)
            total_tps, _ = jp_query.count_tps(db)
            print("ネットワーク概要:")
            print(f"- デバイス数: {n_nodes}")
            print(f"- インターフェース数: {total_tps}")
            print(f"- リンク数: {n_links}")
            if nodes:
                print("- デバイス一覧:")
                for n in nodes:
                    print(f"  - {n}")
            # adjacency (including isolated)
            if show_links is not None:
                print("- 接続一覧:")
                show_links.print_adjacency_full(db)
            return
        except Exception as e:
            print(f"[ERROR] summary: {e}")
            # fall-through to retrieval if summary failed

    # 4) Connection intent?
    if any(x in question for x in ["接続", "つなが", "繋が", "connected", "接続先", "対向", "どんな接続", "どういう接続"]):
        ids = jp_query.extract_ids(question)
        if show_links is None:
            print("[WARN] show_links not importable; falling back to retrieval")
        else:
            if ids.get("node_id") and ids.get("tp_id"):
                edges = show_links.filter_edges(show_links.load_edges(db), tp=f"{ids['node_id']}:{ids['tp_id']}")
                if not edges:
                    print("(no links)"); return
                show_links.print_edges(edges, fmt="list")
                return
            elif ids.get("node_id"):
                show_links.print_adjacency_full(db, node=ids["node_id"])
                return
            else:
                show_links.print_adjacency_full(db)
                return

    # 5) Retrieval intent
    intent_type = jp_query.detect_type(question)
    ids: Dict[str, str] = jp_query.extract_ids(question)

    filters: Dict[str, str] = {}
    if intent_type:
        filters["type"] = intent_type
    for key in ("node_id", "tp_id", "link_id"):
        if key in ids:
            filters[key] = ids[key]

    match_q = jp_query.build_match_terms(question, ids)
    if debug:
        print("-- filters:", filters)
        print("-- match_q:", match_q)
    hits = jp_query.retrieve(db, match_q, filters, k=k)

    if mode == "json":
        import json
        print(json.dumps({"hits": hits}, ensure_ascii=False, indent=2))
        return
    if mode == "context":
        print(jp_query.make_context(hits))
        return

    # Optional QA step
    if qa:
        if not hits:
            print("(no hits; QA skipped)")
            return
        if rag_qa is None:
            print("[WARN] rag_qa not importable; printing context only")
            print(jp_query.make_context(hits))
            return
        prompt = rag_qa.build_prompt(question, hits)
        if dry_run or getattr(rag_qa, "OpenAI", None) is None:
            print("=== PROMPT (dry-run) ===")
            print(prompt)
            return
        answer = rag_qa.call_openai(prompt, model=model)
        print(answer or prompt)
        return

    # summary
    if not hits:
        print("(no hits)")
        return
    for i, h in enumerate(hits, 1):
        obj = h.get("object", {})
        label = f"[{i}] {h.get('type','')}"
        if h.get("node-id"):
            label += f" node={h['node-id']}"
        if h.get("tp-id"):
            label += f" tp={h['tp-id']}"
        if h.get("link-id"):
            label += f" link={h['link-id']}"
        print(label)
        if obj.get("text"):
            print("  " + obj["text"])  # one-line summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rag.db")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--mode", choices=["summary", "json", "context"], default="summary")
    ap.add_argument("--debug", action="store_true")
    ap.add_argument("--qa", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--model", default="gpt-4o-mini")
    args = ap.parse_args()

    print("日本語で質問してください（exit/quit で終了）")
    while True:
        try:
            q = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()  # newline
            break
        if not q:
            continue
        if q.lower() in {"exit", "quit", ":q"}:
            break
        try:
            one_turn(args.db, q, args.k, args.mode, args.debug, args.qa, args.dry_run, args.model)
        except Exception as e:
            print(f"[ERROR] {e}")

    print("bye")


if __name__ == "__main__":
    main()

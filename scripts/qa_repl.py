#!/usr/bin/env python3
"""
Interactive QA REPL (retrieval + optional OpenAI answer)

- Repeatedly prompts for a question
- Retrieves context from SQLite FTS5 (rag.db) via rag_qa.retrieve
- Builds a prompt and either prints it (dry-run) or calls OpenAI for an answer

Usage (repo root):
  python3 scripts/qa_repl.py --db rag.db --k 5 --dry-run
  python3 scripts/qa_repl.py --db rag.db --k 5               # needs OPENAI_API_KEY

Tips:
- Per-turn filters: append "| filters key=value key=value" to a question
  Example: "L3SW1:ae1 の状態は？ | filters type=tp node_id=L3SW1"

Exit with: exit / quit / :q
"""
from __future__ import annotations

import argparse
import sys

from pathlib import Path
THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))

import rag_qa  # noqa: E402


def parse_inline_filters(raw: str):
    if "|" not in raw:
        return raw.strip(), {}
    q, tail = raw.split("|", 1)
    tail = tail.strip()
    # expect "filters k=v k=v"
    parts = tail.split()
    filt_items = []
    if parts and parts[0].lower() == "filters":
        filt_items = parts[1:]
    filters = rag_qa.parse_filters(filt_items)
    return q.strip(), filters


def one_turn(db: str, question: str, k: int, model: str, dry_run: bool, debug: bool):
    qtext, filters = parse_inline_filters(question)
    hits = rag_qa.retrieve(db, qtext, filters=filters, k=k, debug=debug)
    prompt = rag_qa.build_prompt(qtext, hits)
    if dry_run or getattr(rag_qa, "OpenAI", None) is None:
        print("=== PROMPT (dry-run) ===")
        print(prompt)
        return
    answer = rag_qa.call_openai(prompt, model=model)
    print(answer or prompt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="rag.db")
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--model", default="gpt-4o-mini")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--debug", action="store_true")
    args = ap.parse_args()

    print("QAモードです。質問を入力してください（exit/quit/:q で終了）。")
    while True:
        try:
            line = input("> ").strip()
        except (KeyboardInterrupt, EOFError):
            print()
            break
        if not line:
            continue
        if line.lower() in {"exit", "quit", ":q"}:
            break
        try:
            one_turn(args.db, line, args.k, args.model, args.dry_run, args.debug)
        except Exception as e:
            print(f"[ERROR] {e}")

    print("bye")


if __name__ == "__main__":
    main()


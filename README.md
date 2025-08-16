# README.md

## Overview
This repo ships an IETF-based network model (JSON Schema), a sample YAML instance, and a minimal RAG stack using SQLite/FTS5.

- Validation: JSON Schema Draft 2020-12
- ETL: YAML → JSON Lines (objects.jsonl)
- Ingest: SQLite + FTS5
- QA: Retrieve context via BM25 → summarize with an LLM (OpenAI) or dry-run

## Requirements
- macOS (system `sqlite3` supports FTS5)
- Python 3.10+
- Install deps:
  ```bash
  pip install -r requirements.txt
  ```

## 1) ETL
```bash
python3 scripts/etl.py   --schema schema/schema.json   --data   data/sample.yaml   --out    outputs/objects.jsonl
```

## 2) SQLite/FTS5 ingest
```bash
rm -f rag.db
python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl
```

## 3) Retrieval
```bash
python3 scripts/rag_retriever.py --db rag.db --q "ae1 oper up" --k 5
```

## 4) QA
```bash
python3 scripts/rag_qa.py --db rag.db   --q "What is the state of L3SW1:ae1?"   --filters type=tp node_id=L3SW1 --k 3 --dry-run --debug
```

---

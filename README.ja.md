# README.ja.md

## プロジェクト概要
IETF ベースのネットワークモデル（JSON Schema）と、そのサンプル YAML、さらに RAG（SQLite/FTS5）で質問応答できる最小構成のツール群を提供します。

- スキーマ検証：Draft 2020-12（`jsonschema`）
- ETL：YAML → 検索用 JSON Lines（objects.jsonl）
- 取り込み：SQLite + FTS5（全文検索）
- QA：FTS5 でコンテキスト抽出 → LLM で要約（OpenAI もしくはドライラン）

## 前提
- macOS（標準の `sqlite3` は FTS5 対応）
- Python 3.10+ 推奨
- 依存インストール
  ```bash
  pip install -r requirements.txt
  ```

## 1) ETL：YAML → JSONL 生成
```bash
python3 scripts/etl.py   --schema schema/schema.json   --data   data/sample.yaml   --out    outputs/objects.jsonl
```

## 2) SQLite/FTS5 にロード
```bash
rm -f rag.db
python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl
```

## 3) 検索
```bash
python3 scripts/rag_retriever.py --db rag.db --q "ae1 oper up" --k 5
```

## 4) QA
```bash
python3 scripts/rag_qa.py --db rag.db   --q "L3SW1:ae1 の状態は？"   --filters type=tp node_id=L3SW1 --k 3 --dry-run --debug
```

---

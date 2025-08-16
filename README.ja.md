# README.ja.md

## 概要

このリポジトリは **IETF ネットワークモデル**に基づいた JSON Schema、サンプル YAML データ、検証スクリプト、および RAG (Retrieval-Augmented Generation) 用の簡易 CMDB 環境を提供します。  
運用属性（`operational:*`）を CMDB から取り込み、IETF YANG モデルを JSON Schema として活用できるようになっています。  

---

## コンテンツ

- **schema/schema.json**  
  JSON Schema (Draft 2020-12 準拠)。  
  RFC モデル（例: RFC 8345, RFC 8346, RFC 8944）をベースにしつつ、`operational:*` 拡張を追加。

- **data/sample.yaml**  
  サンプルネットワーク構成。  
  ノード・TP・リンクに加え、L2/L3 属性や運用状態を含む。

- **scripts/validate.py**  
  YAML インスタンスを JSON Schema Draft 2020-12 で検証。  
  `$ref` を解決するために `RefResolver` を利用。

- **tests/test_validate.py**  
  pytest を用いたスモークテスト。  
  サンプル YAML がスキーマに適合していることを確認。

- **scripts/etl.py**  
  YAML → JSONL に変換する ETL スクリプト。  
  CMDB に取り込む前処理。

- **scripts/loadJSONL.py**  
  JSONL を SQLite (FTS5 対応) にロード。  
  軽量な CMDB として検索可能に。

- **scripts/rag_retriever.py**  
  SQLite FTS5 を使った検索（フィルタ付き）。

- **scripts/rag_qa.py**  
  検索結果をコンテキストとして OpenAI API で QA 実行。  
  API キーが無い場合は **Dry Run** としてプロンプト内容を出力（課金なし）。  
  API キーを設定した場合は **回答を生成**（OpenAI API を実行するため課金が必要）。

- **README.md / README.ja.md**  
  英語版・日本語版のドキュメント。

---

## 参照 RFC

- [RFC 8345: A YANG Data Model for Network Topologies](https://www.rfc-editor.org/rfc/rfc8345)  
- [RFC 8346: A YANG Data Model for Layer 3 Topologies](https://www.rfc-editor.org/rfc/rfc8346)  
- [RFC 8944: A YANG Data Model for Layer 2 Network Topologies](https://www.rfc-editor.org/rfc/rfc8944)  

---

## Usage

### ① YAML でネットワークトポロジを記述
```yaml
# data/sample.yaml
type: tp
network-id: nw1
node-id: L3SW1
tp-id: ae1
operational: 
  tp-state:
    admin-status: up
    oper-status: up
    mtu: 1500
```

### ② ETL: YAML → JSONL → SQLite
```bash
# YAML を JSONL に変換
python3 scripts/etl.py --schema schema/schema.json --data data/sample.yaml --out outputs/objects.jsonl

# JSONL を SQLite にロード
python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl --reset
```

確認:
```bash
sqlite3 rag.db "SELECT rowid,type,node_id,tp_id,substr(text,1,60) FROM docs LIMIT 5;"
```

### ③ RAG 検索
```bash
python3 scripts/rag_retriever.py --db rag.db --q "mtu 1500" --filters type=tp node_id=L3SW1 --k 3
```

### ④ QA (OpenAI API と連携)
```bash
# Dry Run (APIキーなし): プロンプトを表示するだけ、課金なし
python3 scripts/rag_qa.py --db rag.db --q "L3SW1:ae1 の状態は？" --filters type=tp node_id=L3SW1 --k 3 --dry-run

# OpenAI APIキーを設定した場合: 実際に回答を生成（OpenAI API を実行するため課金が必要）
export OPENAI_API_KEY=sk-xxxx
python3 scripts/rag_qa.py --db rag.db --q "L3SW1:ae1 の状態は？" --filters type=tp node_id=L3SW1 --k 3
```

---

## 注意事項
- **Dry Run**: API キー未設定時、プロンプトのみ出力（課金なし）。  
- **API キー設定時**: OpenAI API を実行するため **課金が必要**。  

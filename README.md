# CMDB MCP — Ansible Wrapper風フルセット

`mcp-ansible-wrapper` とほぼ同じ運用感で立てられる **CMDB MCP サーバ** 一式です。

- FastAPI + SQLite(JSON1/FTS5)
- `mcpctl.sh`（build/start/stop/logs/health/rebuild）
- `/health`, `/tools/list`, `/tools/call`
- Bearer 認証（`REQUIRE_AUTH=1` のとき必須／トークンは `MCP_TOKEN`）
- JSONLアクセスログ（JST, 10イベント番号互換）

## 0) 前提

- Docker/Compose or Python 3.11+
- curl, jq（動作確認用）

## 1) 環境変数（必要なら）

```bash
cp .env.example .env
# 編集例
echo 'REQUIRE_AUTH=1' >> .env
echo 'MCP_TOKEN=secret123' >> .env
```

## 2) Docker で起動

```bash
./mcpctl.sh build
./mcpctl.sh up
./mcpctl.sh health
./mcpctl.sh logs   # Ctrl+C で抜ける
```

## 3) ローカル（venv）で起動

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 9101
```

## 4) 疎通（REQUIRE_AUTH=1 の場合は Authorization が必要）

```bash
BASE=http://localhost:9101
AUTH='Authorization: Bearer secret123'  # .env に合わせる

curl -s -H "$AUTH" $BASE/health | jq .
curl -s -H "$AUTH" $BASE/tools/list | jq .

# Upsert
curl -s -H "$AUTH" -H 'Content-Type: application/json' \
  -X POST $BASE/tools/call -d '{
  "name":"cmdb.upsert",
  "arguments":{"kind":"node","id":"r1","data":{"name":"r1","asn":65001,"role":"edge"}}
}' | jq .

# Get
curl -s -H "$AUTH" -H 'Content-Type: application/json' \
  -X POST $BASE/tools/call -d '{
  "name":"cmdb.get",
  "arguments":{"kind":"node","id":"r1"}
}' | jq .

# Search
curl -s -H "$AUTH" -H 'Content-Type: application/json' \
  -X POST $BASE/tools/call -d '{
  "name":"cmdb.search",
  "arguments":{"q":"edge OR 65001","limit":10}
}' | jq .

# Read-only SQL
curl -s -H "$AUTH" -H 'Content-Type: application/json' \
  -X POST $BASE/tools/call -d '{
  "name":"cmdb.query",
  "arguments":{"sql":"select kind,id,json_extract(data,'$.asn') as asn from objects where kind='node'"}
}' | jq .
```

## 5) Port/Volume

- Port: 9101（compose で公開）。既存 9000 と被らない。
- Volume: `./data` に DB/ログを保存。

## 6) Read-only 確認用テストスクリプト (`scripts/test_cmdb_read.py`)

CMDB API ないし SQLite を直接 SELECT/CTE で検証する簡易ランナー。

### API 例

```bash
python scripts/test_cmdb_read.py \
  --base-url http://localhost:9101 \
  --sql "SELECT name,type FROM sqlite_master ORDER BY name LIMIT 10" --json
```

### diag + CTE 例

```bash
python scripts/test_cmdb_read.py \
  --base-url http://localhost:9101 \
  --diag \
  --sql "WITH c AS (SELECT 1 AS v) SELECT * FROM c" --json
```

### オフライン (API ダウン時)

```bash
python scripts/test_cmdb_read.py --sqlite ./rag.db \
  --sql "SELECT COUNT(*) AS docs FROM docs" --json
```

### 出力サンプル

```json
{
  "ok": true,
  "summary": {"columns": ["name","type"], "count": 5, "sample": [{"name":"docs","type":"table"}]},
  "offline_mode": false
}
```

Exit code:

- 0: 成功
- 2: API 到達不可 (offline 指定なし)
- 3: SQL バリデーション/クエリエラー
- 4: offline sqlite パス不正

制限: 認証有効時の Bearer ヘッダ自動付与は未実装（必要なら拡張）。

## ログのイベント番号（互換）

1: chainlit chat request — user message received (tag: "chainlit chat request")
2: chainlit gpt input — prompt sent from chainlit to GPT (tag: "chainlit gpt input")
3: chainlit gpt output — GPT response to chainlit incl. decision/result (tag: "chainlit gpt output")
4: chainlit mcp request — payload from chainlit to MCP (tag: "chainlit mcp request")
5: mcp request — payload received by MCP from chainlit (tag: "mcp request")
6: mcp gpt input — prompt sent from MCP to GPT (tag: "mcp gpt input")
7: mcp gpt output — response received by MCP from GPT (tag: "mcp gpt output")
8: mcp reply — final reply produced by MCP (tag: "mcp reply")
9: chain mcp reply — reply received by chainlit from MCP (tag: "chain mcp reply")
10: chain reply — final answer output by chainlit (tag: "chain reply")

※ 本サーバでは主に 1/2/5/8 を使用（適宜追加可能）。

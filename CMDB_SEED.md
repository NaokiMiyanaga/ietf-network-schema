# CMDB Seed (Minimal Fixture)

最小限のオブジェクトを投入して `cmdb.search` / `cmdb.query` が空 `{items:[],count:0}` にならないようにするためのシード手順。

## セット内容

| kind | id    | 概要 |
|------|-------|------|
| node | r1    | router cisco ASN65001 |
| node | r2    | router juniper ASN65002 |
| node | l2a   | switch arista stack=1 |
| node | l2b   | switch arista stack=2 |
| link | r1-r2 | r1-r2 point-to-point |

## 使い方

```bash
cd ietf-network-schema
python scripts/seed_cmdb.py --db ./data/cmdb.sqlite3
```

再実行しても上書きされる（idempotent）。

## 動作確認

```bash
python - <<'PY'
from db import get_conn, search, select_sql, init_db
c = get_conn()
init_db(c)
print('search("router") =>', search('router'))
print('search("") =>', search('') )  # 空クエリ上位
print(select_sql(c, "select count(*) as nodes from objects where kind='node'"))
PY
```

## 期待されるルーティング例

- 「ルータ台数」 → `cmdb.query` (SELECT count) + `ansible.inventory`
- 「r1 のインタフェース」 → `cmdb.search` / `cmdb.query` (将来: interface テーブル拡張)

## 次の拡張候補

- interface テーブルの正規化 (kind=iface)
- link 帯域/メディア属性
- policy 用タグ (edge/core)

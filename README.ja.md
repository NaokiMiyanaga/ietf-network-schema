**ライセンス:** MIT

# README.ja.md

## 概要

このリポジトリは **IETF ネットワークモデル**に基づいた JSON Schema、サンプル YAML データ、検証スクリプト、およびCMDB 環境を提供します。  
運用属性（`operational:*`）を CMDB から取り込み、IETF YANG モデルを JSON Schema として活用できるようになっています。  

---

## コンテンツ

- **schema/schema.json**  
  JSON Schema (Draft 2020-12 準拠)。  
  RFC モデル（例: RFC 8345, RFC 8346, RFC 8944）をベースにしつつ、`operational:*` 拡張を追加。

- **data/sample.yaml**  
  FRR を用いた検証環境のマスター YAML（意図／intended）を IETF モデルへマッピングしたサンプル。  
  ノード・TP・リンク・L2/L3 属性を含みます。`operational:*` は省略可能で、欠落時は ETL が既定値を補完します。

- **scripts/validate.py**  
  YAML インスタンスを JSON Schema Draft 2020-12 で検証。  
  `$ref` を解決するために `RefResolver` を利用。

- **scripts/test_validate.py**  
  pytest を用いたスモークテスト。  
  サンプル YAML がスキーマに適合していることを確認。

- **scripts/etl.py**  
  YAML → JSONL に変換する ETL スクリプト。  
  CMDB に取り込む前処理に加え、欠落した `operational:*` の既定値を補完します。

- **scripts/loadJSONL.py**  
  JSONL を SQLite (FTS5 対応) にロード。  
  軽量な CMDB として検索可能に。

- **scripts/rag_retriever.py**  
  SQLite FTS5 を使った検索（フィルタ付き）。

- **scripts/rag_qa.py**  
  検索結果をコンテキストとして OpenAI API で QA 実行。  
  API キーが無い場合は **Dry Run** としてプロンプト内容を出力（課金なし）。  
  API キーを設定した場合は **回答を生成**（OpenAI API を実行するため課金が必要）。

- **scripts/jp_query.py**  
  日本語の自然文から FTS 検索用クエリとフィルタを自動生成して検索（ローカル・ヒューリスティック）。

- **scripts/jp_repl.py**  
  日本語で対話的に検索・一覧・接続表示・（任意で）QA を実行できる REPL。

- **scripts/show_links.py**  
  インターフェース↔インターフェースの接続関係を一覧表示（ノード/IFでの絞り込み対応）。

- **scripts/qa_repl.py**  
  取得（R）＋生成（G）を対話的に実行する QA 用 REPL。`--dry-run` でプロンプト確認、APIキー設定時は回答生成。

- **README.md / README.ja.md**  
  英語版・日本語版のドキュメント。

---

## 参照 RFC

- [RFC 8345: A YANG Data Model for Network Topologies](https://www.rfc-editor.org/rfc/rfc8345)  
- [RFC 8346: A YANG Data Model for Layer 3 Topologies](https://www.rfc-editor.org/rfc/rfc8346)  
- [RFC 8944: A YANG Data Model for Layer 2 Network Topologies](https://www.rfc-editor.org/rfc/rfc8944)  

---

## 依存関係（Dependencies）

- 必須（ローカル検索・一覧・ETL）
  - Python 3.10 以上（推奨: 3.11+）
  - パッケージ: `jsonschema>=4.18.0`, `pyyaml`（`requirements.txt`）
  - SQLite3（標準ライブラリ）
- 任意（QA で OpenAI を使う場合のみ）
  - `openai`（推奨: 1.x 系）

インストール例（推奨: 仮想環境）
```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -r requirements.txt          # 必須分
# QA 機能を使う場合のみ:
python -m pip install openai
```

macOS（Homebrew Python）の注意: PEP 668 によりグローバルへの `pip install` が制限されます。仮想環境（上記）か `pipx` を利用してください。

## Usage

### 検証（バリデーション）
```bash
python3 scripts/validate.py --schema schema/schema.json --data data/sample.yaml
```

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

### ③ 検索
```bash
python3 scripts/rag_retriever.py --db rag.db --q "mtu 1500" --filters type=tp node_id=L3SW1 --k 3
```

#### 日本語でクエリ（ヒューリスティック、オフライン）
```bash
python3 scripts/jp_query.py --db rag.db --q "L3SW1:ae1 の状態は？" --k 3 --debug
```
出力は `hits`（BM25順）と `context`（プロンプト貼り付け用）。
例: 「L3SW1 の MTU 1500」「リンクの遅延 2ms」「ポート ae1 の duplex」など。

対話モード（REPL）:
```bash
python3 scripts/jp_repl.py --db rag.db --k 5           # summary（要約表示）
python3 scripts/jp_repl.py --db rag.db --k 5 --mode context  # コンテキスト表示
python3 scripts/jp_repl.py --db rag.db --k 5 --mode json     # JSON表示
# デバッグ表示（導出された filters / MATCH クエリ）：
python3 scripts/jp_repl.py --db rag.db --k 5 --debug
# LLM で回答（OpenAI APIキー設定時）。--dry-run でプロンプトのみ表示：
python3 scripts/jp_repl.py --db rag.db --k 3 --qa --dry-run
python3 scripts/jp_repl.py --db rag.db --k 3 --qa  # 実回答（課金発生）
# 入力プロンプトが出ます。exit / quit / :q で終了。
```

よく使う自然文（例）:
- アドレス/IF系: 「アドレスは？」「L3SW1 のアドレス」
- SVI/VLAN系: 「SVI一覧」「L3SW* のSVI一覧」「VLAN100 のIF一覧」
- 接続系: 「どんな接続？」「L3SW1 の接続」「L3SW1:ae1 の接続先」
- ルート系: 「ルート一覧」「L3SW1 のルート一覧」「ルーティングは？」
- 要約: 「どんなネットワーク？」（台数・IF数・リンク数・隣接を要約表示）

### 接続の表示（インターフェース↔インターフェース）
- 一覧表示:
```bash
python3 scripts/show_links.py --db rag.db                      # すべてのリンク
python3 scripts/show_links.py --db rag.db --node L3SW1         # ノードに関わるリンク
python3 scripts/show_links.py --db rag.db --tp L3SW1:ae1       # 特定IFの対向
```
- REPLでも自然文でOK（例）:
  - 「何のインターフェースが何のインターフェースと接続されている？」
  - 「L3SW1:ae1 の接続先は？」
  - 「L2SW1 の接続先は？」


### ④ QA（OpenAI API 連携）

**重要:** API キー未設定＝ドライラン（無料）。API キー設定＝回答生成（有償／課金発生）。

```bash
python3 scripts/rag_qa.py --db rag.db --q "What is the state of L3SW1:ae1?" --filters type=tp node_id=L3SW1 --k 3
```

対話型（RAG QA REPL）:
```bash
python3 scripts/qa_repl.py --db rag.db --k 5 --dry-run     # 無料（プロンプトのみ）
export OPENAI_API_KEY=sk-xxxx
python3 scripts/qa_repl.py --db rag.db --k 5               # 有償（回答生成）
# 1行でフィルタ指定も可能:  質問文 | filters key=value ...
# 例: "L3SW1:ae1 の状態は？ | filters type=tp node_id=L3SW1"
```

出力例:

```
L3SW1:ae1の状態は、管理状態（admin）が「up」、運用状態（oper）が「up」です。MTUは1500、デュプレックスはフルです。[1]
```

※ 現状はプロンプトで **日本語で回答** と指定しているため、質問が英語でも日本語で返答されます。今後、**質問言語に合わせて回答言語も自動で切り替える**ように更新予定です。

---

## Operational の既定値（欠落時の補完）

- 範囲: 既定値の適用は ETL 実行時のみです（JSON Schema の検証では自動補完しません）。
- 適用箇所と値:
  - `operational:tp-state`: `admin-status=up`, `oper-status=unknown`, `speed-bps=0`, `duplex=unknown`, `mtu=1500`
  - `operational:link-state`: `oper-status=unknown`, `bandwidth=0`
  - `ietf-l2-topology:l2-termination-point-attributes.operational:lag-state`: `aggregate-oper-status=unknown`
- 挙動: コンテナ自体が無い場合は作成して既定値を設定。既に値があるキーは上書きしません。
- 目的: FRR 由来の「意図（intended）」YAML では実行時の状態が省略されがちなので、下流の検索・要約の安定性を保ちつつ「不明（unknown）」を明示します。

## サンプルネットワーク（抜粋）

```yaml
ietf-network:networks:
  network:
  - network-id: nw1
    node:
    - node-id: L3SW1
      ietf-network-topology:termination-point:
      - tp-id: ae2
        ietf-l3-unicast-topology:l3-termination-point-attributes:
          ip-address: 192.0.2.2
          prefix-length: 30
      - tp-id: vlan100
        ietf-l3-unicast-topology:l3-termination-point-attributes:
          ip-address: 10.100.0.1
          prefix-length: 24
      operational:routing:
        routes:
        - vrf: default
          prefix: 0.0.0.0/0
          next-hop: 192.0.2.1
          protocol: static
    - node-id: L3SW2
      ietf-network-topology:termination-point:
      - tp-id: ae2
        ietf-l3-unicast-topology:l3-termination-point-attributes:
          ip-address: 192.0.2.1
          prefix-length: 30
      - tp-id: vlan100
        ietf-l3-unicast-topology:l3-termination-point-attributes:
          ip-address: 10.100.0.2
          prefix-length: 24
    - node-id: L2SW1
      ietf-network-topology:termination-point:
      - tp-id: ae1
    - node-id: L2SW2
      ietf-network-topology:termination-point:
      - tp-id: ae1
        ietf-l2-topology:l2-termination-point-attributes:
          vlan-id: 101
    ietf-network-topology:link:
    - link-id: L3SW1-ae1__L2SW1-ae1-vlan100
      ietf-network-topology:source:      { source-node: L3SW1, source-tp: ae1 }
      ietf-network-topology:destination: { dest-node:   L2SW1, dest-tp:   ae1 }
    - link-id: L3SW2-ae1__L2SW2-ae1
      ietf-l2-topology:l2-link-attributes:
        vlan-id: 101
      ietf-network-topology:source:      { source-node: L3SW2, source-tp: ae1 }
      ietf-network-topology:destination: { dest-node:   L2SW2, dest-tp:   ae1 }
    - link-id: L3SW1-ae2__L3SW2-ae2
      ietf-network-topology:source:      { source-node: L3SW1, source-tp: ae2 }
      ietf-network-topology:destination: { dest-node:   L3SW2, dest-tp:   ae2 }
```

ヒント: YAML を更新したら、`python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl --reset` で DB を再生成してください。


## ライセンス

このプロジェクトは **MIT ライセンス** の下で配布されています。詳細は [LICENSE](LICENSE) をご覧ください。

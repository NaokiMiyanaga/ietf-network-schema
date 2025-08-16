# ietf-network-schema

IETF ベースのネットワークモデルの JSON Schema とサンプルデータ、および検証スクリプトをまとめたリポジトリです。  
ネットワーク構成管理（CMDB）からの Operational 属性も取り込み、IETF YANG モデルをベースに JSON Schema として利用可能な形にしています。

---

## 含まれるファイル

- **schema.json**  
  IETF Draft 2020-12 に準拠した JSON Schema。  
  RFC 系 IETF モデル（例: RFC 8345, RFC 8346, RFC 8944 など）を元に、Operational 属性（`operational:*`）を拡張しています。

- **sample.yaml**  
  上記スキーマに準拠したサンプルインスタンス。  
  termination-point, link, L2/L3 attributes, operational state などを含む。

- **validate.py**  
  JSON Schema Draft 2020-12 を用いて YAML インスタンスを検証するスクリプト。  
  `$ref` 解決のために `RefResolver` を利用し、ローカルファイルを参照可能に調整。

- **test_validate.py**  
  pytest によるスモークテスト。サンプル YAML がスキーマに合致することを確認。

- **README.ja.md / README.en.md**  
  日本語・英語の説明ファイル。

---

## 参照している RFC

- [RFC 8345: A YANG Data Model for Network Topologies](https://www.rfc-editor.org/rfc/rfc8345)
- [RFC 8346: A YANG Data Model for Layer 3 Topologies](https://www.rfc-editor.org/rfc/rfc8346)
- [RFC 8944: A YANG Data Model for Layer 2 Network Topologies Topologies](https://www.rfc-editor.org/rfc/rfc8944)

---

## 使い方

### 1. バリデーション実行

```bash
python3 validate.py --schema schema.json --data sample.yaml
```

成功すると `OK: validation passed` が表示されます。

### 2. pytest による検証

```bash
pytest -q
```

全テストが `1 passed` となれば正しく動作しています。

---

## 背景と目的

- **背景**  
  ネットワーク運用で利用する CMDB から取得した Operational 情報を、IETF YANG モデルに基づいた JSON Schema に統合。  
  ネットワーク機器やリンクの状態 (`operational:*` 属性) を正規化して取り扱うための仕組み。

- **目的**  
  - IETF モデルとの互換性確保  
  - CMDB からの状態情報を統合  
  - JSON Schema での自動検証と CI/CD パイプラインへの組み込み  

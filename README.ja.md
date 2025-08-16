# IETF Network Schema (日本語版)

このリポジトリは IETF ベースのネットワークスキーマとサンプル YAML、
および検証スクリプトをまとめたものです。

## ディレクトリ構成
- `schema/` : JSON Schema
- `data/` : サンプル YAML
- `scripts/` : 検証・ETL スクリプト
- `outputs/` : ETL 出力（一時ファイル、git管理外）

## 依存関係
```
pip install -r requirements.txt
```

## バリデーション実行例
```
python scripts/validate.py --schema schema/schema.json --data data/sample.yaml
```

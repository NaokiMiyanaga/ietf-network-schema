#!/usr/bin/env bash
set -euo pipefail

# -------------------------
# CLI
# -------------------------
MODE="strict"
DB="rag.db"
DATA_YAML="data/sample.yaml"
SCHEMA_JSON="schema/schema.json"
OUT_JSONL="outputs/objects.jsonl"
ENSURE_DEPS=0

usage () {
  cat <<USAGE
Usage: $0 [--mode strict|permissive] [--db FILE] [--data FILE] [--schema FILE] [--out FILE] [--ensure-deps]
  --mode            strict (default) | permissive
  --db              SQLite DB path (default: rag.db)
  --data            YAML input      (default: data/sample.yaml)
  --schema          JSON Schema     (default: schema/schema.json)
  --out             JSONL output    (default: outputs/objects.jsonl)
  --ensure-deps     足りない依存をこの Python にインストール（pip使用）
USAGE
}

while (( $# )); do
  case "$1" in
    --mode)          MODE="${2:-}"; shift 2;;
    --db)            DB="${2:-}"; shift 2;;
    --data)          DATA_YAML="${2:-}"; shift 2;;
    --schema)        SCHEMA_JSON="${2:-}"; shift 2;;
    --out)           OUT_JSONL="${2:-}"; shift 2;;
    --ensure-deps)   ENSURE_DEPS=1; shift 1;;
    -h|--help)       usage; exit 0;;
    *) echo "[build] unknown arg: $1" >&2; usage; exit 1;;
  esac
done

# -------------------------
# Python 解決（いまのシェルのものを優先）
# -------------------------
if [[ -n "${PYTHON:-}" ]]; then
  PY="$PYTHON"
elif command -v python >/dev/null 2>&1; then
  PY="$(command -v python)"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "[build] no python found in PATH" >&2; exit 1
fi

echo "[build] PY=$PY"
"$PY" - <<'PYV' || true
import sys; print("[build] Python:", sys.version.replace("\n"," "))
PYV

# -------------------------
# 依存チェック＆（任意で）インストール
# -------------------------
missing=()
"$PY" - <<'PY' || missing+=("jsonschema")
import importlib; importlib.import_module("jsonschema")
PY
"$PY" - <<'PY' || missing+=("yaml")
import importlib; importlib.import_module("yaml")
PY

if (( ${#missing[@]} )); then
  echo "[build] missing modules: ${missing[*]}"
  if (( ENSURE_DEPS )); then
    echo "[build] installing into this interpreter: $PY -m pip install -U jsonschema PyYAML"
    "$PY" -m pip install -U jsonschema PyYAML
  else
    echo "[build] HINT: \"$PY\" -m pip install -U jsonschema PyYAML" >&2
    exit 1
  fi
fi

# -------------------------
# 実行
# -------------------------
echo "[build] DATA_YAML=$DATA_YAML"
echo "[build] SCHEMA_JSON=$SCHEMA_JSON"
echo "[build] OUT_JSONL=$OUT_JSONL"
echo "[build] DB=$DB"
echo "[build] MODE=$MODE"

mkdir -p "$(dirname "$OUT_JSONL")"

# 1) Validate
"$PY" scripts/validate.py --schema "$SCHEMA_JSON" --data "$DATA_YAML"

# 2) ETL
etl_args=( --schema "$SCHEMA_JSON" --data "$DATA_YAML" --out "$OUT_JSONL" )
if [[ "$MODE" == "permissive" ]]; then etl_args+=( --mode permissive ); fi
"$PY" scripts/etl.py "${etl_args[@]}"

# 3) Load
"$PY" scripts/loadJSONL.py --db "$DB" --jsonl "$OUT_JSONL" --reset

echo "[build] done -> $DB"
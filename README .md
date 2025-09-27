**License:** MIT

# README.md

## Overview

This repository provides a **JSON Schema based on IETF network models**, sample YAML data, validation scripts, and a lightweight CMDB environment .  
Operational attributes (`operational:*`) are integrated from CMDB, enabling the use of IETF YANG models as JSON Schema.  

---

## Contents

- **schema/schema.json**  
  JSON Schema (Draft 2020-12 compliant).  
  Based on IETF RFC models (e.g., RFC 8345, RFC 8346, RFC 8944) with `operational:*` extensions.

- **data/sample.yaml**  
  A sample network instance.  
  Includes nodes, TPs, links, L2/L3 attributes, and operational states.

- **scripts/validate.py**  
  Validate YAML instances with JSON Schema Draft 2020-12 in **strict mode** (missing/Type mismatch fails immediately).  
  Uses `RefResolver` for `$ref` resolution.

- **tests/test_validate.py**  
  Smoke test with pytest.  
  Ensures the sample YAML conforms to the schema.

- **scripts/etl.py**  
  ETL script converting YAML → JSONL.  
  Performs pre-processing before CMDB ingest. **Default is strict (no backfill)**; only when `--mode permissive` is specified, missing `operational:*` defaults are backfilled.

- **scripts/loadJSONL.py**  
  Load JSONL into SQLite (FTS5 enabled).  
  Provides lightweight CMDB with full-text search.

- **scripts/rag_retriever.py**  
  Search using SQLite FTS5 (with filters).

- **scripts/rag_qa.py**  
  Run QA with OpenAI API using retrieved context.  
  Without API key → **Dry Run** (prints prompt, no cost).  
  With API key → **Generates answer** (requires payment).

- **README.md / README.ja.md**  
  Documentation in English and Japanese.

---

## Referenced RFCs

- [RFC 8345: A YANG Data Model for Network Topologies](https://www.rfc-editor.org/rfc/rfc8345)  
- [RFC 8346: A YANG Data Model for Layer 3 Topologies](https://www.rfc-editor.org/rfc/rfc8346)  
- [RFC 8944: A YANG Data Model for Layer 2 Network Topologies](https://www.rfc-editor.org/rfc/rfc8944)  

---

## Usage

### ① Describe network topology in YAML
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
# Convert YAML to JSONL
python3 scripts/etl.py --schema schema/schema.json --data data/sample.yaml --out outputs/objects.jsonl

# Load JSONL into SQLite
python3 scripts/loadJSONL.py --db "$CMDB_DB_PATH" --jsonl outputs/objects.jsonl --reset
```

Check:
```bash
sqlite3 "$CMDB_DB_PATH" "SELECT rowid,type,node_id,tp_id,substr(text,1,60) FROM docs LIMIT 5;"
```

### ③ Retrieval
```bash
python3 scripts/rag_retriever.py --db "$CMDB_DB_PATH" --q "mtu 1500" --filters type=tp node_id=L3SW1 --k 3
```


### ④ QA with OpenAI API

```bash
python3 scripts/rag_qa.py --db "$CMDB_DB_PATH" --q "What is the state of L3SW1:ae1?" --filters type=tp node_id=L3SW1 --k 3
```

Example output:

```
L3SW1:ae1の状態は、管理状態（admin）が「up」、運用状態（oper）が「up」です。MTUは1500、デュプレックスはフルです。[1]
```

> Note: Although the question is in English, the current system prompt instructs the model to answer **in Japanese**, so the output is Japanese. We plan to update this so the answer language matches the question.


## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.


---

## Operations & Environment (Updated: 2025‑09)

This project **builds the CMDB (SQLite) on the host**, and the resulting DB file is **volume‑mounted into the `cmdb-mcp` container**. The ETL pipeline (YAML→JSONL→SQLite) is **not** executed inside the container.

### 1) Host dependencies
- Python 3.10+
- `jsonschema>=4.18.0`
- `PyYAML>=6.0`
- SQLite with FTS5 support (macOS stock 3.3x+ is fine)

> **Tip:** The actual `python` used to run may differ from where you installed packages (Homebrew / pyenv / conda / venv). Unify them like this:
> ```bash
> PY=$(python -c "import sys; print(sys.executable)")
> "$PY" -m pip install -U jsonschema PyYAML
> "$PY" scripts/validate.py --schema schema/schema.json --data data/sample.yaml
> ```

### 2) Run the ETL on the host
```bash
# Strict validation only (non‑zero exit on failure)
python3 scripts/validate.py --schema schema/schema.json --data data/sample.yaml

# YAML → JSONL (strict; no backfill)
python3 scripts/etl.py --schema schema/schema.json --data data/sample.yaml --out outputs/objects.jsonl
# Backfill only when needed (permissive)
python3 scripts/etl.py --schema schema/schema.json --data data/sample.yaml --out outputs/objects.jsonl --mode permissive

# JSONL → SQLite (FTS5)
python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl --reset
```

### 3) Mount into Docker (`cmdb-mcp`)
In `docker-compose.yml`, **mount the host `rag.db` directly**. Do not change existing file names/paths.
```yaml
services:
  cmdb-mcp:
    volumes:
      - ./rag.db:/app/cmdb-mcp/rag.db
```

### 4) Troubleshooting
- **FTS5 trigger error**: `sqlite3.OperationalError: cannot create triggers on virtual tables`
  - Fixed: `docs_fts` uses standalone FTS (no external content). The loader writes into both `docs` and `docs_fts` explicitly.
- **Module not found**: `ModuleNotFoundError: No module named 'jsonschema'`
  - Likely different interpreters. Use the tip above to align install/run Python.
- **IETF‑derived record types fail** (e.g., `termination-point`)
  - The loader normalizes type names to `tp/node/link/network` and accepts unknown types as metadata. Required‑field checks apply only to `node/tp/link`.
- **Emergency: bypass validation** (dev/test only)
  - Temporarily skip validation in the loader:
    ```bash
    export LOADJSONL_SKIP_VALIDATE=1
    python scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl --reset
    unset LOADJSONL_SKIP_VALIDATE
    ```

### 5) Recommended practice
- Pin `jsonschema>=4.18.0, PyYAML>=6.0` in `requirements.txt`; install via `pip install -r requirements.txt`
- Add strict validation to pre‑commit/CI to block broken YAML
- In VS Code, fix the workspace **Python Interpreter** to your conda env or `.venv`

### 6) Known environment quirks
- Homebrew Python (3.12/3.13) on macOS is PEP 668 “externally managed”; global `pip install` may be blocked. Prefer `--user --break-system-packages` or a virtualenv (`python -m venv .venv`).
- With conda, make sure both `python` and `pip` are from the same conda env.

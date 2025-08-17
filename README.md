# README.md

## Overview

This repository provides a **JSON Schema based on IETF network models**, sample YAML data, validation scripts, and a lightweight CMDB environment for RAG (Retrieval-Augmented Generation).  
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
  Validate YAML instances against JSON Schema Draft 2020-12.  
  Uses `RefResolver` for `$ref` resolution.

- **tests/test_validate.py**  
  Smoke test with pytest.  
  Ensures the sample YAML conforms to the schema.

- **scripts/etl.py**  
  ETL script converting YAML → JSONL.  
  Prepares objects for CMDB ingestion.

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
python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl --reset
```

Check:
```bash
sqlite3 rag.db "SELECT rowid,type,node_id,tp_id,substr(text,1,60) FROM docs LIMIT 5;"
```

### ③ RAG Retrieval
```bash
python3 scripts/rag_retriever.py --db rag.db --q "mtu 1500" --filters type=tp node_id=L3SW1 --k 3
```

### ④ QA with OpenAI API
```bash
# Dry Run (no API key): shows prompt only, no cost
python3 scripts/rag_qa.py --db rag.db --q "What is the state of L3SW1:ae1?" --filters type=tp node_id=L3SW1 --k 3 --dry-run

# With OpenAI API key: generates answer (requires payment)
export OPENAI_API_KEY=sk-xxxx
python3 scripts/rag_qa.py --db rag.db --q "What is the state of L3SW1:ae1?" --filters type=tp node_id=L3SW1 --k 3
```

---

## Notes
- **Dry Run**: No API key → prints prompt only, no cost.  
- **With API key**: OpenAI API execution **requires payment**.  

---

## License

This project is licensed under the **MIT License**.  
See the [LICENSE](./LICENSE) file for details.


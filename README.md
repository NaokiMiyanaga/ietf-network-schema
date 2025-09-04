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

- **scripts/test_validate.py**  
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

- **scripts/jp_query.py**  
  Heuristic Japanese NL → FTS query + filters (offline). Useful to try natural language retrieval without calling any API.

- **scripts/jp_repl.py**  
  Interactive Japanese REPL for retrieval, listing, connections, and optional QA.

- **scripts/show_links.py**  
  Show interface-to-interface connections; filter by node or specific interface.

- **scripts/qa_repl.py**  
  Interactive QA REPL (retrieval + optional OpenAI answer). Use `--dry-run` to inspect prompts; with API key it generates answers.
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

Japanese NL (heuristic, offline):
```bash
python3 scripts/jp_query.py --db rag.db --q "L3SW1:ae1 の状態は？" --k 3 --debug
```

Common natural-language prompts (examples):
- Addresses: "アドレスは？", "L3SW1 のアドレス"
- SVI/VLAN: "SVI一覧", "L3SW* のSVI一覧", "VLAN100 のIF一覧"
- Connections: "どんな接続？", "L3SW1 の接続", "L3SW1:ae1 の接続先"
- Routes: "ルート一覧", "L3SW1 のルート一覧", "ルーティングは？"
- Summary: "どんなネットワーク？" (counts + adjacency)

Interactive REPL (Japanese):
```bash
python3 scripts/jp_repl.py --db rag.db --k 5                # summary view
python3 scripts/jp_repl.py --db rag.db --k 5 --mode context # show context
python3 scripts/jp_repl.py --db rag.db --k 5 --mode json    # JSON output
# Debug filters/MATCH query:
python3 scripts/jp_repl.py --db rag.db --k 5 --debug
# QA end-to-end (requires OPENAI_API_KEY). Use --dry-run to just print prompt.
python3 scripts/jp_repl.py --db rag.db --k 3 --qa --dry-run
python3 scripts/jp_repl.py --db rag.db --k 3 --qa
```

Connections (interface ↔ interface):
```bash
python3 scripts/show_links.py --db rag.db                      # all links
python3 scripts/show_links.py --db rag.db --node L3SW1         # links involving a node
python3 scripts/show_links.py --db rag.db --tp L3SW1:ae1       # peer of specific interface
```

Sample network (excerpt):
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

Tip: after editing YAML, regenerate DB with `python3 scripts/loadJSONL.py --db rag.db --jsonl outputs/objects.jsonl --reset`.

### ④ QA with OpenAI API

**Important:** Without `OPENAI_API_KEY` = Dry Run (free). With API key = live answer (paid).
```bash
# Dry Run (no API key): shows prompt only, no cost
python3 scripts/rag_qa.py --db rag.db --q "What is the state of L3SW1:ae1?" --filters type=tp node_id=L3SW1 --k 3 --dry-run

# With OpenAI API key: generates answer (requires payment)
export OPENAI_API_KEY=sk-xxxx
python3 scripts/rag_qa.py --db rag.db --q "What is the state of L3SW1:ae1?" --filters type=tp node_id=L3SW1 --k 3
```

Interactive (RAG QA REPL):
```bash
python3 scripts/qa_repl.py --db rag.db --k 5 --dry-run           # free (prompt only)
export OPENAI_API_KEY=sk-xxxx
python3 scripts/qa_repl.py --db rag.db --k 5                     # paid (answer generation)
# Per-turn filters: append "| filters key=value ..."
# Example: "L3SW1:ae1 の状態は？ | filters type=tp node_id=L3SW1"
```

---

## Notes
- **Dry Run**: No API key → prints prompt only, no cost.  
- **With API key**: OpenAI API execution **requires payment**.  

---

## License

This project is licensed under the **MIT License**.  
See the [LICENSE](./LICENSE) file for details.

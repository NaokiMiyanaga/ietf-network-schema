# ietf-network-schema

This repository provides a JSON Schema based on IETF network models, sample YAML data, and validation scripts.  
Operational attributes from the Configuration Management Database (CMDB) are also integrated, making it possible to use IETF YANG-based models as JSON Schema.

---

## Contents

- **schema.json**  
  JSON Schema compliant with Draft 2020-12.  
  Based on IETF RFC models (e.g., RFC 8345, RFC 8346, RFC 8944) and extended with operational attributes (`operational:*`).

- **sample.yaml**  
  A sample instance conforming to the schema.  
  Includes termination points, links, L2/L3 attributes, and operational state.

- **validate.py**  
  A script to validate YAML instances against the JSON Schema Draft 2020-12.  
  Uses `RefResolver` to properly handle `$ref` resolution with local files.

- **test_validate.py**  
  Smoke test using pytest to ensure the sample YAML conforms to the schema.

- **README.ja.md / README.en.md**  
  Documentation in Japanese and English.

---

## Referenced RFCs

- [RFC 8345: A YANG Data Model for Network Topologies](https://www.rfc-editor.org/rfc/rfc8345)
- [RFC 8346: A YANG Data Model for Layer 3 Topologies](https://www.rfc-editor.org/rfc/rfc8346)
- [RFC 8944: A YANG Data Model for Layer 2 Network Topologies Topologies](https://www.rfc-editor.org/rfc/rfc8944)

---

## Usage

### 1. Run validation

```bash
python3 validate.py --schema schema.json --data sample.yaml
```

If successful, it will print `OK: validation passed`.

### 2. Run pytest

```bash
pytest -q
```

If the test passes (`1 passed`), validation is working correctly.

---

## Background & Purpose

- **Background**  
  Operational data from CMDB is integrated into IETF YANG models and expressed as JSON Schema.  
  Enables consistent handling of device and link states (`operational:*` attributes).

- **Purpose**  
  - Maintain compatibility with IETF models  
  - Integrate operational state from CMDB  
  - Enable automatic validation with JSON Schema and CI/CD integration  

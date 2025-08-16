#!/usr/bin/env python3
"""
Simple JSON Schema validator (Draft 2020-12). No dynamic patching.
- Normalizes legacy refs like:
    * "schema_operational_merged.json#/$defs/..." -> "#/allOf/0/$defs/..."
    * "#/$defs/..." -> "#/allOf/0/$defs/..."
- Adds resolver aliases so refs targeting "schema_operational_merged.json" resolve to the provided --schema.
Usage:
  python3 validate.py --schema schema.json --data sample.yaml
"""
import argparse
import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator, RefResolver

def load_json(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)

def load_yaml(path: Path):
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def normalize_ref(ref: str) -> str:
    # Remove filename prefix if present (keeps the fragment)
    if "schema_operational_merged.json#" in ref:
        ref = ref.split("schema_operational_merged.json#", 1)[1]
        if not ref.startswith("#"):
            ref = "#" + ref
    # Map root $defs to allOf[0]/$defs (schema layout in this bundle)
    if ref.startswith("#/$defs/"):
        ref = ref.replace("#/$defs/", "#/allOf/0/$defs/")
    return ref

def normalize_refs(obj: Any):
    if isinstance(obj, dict):
        if "$ref" in obj and isinstance(obj["$ref"], str):
            obj["$ref"] = normalize_ref(obj["$ref"])
        for v in obj.values():
            normalize_refs(v)
    elif isinstance(obj, list):
        for x in obj:
            normalize_refs(x)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    args = ap.parse_args()

    schema = load_json(args.schema)
    instance = load_yaml(args.data)

    # Normalize problematic refs in-place
    normalize_refs(schema)

    # Build resolver with aliases for both the actual file path and the historical name
    base_uri = args.schema.resolve().as_uri()
    alias_uri = (args.schema.parent / "schema_operational_merged.json").resolve().as_uri()
    store = {base_uri: schema, alias_uri: schema}

    # Ensure $id is set to actual file's URI so local fragments resolve
    if isinstance(schema, dict):
        schema.setdefault("$id", base_uri)

    resolver = RefResolver(base_uri=base_uri, referrer=schema, store=store)
    validator = Draft202012Validator(schema, resolver=resolver)

    errors = sorted(validator.iter_errors(instance), key=lambda e: e.path)
    if errors:
        print("[VALIDATION ERROR] in", args.data.name)
        for err in errors:
            print("-", err.message)
            print("  Instance path:", "/" + "/".join([str(x) for x in err.path]))
            print("  Schema path:  /" + "/".join([str(x) for x in err.schema_path]))
        raise SystemExit(1)
    else:
        print("OK: validation passed")

if __name__ == "__main__":
    main()

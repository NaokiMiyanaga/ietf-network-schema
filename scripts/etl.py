#!/usr/bin/env python3
"""
ETL for ietf-network-schema
- Validates YAML against JSON Schema by invoking scripts/validate.py
- Extracts nodes / termination-points / links into normalized JSONL (RAG-ready)
Defaults assume repo layout (run from repo root):
  schema/schema.json
  data/sample.yaml
  outputs/objects.jsonl
  scripts/validate.py
"""
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import sys
import yaml

def run_validate(schema: Path, data: Path, validate_py: Path):
    cmd = [sys.executable, str(validate_py), "--schema", str(schema), "--data", str(data)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    print(proc.stdout.strip())
    return True

def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def make_text_for_node(n):
    nid = n.get("node-id")
    l3 = n.get("ietf-l3-unicast-topology:l3-node-attributes", {}) or {}
    name = l3.get("name")
    return f"Node {nid}" + (f" (name={name})" if name else "")

def make_text_for_tp(node_id, tp):
    tid = tp.get("tp-id")
    op = tp.get("operational:tp-state") or {}
    fields = []
    if op.get("admin-status"): fields.append(f"admin={op['admin-status']}")
    if op.get("oper-status"): fields.append(f"oper={op['oper-status']}")
    if op.get("mtu") is not None: fields.append(f"mtu={op['mtu']}")
    if op.get("duplex"): fields.append(f"duplex={op['duplex']}")
    return f"TP {node_id}:{tid}" + (f" ({', '.join(fields)})" if fields else "")

def make_text_for_link(link):
    lid = link.get("link-id")
    op = link.get("operational:link-state") or {}
    fields = []
    if op.get("oper-status"): fields.append(f"oper={op['oper-status']}")
    if op.get("bandwidth") is not None: fields.append(f"bw={op['bandwidth']}")
    if op.get("delay-ms") is not None: fields.append(f"delay-ms={op['delay-ms']}")
    return f"Link {lid}" + (f" ({', '.join(fields)})" if fields else "")

def make_text_for_route(node_id: str, r: dict) -> str:
    vrf = r.get("vrf") or "default"
    prefix = r.get("prefix") or "?"
    nh = r.get("next-hop") or "?"
    proto = r.get("protocol")
    metric = r.get("metric")
    parts = [f"vrf={vrf}", prefix, f"-> {nh}"]
    tail = []
    if proto: tail.append(str(proto))
    if metric is not None: tail.append(f"metric={metric}")
    if tail:
        parts.append(f"({', '.join(tail)})")
    return "Route " + node_id + ": " + " ".join(parts)

def to_doc(doc_type, **fields):
    doc = {"type": doc_type, **fields}
    # common metadata
    doc.setdefault("observed_at", fields.get("observed_at") or iso_now())
    doc.setdefault("source", fields.get("source") or "cmdb")
    doc.setdefault("lang", fields.get("lang") or "ja")
    return doc

def extract_docs(data: dict):
    docs = []
    nets = (data.get("ietf-network:networks") or {}).get("network", []) or []
    for net in nets:
        network_id = net.get("network-id") or "default"
        # nodes
        for node in net.get("node", []) or []:
            node_id = node.get("node-id")
            docs.append(to_doc(
                "node",
                **{"network-id": network_id, "node-id": node_id},
                node=node,
                text=make_text_for_node(node),
            ))
            # termination-points
            for tp in node.get("ietf-network-topology:termination-point", []) or []:
                tp_id = tp.get("tp-id")
                op = tp.get("operational:tp-state") or {}
                observed = op.get("last-change")
                docs.append(to_doc(
                    "tp",
                    **{"network-id": network_id, "node-id": node_id, "tp-id": tp_id},
                    tp=tp,
                    operational={"tp-state": op} if op else None,
                    text=make_text_for_tp(node_id, tp),
                    observed_at=observed,
                ))
            # routes (optional, custom operational:routing.routes)
            routing = (node.get("operational:routing") or {}).get("routes") or []
            for r in routing:
                observed = r.get("last-change")
                docs.append(to_doc(
                    "route",
                    **{"network-id": network_id, "node-id": node_id},
                    route=r,
                    vrf=r.get("vrf") or "default",
                    prefix=r.get("prefix"),
                    next_hop=r.get("next-hop"),
                    protocol=r.get("protocol"),
                    metric=r.get("metric"),
                    text=make_text_for_route(node_id, r),
                    observed_at=observed,
                ))
        # links
        for link in net.get("ietf-network-topology:link", []) or []:
            lid = link.get("link-id")
            op = link.get("operational:link-state") or {}
            observed = op.get("last-change")
            docs.append(to_doc(
                "link",
                **{"network-id": network_id, "link-id": lid},
                link=link,
                operational={"link-state": op} if op else None,
                text=make_text_for_link(link),
                observed_at=observed,
            ))
    return docs

def main():
    repo = Path(__file__).resolve().parents[1]  # repo root
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", type=Path, default=repo / "schema" / "schema.json")
    ap.add_argument("--data", type=Path, default=repo / "data" / "sample.yaml")
    ap.add_argument("--out", type=Path, default=repo / "outputs" / "objects.jsonl")
    ap.add_argument("--validate", type=Path, default=repo / "scripts" / "validate.py")
    args = ap.parse_args()

    args.out.parent.mkdir(parents=True, exist_ok=True)

    # 1) validate
    run_validate(args.schema, args.data, args.validate)

    # 2) load yaml
    with args.data.open("r", encoding="utf-8") as f:
        y = yaml.safe_load(f)

    # 3) extract docs
    docs = extract_docs(y)

    # 4) write JSONL
    with args.out.open("w", encoding="utf-8") as f:
        for d in docs:
            trimmed = {k: v for k, v in d.items() if v is not None}
            json.dump(trimmed, f, ensure_ascii=False)
            f.write("\n")

    print(f"Wrote {len(docs)} objects -> {args.out}")

if __name__ == "__main__":
    main()

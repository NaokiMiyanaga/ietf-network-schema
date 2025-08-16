#!/usr/bin/env python3
import argparse
import json
from pathlib import Path
from datetime import datetime, timezone
import subprocess
import sys
import yaml

def run_validate(schema: Path, data: Path, validate_py: Path):
    # call validate.py as a subprocess so we reuse its ref normalization & resolver
    cmd = [sys.executable, str(validate_py), "--schema", str(schema), "--data", str(data)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout)
        print(proc.stderr, file=sys.stderr)
        raise SystemExit(proc.returncode)
    return proc.stdout.strip()

def iso_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()

def make_text_for_node(n):
    nid = n.get("node-id")
    flags = []
    l3 = n.get("ietf-l3-unicast-topology:l3-node-attributes", {})
    if l3.get("name"): flags.append(f"name={l3.get('name')}")
    return f"Node {nid}" + (f" ({', '.join(flags)})" if flags else "")

def make_text_for_tp(node_id, tp):
    tid = tp.get("tp-id")
    op = tp.get("operational:tp-state", {}) or {}
    admin = op.get("admin-status")
    oper = op.get("oper-status")
    mtu = op.get("mtu")
    duplex = op.get("duplex")
    bits = [b for b in [f"admin={admin}" if admin else None,
                        f"oper={oper}" if oper else None,
                        f"mtu={mtu}" if mtu is not None else None,
                        f"duplex={duplex}" if duplex else None] if b]
    return f"TP {node_id}:{tid}" + (f" ({', '.join(bits)})" if bits else "")

def make_text_for_link(link):
    lid = link.get("link-id")
    op = link.get("operational:link-state", {}) or {}
    oper = op.get("oper-status")
    bw = op.get("bandwidth") or op.get("bw-available-bps")
    delay = op.get("delay-ms") or op.get("latency-ms")
    bits = [b for b in [f"oper={oper}" if oper else None,
                        f"bw={bw}" if bw is not None else None,
                        f"delay-ms={delay}" if delay is not None else None] if b]
    return f"Link {lid}" + (f" ({', '.join(bits)})" if bits else "")

def to_obj(obj_type, **fields):
    doc = {"type": obj_type, **fields}
    # common metadata defaults
    doc.setdefault("observed_at", fields.get("observed_at") or iso_now())
    doc.setdefault("source", fields.get("source") or "cmdb")
    doc.setdefault("lang", fields.get("lang") or "ja")
    return doc

def extract_objects(data: dict):
    out = []
    networks = data.get("ietf-network:networks", {}).get("network", [])
    for net in networks:
        network_id = net.get("network-id") or net.get("ietf-network:network-id") or "default"
        # nodes
        for node in net.get("node", []):
            node_id = node.get("node-id")
            observed = None
            # node document
            out.append(to_obj(
                "node",
                **{"network-id": network_id, "node-id": node_id},
                node=node,
                text=make_text_for_node(node),
                observed_at=observed
            ))
            # tps
            for tp in node.get("ietf-network-topology:termination-point", []):
                tp_id = tp.get("tp-id")
                op = (tp.get("operational:tp-state") or {})
                observed = op.get("last-change")
                out.append(to_obj(
                    "tp",
                    **{"network-id": network_id, "node-id": node_id, "tp-id": tp_id},
                    tp=tp,
                    operational={"tp-state": op} if op else None,
                    text=make_text_for_tp(node_id, tp),
                    observed_at=observed
                ))
        # links
        for link in net.get("ietf-network-topology:link", []):
            lid = link.get("link-id")
            op = (link.get("operational:link-state") or {})
            observed = op.get("last-change")
            out.append(to_obj(
                "link",
                **{"network-id": network_id, "link-id": lid},
                link=link,
                operational={"link-state": op} if op else None,
                text=make_text_for_link(link),
                observed_at=observed
            ))
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--schema", type=Path, required=True)
    ap.add_argument("--data", type=Path, required=True)
    ap.add_argument("--out", type=Path, default=Path("objects.jsonl"))
    ap.add_argument("--validate", type=Path, default=Path("validate.py"))
    args = ap.parse_args()

    # 1) validate
    msg = run_validate(args.schema, args.data, args.validate)
    print(msg)

    # 2) load yaml
    with args.data.open("r", encoding="utf-8") as f:
        y = yaml.safe_load(f)

    # 3) extract documents
    objs = extract_objects(y)

    # 4) write JSONL
    with args.out.open("w", encoding="utf-8") as f:
        for o in objs:
            # drop None fields to keep JSON small
            compact = {k: v for k, v in o.items() if v is not None}
            json.dump(compact, f, ensure_ascii=False)
            f.write("\n")

    print(f"Wrote {len(objs)} objects -> {args.out}")

if __name__ == "__main__":
    main()

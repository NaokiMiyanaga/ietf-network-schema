# -*- coding: utf-8 -*-
"""
CMDB updater entrypoint (kept inside ietf-network-schema as requested)

This module shells out to mcp-ansible-wrapper/scripts/mcp_ingest_state.sh
so we don't duplicate any ingestion logic. It only prepares environment
variables and returns a structured result.

Usage from Python:
    from cmdb_update import cmdb_update
    res = cmdb_update()
    print(res["status"], res["summary"])

Environment variables respected (same as shell script):
    DB              : path to SQLite DB (default: <repo>/rag.db)
    SCHEMA_SQL      : path to schema SQL (default: <repo>/cmdb_schema.sql)
    MCP_BASE        : MCP base URL (required)
    MCP_TOKEN       : MCP auth token (required)
    PLAYBOOK_BGP    : playbook name for BGP (default: show_bgp)
    PLAYBOOK_OSPF   : playbook name for OSPF (default: show_ospf)
    VERBOSE         : 0/1/2 (default: 1)
    WRAPPER_DIR     : path to mcp-ansible-wrapper (optional)
                      If not set, we try ../mcp-ansible-wrapper relative to this file.
"""

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import Dict, Any


def _detect_wrapper_script() -> Path:
    """Locate mcp_ingest_state.sh from either WRAPPER_DIR env or a sensible default."""
    # 1) explicit env
    wrapper_dir = os.environ.get("WRAPPER_DIR")
    if wrapper_dir:
        cand = Path(wrapper_dir).expanduser().resolve() / "scripts" / "mcp_ingest_state.sh"
        if cand.exists():
            return cand

    # 2) default: ../mcp-ansible-wrapper relative to this file
    here = Path(__file__).resolve().parent
    cand = (here.parent / "mcp-ansible-wrapper" / "scripts" / "mcp_ingest_state.sh").resolve()
    if cand.exists():
        return cand

    # 3) fallback: scripts/ under current working directory
    cand = Path.cwd() / "scripts" / "mcp_ingest_state.sh"
    if cand.exists():
        return cand

    raise FileNotFoundError(
        "mcp_ingest_state.sh not found. Set WRAPPER_DIR env to your mcp-ansible-wrapper path."
    )


def cmdb_update(extra_env: Dict[str, str] | None = None) -> Dict[str, Any]:
    """
    Invoke mcp_ingest_state.sh and return structured result.

    Returns:
        {
          "status": "ok" | "error",
          "summary": str,
          "stdout": str,
          "stderr": str,
          "script": "/abs/path/to/mcp_ingest_state.sh",
          "env": { "DB": "...", "SCHEMA_SQL": "...", "MCP_BASE": "...", ... }
        }
    """
    repo_root = Path(__file__).resolve().parent
    db_default = (repo_root / "rag.db").as_posix()
    schema_default = (repo_root / "cmdb_schema.sql").as_posix()

    env = os.environ.copy()
    env.setdefault("DB", db_default)
    env.setdefault("SCHEMA_SQL", schema_default)
    env.setdefault("PLAYBOOK_BGP", "show_bgp")
    env.setdefault("PLAYBOOK_OSPF", "show_ospf")
    env.setdefault("VERBOSE", "1")
    # MCP settings must be provided by caller's environment
    mcp_base = env.get("MCP_BASE")
    mcp_token = env.get("MCP_TOKEN")

    if extra_env:
        env.update(extra_env)
        # re-read after overrides
        mcp_base = env.get("MCP_BASE") or mcp_base
        mcp_token = env.get("MCP_TOKEN") or mcp_token

    missing = []
    if not mcp_base:
        missing.append("MCP_BASE")
    if not mcp_token:
        missing.append("MCP_TOKEN")
    if missing:
        return {
            "status": "error",
            "summary": f"Missing required environment variables: {', '.join(missing)}",
            "stdout": "",
            "stderr": "",
            "script": "",
            "env": {k: env.get(k, "") for k in ("DB", "SCHEMA_SQL", "MCP_BASE", "PLAYBOOK_BGP", "PLAYBOOK_OSPF", "VERBOSE")}
        }

    try:
        script = _detect_wrapper_script()
    except FileNotFoundError as e:
        return {
            "status": "error",
            "summary": str(e),
            "stdout": "",
            "stderr": "",
            "script": "",
            "env": {k: env.get(k, "") for k in ("DB", "SCHEMA_SQL", "MCP_BASE", "PLAYBOOK_BGP", "PLAYBOOK_OSPF", "VERBOSE", "WRAPPER_DIR")}
        }

    # Ensure executable via bash
    cmd = ["bash", str(script)]

    res = subprocess.run(cmd, env=env, capture_output=True, text=True)
    status = "ok" if res.returncode == 0 else "error"

    summary = "[cmdb_update] mcp_ingest_state.sh completed" if status == "ok" \
        else f"[cmdb_update] mcp_ingest_state.sh failed (rc={res.returncode})"

    return {
        "status": status,
        "summary": summary,
        "stdout": res.stdout,
        "stderr": res.stderr,
        "script": str(script),
        "env": {
            "DB": env.get("DB", ""),
            "SCHEMA_SQL": env.get("SCHEMA_SQL", ""),
            "MCP_BASE": env.get("MCP_BASE", ""),
            "PLAYBOOK_BGP": env.get("PLAYBOOK_BGP", ""),
            "PLAYBOOK_OSPF": env.get("PLAYBOOK_OSPF", ""),
            "VERBOSE": env.get("VERBOSE", ""),
            "WRAPPER_DIR": env.get("WRAPPER_DIR", ""),
        },
    }


if __name__ == "__main__":
    # Allow quick manual testing: `python cmdb_update.py`
    result = cmdb_update()
    print(result["summary"])
    sys.stdout.write(result["stdout"])
    sys.stderr.write(result["stderr"])
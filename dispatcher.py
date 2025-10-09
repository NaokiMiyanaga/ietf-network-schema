# 既存 import 群の下に追加
from pathlib import Path
import subprocess, os, sys

def run_cmdb_update():
    repo_root = Path(__file__).resolve().parent
    script_path = repo_root / "scripts" / "mcp_ingest_state.sh"
    env = os.environ.copy()
    env.setdefault("VERBOSE", "1")
    print(f"[dispatcher] running {script_path}")
    res = subprocess.run(["bash", str(script_path)], env=env, capture_output=True, text=True)
    if res.returncode == 0:
        print(f"[cmdb] update ok")
        return {"status": "ok", "stdout": res.stdout}
    else:
        print(f"[cmdb] update failed", file=sys.stderr)
        return {"status": "error", "stderr": res.stderr}

# dispatcher 内のルート分岐に追加
if text.strip() == "/mcp cmdb update":
    return run_cmdb_update()
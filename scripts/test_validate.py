import subprocess, sys
from pathlib import Path

def test_sample_validates():
    repo_root = Path(__file__).resolve().parents[1]
    validate = repo_root / "ietf-network-schema/scripts/validate.py"
    schema = repo_root / "ietf-network-schema/schema/schema.json"
    data = repo_root / "ietf-network-schema/data/sample.yaml"
    cmd = [sys.executable, str(validate), "--schema", str(schema), "--data", str(data)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"

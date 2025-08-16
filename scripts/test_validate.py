import subprocess, sys
from pathlib import Path

def test_sample_validates():
    root = Path(__file__).resolve().parents[1]
    cmd = [
        sys.executable,
        str(root / "scripts" / "validate.py"),
        "--schema", str(root / "schema" / "schema.json"),
        "--data", str(root / "data" / "sample.yaml"),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"

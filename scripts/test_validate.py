import subprocess
import sys
from pathlib import Path

def test_sample_validates():
    base = Path(__file__).resolve().parent
    cmd = [sys.executable, str(base / "validate.py"), "--schema", str(base / "schema.json"), "--data", str(base / "sample.yaml")]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}"

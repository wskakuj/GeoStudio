"""Local OCR annotations are assigned to the correct raster fields."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_raster_a1_assignment_and_leaders():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for the browser worker regressions")
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs"))],
        capture_output=True, text=True, timeout=90,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "15 raster A1 assignment regressions passed" in result.stdout

"""Colored callout circles, digits and leaders must not become polygon borders."""
from pathlib import Path
import shutil
import subprocess

import pytest


def test_colored_annotations_do_not_split_raster_fields():
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for raster tracing behavior tests")
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs"))],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr

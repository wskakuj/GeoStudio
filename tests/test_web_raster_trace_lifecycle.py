"""Behavioral regressions for raster analysis workers and their UI lifetime."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("scenario", [
    "close_during_prepare",
    "worker_replaced_after_save",
    "latest_analysis_only",
    "current_error_and_closed_callbacks",
    "quality_prepare_race",
    "quality_preserves_native_geometry_and_completed_snap",
    "analysis_change_cancels_drag_and_fit",
])
def test_raster_trace_worker_lifecycle(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for raster tracing behavior tests")
    script = Path(__file__).with_suffix(".cjs")
    result = subprocess.run(
        [node, str(script), scenario], capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr

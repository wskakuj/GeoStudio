"""GetCapabilities UI requests must terminate and publish only the current source."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
SCRIPT = Path(__file__).with_suffix(".cjs")


@pytest.mark.skipif(NODE is None, reason="Node.js is needed for WMS layers behavior tests")
@pytest.mark.parametrize("scenario", [
    "layers_timeout_and_retry",
    "layers_latest_custom_url_wins",
    "layers_same_source_second_attempt_wins",
    "layers_changed_url_without_retry_is_idle",
    "layers_filter_clears_selection_and_cancels_request",
])
def test_wms_layers_lifecycle(scenario):
    result = subprocess.run(
        [NODE, str(SCRIPT), scenario], capture_output=True,
        text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr

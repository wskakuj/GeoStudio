"""Run the actual WMS client functions with controlled fetches and timers."""
from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


NODE = shutil.which("node")
SCRIPT = Path(__file__).with_suffix(".cjs")


@pytest.mark.skipif(NODE is None, reason="Node.js is needed for WMS client behavior tests")
@pytest.mark.parametrize("scenario", [
    "cached_small_pan",
    "zoom_requests_sharper_image",
    "pending_small_pans_share_download",
    "aborted_batch_cannot_finish_new_status",
    "late_decode_cannot_replace_current_image",
    "return_to_cached_view_cancels_unneeded_request",
    "return_to_cached_view_clears_obsolete_error",
    "manual_retry_bypasses_cooldown",
    "remove_cancels_request",
    "remove_keeps_other_layer_refresh",
    "visible_layers_load_independently",
    "same_view_does_not_restart_debounce",
    "unchanged_resize_does_not_schedule_fetch",
    "same_view_after_error_does_not_retry",
    "client_timeout_finishes_loading_without_retry",
    "client_timeout_during_decode_allows_manual_retry",
    "show_after_timeout_bypasses_cooldown",
])
def test_wms_request_lifecycle(scenario):
    result = subprocess.run(
        [NODE, str(SCRIPT), scenario], capture_output=True,
        text=True, timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr

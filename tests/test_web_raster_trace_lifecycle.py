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
    "parcel_snap_uses_hidden_native_geometry_and_saves_preview",
    "parcel_controls_refit_without_reanalysis_or_losing_a1",
    "parcel_manual_correction_survives_settings_and_save",
    "parcel_snap_handles_merged_fragments_and_retains_manual_corner",
    "parcel_shared_boundary_veto_is_consistent_for_neighbors_and_union",
    "parcel_inserted_reference_node_edit_survives_merging",
    "parcel_snap_preserves_calibrated_coordinates_across_quality_and_zoom",
    "parcel_option_change_invalidates_pending_fit_and_queued_save",
    "parcel_reference_fetch_paginates_full_native_extent",
    "parcel_reference_fetch_rejects_incomplete_pagination",
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

"""Behavioral regressions for raster analysis workers and their UI lifetime."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("scenario", [
    "asynchronous_a1_fills_current_field_and_never_overwrites_manual_input",
    "cached_a1_is_available_on_first_click_and_late_closed_result_is_ignored",
    "unavailable_a1_keeps_manual_drawing_usable",
    "a1_api_uses_document_tokens_and_only_restores_an_explicit_cache_miss",
    "neighbour_fitted_manual_corner_and_node_survive_merging",
    "neighbour_bridge_origins_do_not_replace_manual_corners_on_next_union",
    "rejected_hidden_vertices_cannot_be_dragged_back_into_a_proposal",
    "first_useful_stroke_measurement_initializes_the_range",
    "forest_reference_classes_do_not_occupy_the_trace_mask",
    "first_click_fills_a1_and_preserves_manual_corrections",
    "uncertain_or_conflicting_a1_is_not_guessed",
    "stroke_width_sets_initial_range_once_and_respects_manual_override",
    "occupied_click_is_blocked_using_hidden_full_geometry",
    "failed_automatic_fit_hides_proposal_and_prevents_save",
    "neighbour_fit_saves_exact_preview_and_manual_edit_is_not_resnapped",
    "magnet_uses_native_vertices_and_prioritizes_nodes",
    "close_during_prepare",
    "worker_replaced_after_save",
    "latest_analysis_only",
    "current_error_and_closed_callbacks",
    "quality_prepare_race",
    "quality_preserves_native_geometry_and_completed_snap",
    "analysis_change_cancels_drag_and_fit",
    "parcel_snap_uses_hidden_native_geometry_and_saves_preview",
    "parcel_controls_refit_without_reanalysis_or_losing_a1",
    "parcel_range_controls_keep_close_shared_borders",
    "parcel_precision_preserves_close_fits_at_a_raster_junction",
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

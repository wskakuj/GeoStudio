"""Run the actual browser geometry helper on synthetic parcel networks."""
from pathlib import Path
import shutil
import subprocess

import pytest


CASES = [
    "translated_sides_use_exact_parcel_corners",
    "increasing_search_distance_keeps_clear_nearby_partition_fits",
    "wide_search_keeps_nearest_track_without_hiding_real_ambiguity",
    "dense_reference_corridor_is_bounded_and_reports_complexity",
    "large_search_preserves_real_pixel_pipeline_for_adjacent_thick_strokes",
    "native_5216_only_and_duplicate_edges",
    "contiguous_parcel_edges_keep_real_intermediate_nodes",
    "gently_bent_reference_is_followed_without_shortcuts",
    "parallel_ambiguity_is_left_for_review",
    "crossings_distant_sides_and_short_contact_do_not_snap",
    "shared_t_junction_and_internal_divider_are_preserved",
    "supported_shared_projection_recovers_a_neighbours_raster_bevel",
    "propagated_shared_projections_respect_manual_locks",
    "conflicting_supported_shared_projections_remain_unresolved",
    "a_fit_cannot_reverse_a_short_unreferenced_connector",
    "order_direction_and_repeated_calls_are_deterministic",
    "manual_locks_are_kept_and_report_original_corner_indices",
    "area_limit_and_narrow_notch_prevent_invalid_snaps",
    "million_metre_coordinates_keep_subpixel_precision",
    "shared_area_veto_is_local_and_keeps_neighbours_together",
    "shared_path_veto_catches_bulges_with_unchanged_endpoints",
    "shared_iteration_limit_freezes_only_shared_geometry",
    "shared_points_have_identical_numbers_after_epsilon_normalization",
    "shallow_native_corners_do_not_trigger_false_shared_veto",
    "supported_shared_anchors_can_move_a_short_interior_field",
    "thick_stroke_bevels_follow_the_real_parcel_corners",
    "a_bevel_already_touching_both_sides_keeps_distinct_source_vertices",
    "short_collinear_junction_edges_use_whole_side_evidence",
    "short_slanted_connector_uses_one_supported_straight_track",
    "bevel_recovery_requires_a_short_supported_native_join",
    "a_fully_supported_narrow_field_can_recover_its_stroke_width",
    "native_corners_use_the_diagonal_of_two_supported_distance_bands",
    "real_pixel_strokes_overlapping_5216_snap_to_its_complete_perimeter",
    "stroke_measurement_rejects_solid_patches_masks_and_isolated_annotations",
    "parcel_index_handles_3555_edges_without_global_quadratic_search",
]


@pytest.mark.parametrize("scenario", CASES)
def test_raster_parcel_snap(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for browser geometry tests")
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        [node, str(root / "tests/test_web_raster_parcel_snap.cjs"), scenario],
        check=True, cwd=root, capture_output=True, text=True, timeout=20,
    )

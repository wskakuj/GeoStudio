"""Whole-map tracing UI, asynchronous review, and guarded save integration."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("scenario", [
    "one_click_prepares_all_fields_and_uses_the_batch_callback",
    "reliable_competing_uncertain_number_requires_review",
    "unreliable_competing_assignment_does_not_replace_a_confirmed_number",
    "matching_uncertain_number_does_not_erase_independent_confirmation",
    "two_different_confirmed_numbers_require_explicit_conflict_resolution",
    "variant_choices_are_bounded_numeric_values_without_automatic_assignment",
    "explicit_batch_variant_resolves_missing_a1_and_is_retained_after_refit",
    "rejected_batch_geometry_blocks_variant_selection",
    "several_numbers_in_one_field_warn_about_the_missing_boundary",
    "full_image_budget_preserves_original_calibrated_coordinates",
    "batch_waits_for_ocr_and_assigns_late_labels_to_the_current_analysis",
    "uncertain_a1_is_prefilled_but_requires_explicit_selection",
    "confirmed_tentative_a1_survives_refits_and_changed_ocr_retry",
    "failed_ocr_keeps_batch_editable_and_retry_preserves_manual_a1",
    "manual_a1_and_explicit_unchecking_survive_snap_refitting",
    "global_parcel_fit_keeps_the_same_shared_path_for_both_batch_neighbours",
    "parcel_worker_yields_before_backend_and_caches_only_current_results",
    "cancel_or_close_terminates_pending_parcel_work_and_ignores_late_callbacks",
    "changed_settings_quality_or_analysis_replaces_parcel_jobs_without_cache_poisoning",
    "parcel_worker_failure_never_silently_uses_unfitted_geometry",
    "source_mesh_work_guard_includes_unselected_shapes_before_creating_a_worker",
    "rejected_and_missing_a1_cannot_enter_the_saved_selection",
    "a_batch_save_submits_exact_fitted_points_once_and_disables_mutation",
    "cancelling_a_pending_fit_aborts_it_and_ignores_its_late_result",
    "cancelling_or_closing_while_ocr_waits_never_starts_a_late_batch",
    "reanalysis_ignores_old_fit_and_old_worker_deliveries",
    "failed_refit_removes_old_rows_and_all_hidden_selected_geometry",
    "missing_backend_item_is_a_visible_error_and_cannot_save_partial_results",
    "occupied_regions_and_the_parcel_footprint_filter_are_applied_to_the_whole_batch",
    "actual_map_fit_callback_sends_document_revision_snap_and_abort_signal",
    "actual_map_late_fit_response_is_rejected_after_a_document_change",
    "actual_map_save_uses_one_exact_preview_and_one_atomic_apply",
    "actual_map_save_rejects_changed_coordinates_and_unready_preview_without_apply",
    "actual_map_save_rechecks_context_after_asynchronous_preview",
    "actual_map_late_apply_cannot_replace_the_state_of_another_document",
    "actual_map_preview_must_preserve_the_approved_a1_numbers",
])
def test_raster_trace_batch_lifecycle(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for raster tracing behavior tests")
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs")), scenario],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr

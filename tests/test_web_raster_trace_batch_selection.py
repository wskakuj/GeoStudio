"""Whole-map proposal selection against native parcel rings and holes."""
from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.parametrize("scenario", [
    "enclosed_parcel_is_retained_without_a_field_vertex_or_seed_inside",
    "crossing_strips_are_retained_when_neither_ring_has_an_inside_vertex",
    "a_field_wholly_inside_a_native_hole_is_outside_the_footprint",
    "a_field_crossing_the_hole_boundary_or_a_separate_part_is_retained",
    "native_geometry_and_calibrated_world_coordinates_drive_intersection",
    "boundary_contacts_are_kept_but_disjoint_geometry_is_filtered",
    "reliably_located_unread_or_conflicting_callouts_keep_white_fields_for_review",
    "unassigned_unread_callouts_do_not_invent_white_field_proposals",
])
def test_batch_footprint_intersection(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for raster tracing behavior tests")
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs")), scenario],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stdout + result.stderr

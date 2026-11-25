"""Behavioral bounds, shared topology and straight-line fits of raster tracing."""
from pathlib import Path
import shutil
import subprocess

import pytest


CASES = [
    "occupied_5310_mask_never_becomes_a_proposal",
    "waves_become_supported_straight_sides",
    "genuine_bend_and_concavity_are_retained",
    "fixed_junction_survives_quad_like_outline",
    "canonical_direction_and_ring_start",
    "shared_edges_are_identical_and_topology_has_no_slivers",
    "narrow_fields_and_zero_tolerance_do_not_collapse",
    "red_divider_is_preserved_and_merged_selection_uses_chosen_tolerance",
]


@pytest.mark.parametrize("case", CASES)
def test_raster_trace_geometry(case):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed for raster geometry tests")
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [node, str(root / "tests/test_web_raster_trace_geometry.cjs"), case],
        cwd=root, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

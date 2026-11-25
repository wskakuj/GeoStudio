"""Real dedicated parcel-fitting worker import, topology and work limits."""
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app


def test_dedicated_parcel_worker_and_its_import_are_served():
    with TestClient(create_app()) as client:
        worker = client.get("/raster_parcel_worker.js")
        helper = client.get("/raster_parcel_snap.js")
        assert worker.status_code == helper.status_code == 200
        assert 'importScripts("/raster_parcel_snap.js")' in worker.text
        assert "snapRings" in worker.text and "GeoStudioRasterParcelSnap" in helper.text
        assert "javascript" in worker.headers["content-type"]


@pytest.mark.parametrize("scenario", [
    "actual_import_preserves_global_shared_boundary_veto",
    "native_5216_paths_and_diagnostics_survive_worker_messages",
    "import_or_calculation_failure_returns_retry_error_without_geometry",
    "complete_source_mesh_limit_is_checked_before_running_the_fitter",
    "the_source_mesh_may_include_more_than_one_thousand_unselected_neighbours",
    "malformed_messages_do_not_reach_the_fitting_algorithm",
])
def test_real_parcel_worker(scenario):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the parcel worker integration test")
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs")), scenario],
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr

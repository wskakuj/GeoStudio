"""Worker imports must be served, bundled and optional failures contained."""
from pathlib import Path
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

from geostudio.web_app.server import create_app


def test_worker_and_local_ocr_assignment_helpers_are_served():
    with TestClient(create_app()) as client:
        page = client.get("/").text
        assert page.index('src="/raster_a1.js"') < page.index('src="/raster_trace.js"')
        for name, marker in (
            ("raster_trace_metrics.js", "GeoStudioRasterTraceMetrics"),
            ("raster_a1.js", "GeoStudioRasterA1"),
        ):
            response = client.get("/" + name)
            assert response.status_code == 200
            assert marker in response.text
            assert "javascript" in response.headers["content-type"]
            assert "MODEL=null" not in response.text


@pytest.mark.parametrize("failure", ["", "missing", "failed"])
def test_real_worker_runs_local_helpers_and_survives_measurement_failure(failure):
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is required for the worker integration test")
    result = subprocess.run(
        [node, str(Path(__file__).with_suffix(".cjs")), failure],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr

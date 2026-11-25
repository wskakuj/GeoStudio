"""Exercise real raster decoders and the worker on generated map fragments.

The fixtures contain no uploaded scans or map data.  The same asymmetric
closed field is encoded in each supported image format before tracing, so a
codec, channel-order or preview-coordinate regression cannot hide behind a
test that supplies already-decoded pixels directly to the worker.
"""
from __future__ import annotations

import base64
from io import BytesIO
import json
from math import hypot
from pathlib import Path
import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw, TiffImagePlugin

from geostudio.web_app import underlay_raster


TRACE = (Path(__file__).resolve().parents[1]
         / "geostudio/web_app/static/raster_trace.js")
SIZE = (320, 256)
CORNERS = ((44, 36), (264, 59), (241, 221), (30, 186))
AFFINE = (0.0, -1.75, 5850012.25, 1.25, 0.0, 7519986.25)


def _encoded_field(format_name: str, *, scale: int = 1) -> bytes:
    image = Image.new("RGB", tuple(value * scale for value in SIZE), "white")
    corners = [(x * scale, y * scale) for x, y in CORNERS]
    draw = ImageDraw.Draw(image)
    draw.polygon(corners, fill=(200, 222, 165))
    draw.line(corners + [corners[0]], fill=(28, 28, 28),
              width=5 * scale, joint="curve")
    options = {}
    if format_name == "JPEG":
        # Lossy colour subsampling must not open a boundary or create fields.
        options = {"quality": 82, "subsampling": 2}
    elif format_name == "GeoTIFF":
        tags = TiffImagePlugin.ImageFileDirectory_v2()
        tags[33550] = (1.25, 1.75, 0.0)
        # A nonzero source-pixel tie point catches origin/axis mistakes.
        tags[33922] = (11.0, 7.0, 0.0, 7520000.0, 5850000.0, 0.0)
        tags[34735] = (1, 1, 0, 1, 3072, 0, 1, 2178)
        options = {"tiffinfo": tags}
        format_name = "TIFF"
    output = BytesIO()
    image.save(output, format=format_name, **options)
    return output.getvalue()


def _trace(preview: bytes) -> list[dict]:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node.js is needed to exercise the raster tracing worker")
    with Image.open(BytesIO(preview)) as decoded:
        pixels = decoded.convert("RGBA")
        request = {"width": pixels.width, "height": pixels.height,
                   "pixels": base64.b64encode(pixels.tobytes()).decode("ascii")}
    script = r"""
const fs = require('node:fs');
const request = JSON.parse(fs.readFileSync(0, 'utf8'));
const source = fs.readFileSync(process.argv[1], 'utf8');
const traceLandUses = new Function(source + '; return traceLandUses;')();
const pixels = new Uint8ClampedArray(Buffer.from(request.pixels, 'base64'));
const mask = new Uint8ClampedArray(pixels.length);
const result = traceLandUses(pixels, mask, request.width, request.height, 5);
process.stdout.write(JSON.stringify(Array.from(result.shapes.values())));
"""
    result = subprocess.run(
        [node, "-e", script, str(TRACE)], input=json.dumps(request),
        capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(result.stdout)


def _corner_error(actual, expected) -> float:
    """Compare corners without depending on winding or the starting vertex."""
    return max(
        max(min(hypot(x - u, y - v) for u, v in expected) for x, y in actual),
        max(min(hypot(x - u, y - v) for u, v in actual) for x, y in expected))


def _area(points) -> float:
    return abs(sum(x * points[(i + 1) % len(points)][1]
                   - y * points[(i + 1) % len(points)][0]
                   for i, (x, y) in enumerate(points))) / 2


@pytest.fixture(scope="module")
def png_outline():
    preview, _ = underlay_raster.prepare_raster(_encoded_field("PNG"))
    shapes = _trace(preview)
    assert len(shapes) == 1
    return shapes[0]["points"]


@pytest.mark.parametrize("format_name", ["PNG", "JPEG", "TIFF", "GeoTIFF"])
def test_raster_formats_preserve_the_same_closed_field(format_name, png_outline):
    preview, metadata = underlay_raster.prepare_raster(_encoded_field(format_name))
    assert preview.startswith(b"\x89PNG\r\n\x1a\n")
    assert (metadata["width"], metadata["height"]) == SIZE
    assert (metadata["sourceWidth"], metadata["sourceHeight"]) == SIZE
    if format_name == "GeoTIFF":
        assert metadata["epsg"] == 2178
        assert metadata["coefficients"] == pytest.approx(AFFINE)
    else:
        assert metadata["epsg"] is None
        assert metadata["coefficients"] is None

    shapes = _trace(preview)
    assert len(shapes) == 1, "Decoding must not leak or split the closed field"
    outline = shapes[0]["points"]
    assert shapes[0]["suggested"] is True
    assert len(outline) == 4, "A straight quadrilateral needs four corners"
    # The drawn stroke is five pixels wide; the recovered centre line should
    # remain within that stroke rather than reproduce a blocky codec edge.
    assert _corner_error(outline, CORNERS) < 4.5
    assert _area(outline) == pytest.approx(_area(CORNERS), rel=0.05)
    assert _corner_error(outline, png_outline) <= 2


def test_downsampled_geotiff_trace_keeps_source_pixel_georeferencing(monkeypatch):
    content = _encoded_field("GeoTIFF", scale=2)
    _, full_metadata = underlay_raster.prepare_raster(content)
    monkeypatch.setattr(underlay_raster, "MAX_RASTER_PIXELS", SIZE[0] * SIZE[1])
    preview, metadata = underlay_raster.prepare_raster(content)

    assert (metadata["width"], metadata["height"]) == SIZE
    assert (metadata["sourceWidth"], metadata["sourceHeight"]) == (640, 512)
    assert metadata["coefficients"] == full_metadata["coefficients"]
    assert metadata["coefficients"] == pytest.approx(AFFINE)
    assert metadata["epsg"] == full_metadata["epsg"] == 2178
    shapes = _trace(preview)
    assert len(shapes) == 1
    outline = shapes[0]["points"]
    assert len(outline) == 4
    assert _corner_error(outline, CORNERS) < 4.5

    # Apply the source-to-preview ratio used by the calibrated canvas.  A
    # decoder that accidentally rescales the affine would move this polygon
    # hundreds of metres despite an apparently correct preview.
    sx = metadata["sourceWidth"] / metadata["width"]
    sy = metadata["sourceHeight"] / metadata["height"]
    a, b, c, d, e, f = metadata["coefficients"]
    actual_world = [(a * x * sx + b * y * sy + c,
                     d * x * sx + e * y * sy + f) for x, y in outline]
    expected_world = [(5850012.25 - 1.75 * 2 * y,
                       7519986.25 + 1.25 * 2 * x) for x, y in CORNERS]
    assert _corner_error(actual_world, expected_world) < 9

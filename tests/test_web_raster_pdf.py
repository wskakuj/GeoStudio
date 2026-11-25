"""PDF sheets use the same bounded raster and trace pipeline as image files."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from math import ceil
import sys

from fastapi.testclient import TestClient
from PIL import Image
import pypdfium2 as pdfium
import pytest
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.pdfgen.canvas import Canvas

from conftest import MapBuilder
from geostudio.web_app import underlay_raster
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app
from test_web_raster_trace_formats import _area, _corner_error, _trace


PDF_CORNERS = ((40, 35), (260, 58), (235, 215), (28, 180))


def _pdf_sheet(*, pages=1, password=None, page_size=(72, 60)) -> bytes:
    """A known polygon in a 300 by 250 source-pixel grid at 300 dpi."""
    output = BytesIO()
    encryption = (StandardEncryption(password, ownerPassword="test-owner")
                  if password else None)
    canvas = Canvas(output, pagesize=page_size, encrypt=encryption)
    for _ in range(pages):
        path = canvas.beginPath()
        for index, (x, y) in enumerate(PDF_CORNERS):
            point = (x * 72 / 300, page_size[1] - y * 72 / 300)
            if index:
                path.lineTo(*point)
            else:
                path.moveTo(*point)
        path.close()
        canvas.setFillColorRGB(200 / 255, 222 / 255, 165 / 255)
        canvas.setStrokeColorRGB(28 / 255, 28 / 255, 28 / 255)
        canvas.setLineWidth(5 * 72 / 300)
        canvas.setLineJoin(1)
        canvas.drawPath(path, fill=1, stroke=1)
        canvas.showPage()
    canvas.save()
    return output.getvalue()


def test_pdf_sheet_decodes_and_traces_the_same_straight_field():
    preview, metadata = underlay_raster.prepare_raster(_pdf_sheet())
    assert preview.startswith(b"\x89PNG\r\n\x1a\n")
    assert (metadata["width"], metadata["height"]) == (300, 250)
    assert (metadata["sourceWidth"], metadata["sourceHeight"]) == (300, 250)
    assert metadata["coefficients"] is None
    assert metadata["epsg"] is None
    with Image.open(BytesIO(preview)) as image:
        assert image.mode == "RGB"
        assert image.getpixel((2, 2)) == (255, 255, 255)
        assert image.getpixel((150, 120)) == pytest.approx((200, 222, 165), abs=1)
    shapes = _trace(preview)
    assert len(shapes) == 1
    outline = shapes[0]["points"]
    assert len(outline) == 4
    assert shapes[0]["suggested"] is True
    assert _corner_error(outline, PDF_CORNERS) < 4.5
    assert _area(outline) == pytest.approx(_area(PDF_CORNERS), rel=0.05)


@pytest.mark.parametrize("pixel_cap,edge_cap", [(18750, 8192), (14000000, 150)])
def test_pdf_preview_limits_do_not_change_300dpi_source_grid(monkeypatch,
                                                           pixel_cap, edge_cap):
    content = _pdf_sheet()
    _, full = underlay_raster.prepare_raster(content)
    monkeypatch.setattr(underlay_raster, "MAX_RASTER_PIXELS", pixel_cap)
    monkeypatch.setattr(underlay_raster, "MAX_PREVIEW_EDGE", edge_cap)
    render_scales = []
    native_render = pdfium.PdfPage.render

    def record_render(self, *args, **kwargs):
        render_scales.append(kwargs["scale"])
        return native_render(self, *args, **kwargs)

    monkeypatch.setattr(pdfium.PdfPage, "render", record_render)
    preview, reduced = underlay_raster.prepare_raster(content)
    assert (reduced["sourceWidth"], reduced["sourceHeight"]) == (
        full["sourceWidth"], full["sourceHeight"])
    assert reduced["width"] * reduced["height"] <= pixel_cap
    assert max(reduced["width"], reduced["height"]) <= edge_cap
    assert (reduced["width"], reduced["height"]) == (150, 125)
    assert len(render_scales) == 1
    assert ceil(72 * render_scales[0]) <= 150
    assert ceil(60 * render_scales[0]) <= 125
    with Image.open(BytesIO(preview)) as image:
        assert image.size == (reduced["width"], reduced["height"])
        assert image.getpixel((75, 60)) == pytest.approx((200, 222, 165), abs=1)


@pytest.mark.parametrize("kind", ["invalid", "password", "multiple_pages"])
def test_unusable_pdf_is_rejected_with_actionable_error(kind):
    if kind == "invalid":
        content = b"%PDF-1.7\nthis is not a PDF document"
        message = "uszkodzony|hasłem"
    elif kind == "password":
        content = _pdf_sheet(password="test-password")
        message = "hasłem"
    else:
        content = _pdf_sheet(pages=2)
        message = "kilka stron|osobny PDF"
    with pytest.raises(ValueError, match=message):
        underlay_raster.prepare_raster(content)


def test_pdf_is_not_accepted_by_the_tiff_only_decoder():
    with pytest.raises(ValueError):
        underlay_raster.prepare_geotiff(_pdf_sheet())


def test_pdf_file_byte_limit_is_checked_before_native_decoder(monkeypatch):
    def unexpected_decode(content):
        pytest.fail("An oversized PDF must be rejected before opening PDFium")

    monkeypatch.setattr(underlay_raster, "_prepare_pdf", unexpected_decode)
    assert underlay_raster.MAX_RASTER_BYTES == 48 * 1024 * 1024
    oversized = b"%PDF-1.7\n" + b" " * underlay_raster.MAX_RASTER_BYTES
    with pytest.raises(ValueError, match="48 MB"):
        underlay_raster.prepare_raster(oversized)


def test_oversized_pdf_page_is_rejected_before_allocating_a_bitmap(monkeypatch):
    def unexpected_render(self, *args, **kwargs):
        pytest.fail("The 80-million source-pixel limit must precede rendering")

    monkeypatch.setattr(pdfium.PdfPage, "render", unexpected_render)
    # 2160 points = 30 inches = 9000 source pixels at 300 dpi on each axis.
    assert underlay_raster.MAX_SOURCE_PIXELS == 80_000_000
    with pytest.raises(ValueError, match="80 mln"):
        underlay_raster.prepare_raster(_pdf_sheet(page_size=(2160, 2160)))


def test_raster_prepare_api_accepts_pdf_and_keeps_original_map():
    original = (MapBuilder().object("5216", "PDF-BASE", {"A2": "1"},
                [(0, 0), (0, 10), (10, 10), (10, 0)]).build())
    workspace = PreviewWorkspace()
    workspace.load_map(original, "synthetic.MAP")
    status = workspace.editing_status()
    app = create_app(workspace)
    headers = {"X-GeoStudio-Token": app.state.api_token,
               "Content-Type": "application/pdf"}
    content = _pdf_sheet()
    with TestClient(app) as client:
        response = client.post("/api/underlay/raster/prepare", content=content,
                               headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["content-type"] == "image/png"
        assert response.headers["x-raster-width"] == "300"
        assert response.headers["x-raster-height"] == "250"
        assert response.headers["x-raster-source-width"] == "300"
        assert response.headers["x-raster-source-height"] == "250"
        assert response.headers["x-raster-affine"] == "null"
        assert response.headers["x-raster-epsg"] == ""
        assert response.headers["x-raster-digest"] == sha256(content).hexdigest()
        with Image.open(BytesIO(response.content)) as image:
            assert image.size == (300, 250)
        invalid = client.post("/api/underlay/raster/prepare",
                              content=b"%PDF-broken", headers=headers)
        assert invalid.status_code == 400
        assert "hasłem" in invalid.json()["detail"]
    assert workspace.editing_status()["revision"] == status["revision"]
    assert workspace.export_copy(status["documentToken"])[1] == original


def test_packaged_selftest_fails_if_native_pdf_decoder_is_missing(monkeypatch):
    from geostudio.web_app.__main__ import _selftest

    def missing_decoder(content, **kwargs):
        assert content.startswith(b"%PDF-")
        raise ImportError("Synthetic missing PDFium native library")

    monkeypatch.setattr(underlay_raster, "prepare_raster", missing_decoder)
    streams = (sys.stdout, sys.stderr)
    assert _selftest(PreviewWorkspace()) == 1
    assert (sys.stdout, sys.stderr) == streams

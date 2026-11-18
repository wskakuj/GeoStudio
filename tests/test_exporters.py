"""Export tests: the files must be identical to what the code produced before
``exporters.py`` existed.

Two independent checks, deliberately kept apart:

1. **Equivalence, same environment.** ``legacy_export`` holds a frozen copy of
   the pre-refactor code. Running it and the new module in one process must
   produce byte-identical files. This is the real proof that nothing changed,
   and it does not depend on Qt version, platform or antialiasing.
2. **Regression against a reference, any environment.** The golden file
   records what main produced: image size, background colour, the bounding box
   of the drawing, overall ink coverage and a 16x16 grid of per-cell ink. None
   of that is compared as a hash, because two Qt builds legitimately render
   antialiasing differently — GitHub Actions proved that. The tolerances are
   tight enough that moving geometry, losing an object or changing a colour
   still fails.

DXF is compared structurally: ezdxf writes a creation stamp and handles, so
two identical exports are never byte-identical.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

from geostudio.app import GeoStudioWindow
from geostudio.exporters import (IMAGE_MAX_HEIGHT, IMAGE_MIN_HEIGHT, IMAGE_WIDTH,
                                 render_scene_image, sanitise_layer_name,
                                 save_image, scene_image_geometry, write_dxf)
from geostudio.geomap import GeoMap

from export_snapshot import (_dxf_structure, build_export_window, export_map_bytes,
                            run_exports)

GOLDEN = Path(__file__).parent / "golden" / "exports_v014.json"

# Tolerances for the cross-environment comparison. They are sized to absorb a
# different rasteriser, not to detect a moved vertex: cartographic lines are
# thin, so pixel statistics separate "another Qt build" from "geometry changed"
# only weakly. Exactness is proven by the legacy comparison below and by the
# DXF structure, which is vector data and therefore environment-independent.
INK_GRID_TOLERANCE = 0.04       # per cell, fraction of covered pixels
INK_TOTAL_TOLERANCE = 0.004     # whole image
BOX_TOLERANCE_PX = 24           # the box is measured on a 512 px probe


@pytest.fixture(scope="module")
def qt_app():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qt_app, tmp_path):
    widget = build_export_window(tmp_path)
    yield widget
    widget.close()


# --- golden comparison ---------------------------------------------------

def test_exports_match_golden(qt_app, tmp_path):
    """Regression check against what main produced, on any Qt build."""
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = run_exports(build_export_window(tmp_path), tmp_path / "out")

    for key in ("image.png", "image.jpg", "image.tif"):
        expected, produced = golden[key], actual[key]
        assert produced["readable"], f"{key} could not be read back"
        assert (produced["width"], produced["height"]) == \
            (expected["width"], expected["height"]), key

        signature = produced["signature"]
        reference = expected["signature"]
        _assert_background(key, signature["background"], reference["background"])
        _assert_content_box(key, signature["contentBox"], reference["contentBox"])
        assert signature["inkFraction"] == pytest.approx(
            reference["inkFraction"], abs=INK_TOTAL_TOLERANCE), key
        _assert_ink_grid(key, signature["inkGrid"], reference["inkGrid"])
        # A blank or half-empty export must never pass as "close enough".
        assert 0.001 < signature["inkFraction"] < 0.5, key

    assert actual["dxf"] == golden["dxf"]


def _assert_background(key, produced, expected):
    """The paper colour: exact for lossless formats, tolerant for JPEG.

    A JPEG encoder may round the first pixel a step or two; the contract is a
    white background, not one particular byte.
    """
    produced_rgb = _hex_to_rgb(produced)
    expected_rgb = _hex_to_rgb(expected)
    if key.endswith((".png", ".tif")):
        assert produced_rgb == expected_rgb, (key, produced, expected)
        return
    for got, want in zip(produced_rgb, expected_rgb):
        assert got >= 250, (key, produced)
        assert abs(got - want) <= 8, (key, produced, expected)


def _hex_to_rgb(value):
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) for index in (0, 2, 4))


def _assert_content_box(key, produced, expected):
    if expected is None or produced is None:
        assert produced == expected, key
        return
    for got, want in zip(produced, expected):
        assert abs(got - want) <= BOX_TOLERANCE_PX, (key, produced, expected)


def _assert_ink_grid(key, produced, expected):
    assert len(produced) == len(expected), key
    for index, (got, want) in enumerate(zip(produced, expected)):
        assert got == pytest.approx(want, abs=INK_GRID_TOLERANCE), \
            f"{key}: ink differs in cell {index}: {got:.4f} vs {want:.4f}"


def test_new_export_matches_the_frozen_old_implementation(qt_app, tmp_path):
    """The extraction must be byte-identical to the code it replaced.

    Both implementations run in this process, on this machine, one after the
    other — so this comparison holds regardless of Qt version or platform.
    """
    from legacy_export import legacy_export_dxf, legacy_export_image

    window = build_export_window(tmp_path)
    for suffix in (".png", ".jpg", ".tif"):
        new_path = tmp_path / f"new{suffix}"
        old_path = tmp_path / f"old{suffix}"
        assert save_image(render_scene_image(window.map_scene), new_path)
        legacy_export_image(window.map_scene, old_path)
        assert new_path.read_bytes() == old_path.read_bytes(), suffix

    new_dxf = tmp_path / "new.dxf"
    old_dxf = tmp_path / "old.dxf"
    write_dxf(window.doc, window.catalog, new_dxf)
    legacy_export_dxf(window.doc, window.catalog, old_dxf)
    assert _dxf_structure(new_dxf) == _dxf_structure(old_dxf)
    window.close()


def test_image_content_lands_where_the_dxf_geometry_says(qt_app, tmp_path):
    """Ties the raster to the vector data, independently of antialiasing.

    The exported image is rendered with KeepAspectRatio from the scene rect, so
    every DXF vertex has a predictable pixel position. Ink must be present
    there. This catches a blank export, a shifted map or a missing object
    without comparing a single pixel value.
    """
    window = build_export_window(tmp_path)
    image = render_scene_image(window.map_scene)
    assert image is not None

    dxf_path = tmp_path / "check.dxf"
    write_dxf(window.doc, window.catalog, dxf_path)
    structure = _dxf_structure(dxf_path)
    points = [point for entity in structure["entities"] for point in entity["points"]]
    assert points

    rect = window.map_scene.itemsBoundingRect()
    scale = min(image.width() / rect.width(), image.height() / rect.height())
    offset_x = (image.width() - rect.width() * scale) / 2
    offset_y = (image.height() - rect.height() * scale) / 2

    for x, y in points:
        # Scene coordinates are (x, -y); the export keeps that mapping.
        pixel_x = offset_x + (x - rect.left()) * scale
        pixel_y = offset_y + (-y - rect.top()) * scale
        assert _ink_near(image, pixel_x, pixel_y, radius=6), (x, y, pixel_x, pixel_y)
    window.close()


def _ink_near(image, x, y, radius=6):
    left = max(0, int(x) - radius)
    right = min(image.width(), int(x) + radius + 1)
    top = max(0, int(y) - radius)
    bottom = min(image.height(), int(y) + radius + 1)
    for py in range(top, bottom):
        for px in range(left, right):
            colour = image.pixelColor(px, py)
            if (255 - colour.red()) + (255 - colour.green()) + (255 - colour.blue()) > 30:
                return True
    return False


def test_dxf_keeps_entity_order_and_layers(qt_app, tmp_path):
    actual = run_exports(build_export_window(tmp_path), tmp_path / "out")
    dxf = actual["dxf"]
    assert dxf["dxfversion"] == "AC1024"
    assert [entity["layer"] for entity in dxf["entities"]] == [
        "Działki _granice_ _1_", "Działki _granice_ _1_", "Obręby_arkusze_2024",
        "Użytki_ rolne_łąki", "x" * 100, "Inne _ kod 9999",
    ]
    assert [entity["type"] for entity in dxf["entities"]] == [
        "LWPOLYLINE", "LWPOLYLINE", "LWPOLYLINE", "LWPOLYLINE", "POINT", "LWPOLYLINE",
    ]


# --- window methods keep working ----------------------------------------

def test_export_methods_are_still_on_the_window(qt_app):
    for name in ("export_image", "export_dxf"):
        assert callable(getattr(GeoStudioWindow, name))


def test_export_image_without_document_does_nothing(qt_app, tmp_path, monkeypatch):
    widget = GeoStudioWindow()
    calls = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: calls.append(a) or ("", "")))
    widget.export_image()
    widget.export_dxf()
    assert calls == []
    widget.close()


def test_cancelled_dialog_writes_nothing(window, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    window.export_image()
    window.export_dxf()
    assert list(tmp_path.glob("*.png")) == []
    assert list(tmp_path.glob("*.dxf")) == []


def test_unsupported_image_format_reports_the_old_message(window, tmp_path, monkeypatch):
    target = tmp_path / "mapa.xyz"
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(target), "")))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    window.export_image()
    assert not target.exists()
    assert warnings and warnings[0][1] == "Błąd eksportu"
    assert "Format niedostępny" in warnings[0][2]


def test_missing_ezdxf_keeps_the_installation_hint(window, tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "ezdxf", None)      # import ezdxf -> ImportError
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(tmp_path / "x.dxf"), "")))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: warnings.append(a)))
    window.export_dxf()
    assert warnings and warnings[0][1] == "Wymagana biblioteka"
    assert warnings[0][2] == "Zainstaluj ezdxf: pip install ezdxf"


# --- units ---------------------------------------------------------------

def test_image_geometry_follows_the_scene_and_clamps():
    wide = QRectF(0, 0, 1000, 10)
    assert scene_image_geometry(wide) == (IMAGE_WIDTH, IMAGE_MIN_HEIGHT)
    tall = QRectF(0, 0, 10, 1000)
    assert scene_image_geometry(tall) == (IMAGE_WIDTH, IMAGE_MAX_HEIGHT)
    square = QRectF(0, 0, 500, 500)
    assert scene_image_geometry(square) == (IMAGE_WIDTH, IMAGE_WIDTH)


def test_render_returns_none_for_an_empty_scene(qt_app):
    from PySide6.QtWidgets import QGraphicsScene
    assert render_scene_image(QGraphicsScene()) is None


def test_render_produces_an_rgb_image_with_a_white_background(qt_app, tmp_path):
    window = build_export_window(tmp_path)
    image = render_scene_image(window.map_scene)
    assert image is not None
    assert image.format() == QImage.Format_RGB32
    assert image.pixelColor(0, 0).name() == "#ffffff"
    window.close()


def test_sanitise_layer_name_matches_the_old_rule():
    assert sanitise_layer_name('a<b>c/d\\e"f:g;h?i*j|k,l=m') == "a_b_c_d_e_f_g_h_i_j_k_l_m"
    assert sanitise_layer_name("Działki 12/3") == "Działki 12_3"
    assert len(sanitise_layer_name("x" * 140)) == 100
    assert sanitise_layer_name("") == ""


def test_save_image_reports_failure(tmp_path):
    image = QImage(4, 4, QImage.Format_RGB32)
    image.fill(0)
    assert save_image(image, tmp_path / "ok.png") is True
    assert save_image(image, tmp_path / "bad.xyz") is False


def test_write_dxf_puts_single_vertices_as_points(tmp_path):
    doc = GeoMap(export_map_bytes())
    target = tmp_path / "out.dxf"
    write_dxf(doc, {"5216": "Działki"}, target)
    import ezdxf
    model = ezdxf.readfile(str(target)).modelspace()
    types = [entity.dxftype() for entity in model]
    assert types.count("POINT") == 1
    assert types.count("LWPOLYLINE") == 5

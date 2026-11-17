"""Export tests: the files must be identical to what the code produced before
``exporters.py`` existed.

PNG and JPEG bytes are deterministic on one Qt build, so the golden file keeps
a hash. The hash is compared only when the recorded Qt version and platform
still match; on another system the test falls back to a coarse signature
(size, background, content box, 16x16 colour grid) so a Windows machine or a
newer Qt does not fail for reasons unrelated to the refactor.

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

from export_snapshot import (build_export_window, export_map_bytes, run_exports)

GOLDEN = Path(__file__).parent / "golden" / "exports_v014.json"

# Tolerances used when the reference environment is not the current one.
# The content box is measured on a 512 px probe, so it carries up to ~5 px of
# quantisation on a 2600 px image; 16 px leaves room for that and still catches
# any real change of layout.
GRID_CHANNEL_TOLERANCE = 24
BOX_TOLERANCE_PX = 16


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
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    actual = run_exports(build_export_window(tmp_path), tmp_path / "out")
    same_environment = actual["environment"] == golden["environment"]

    for key in ("image.png", "image.jpg", "image.tif"):
        expected, produced = golden[key], actual[key]
        assert produced["readable"], f"{key} could not be read back"
        assert (produced["width"], produced["height"]) == \
            (expected["width"], expected["height"]), key
        signature = produced["signature"]
        assert signature["background"] == expected["signature"]["background"], key
        _assert_content_box(key, signature["contentBox"], expected["signature"]["contentBox"])
        _assert_grid(key, signature["grid"], expected["signature"]["grid"])
        if same_environment:
            assert produced["sha256"] == expected["sha256"], (
                f"{key} bytes differ from the reference on the same Qt build")

    assert actual["dxf"] == golden["dxf"]


def _assert_content_box(key, produced, expected):
    if expected is None or produced is None:
        assert produced == expected, key
        return
    for got, want in zip(produced, expected):
        assert abs(got - want) <= BOX_TOLERANCE_PX, (key, produced, expected)


def _assert_grid(key, produced, expected):
    assert len(produced) == len(expected), key
    for cell, reference in zip(produced, expected):
        for channel, want in zip(cell, reference):
            assert abs(channel - want) <= GRID_CHANNEL_TOLERANCE, (key, cell, reference)


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

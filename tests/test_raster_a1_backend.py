"""Offline A1 OCR, conservative evidence, transparency and real model packaging."""
from hashlib import sha256
from io import BytesIO
import os
from pathlib import Path
import socket
import sys
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw, ImageFont

from geostudio.web_app import raster_a1 as a1


def _png(image):
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_telemetry_is_disabled_before_engine_creation_and_models_are_local(tmp_path, monkeypatch):
    events = []
    package = tmp_path / "rapidocr"
    model_dir = package / "models"
    model_dir.mkdir(parents=True)
    hashes = {}
    for name in a1._MODELS:
        content = ("local test model " + name).encode()
        (model_dir / name).write_bytes(content)
        hashes[name] = sha256(content).hexdigest()

    def disable():
        assert os.environ["ORT_DISABLE_TELEMETRY"] == "1"
        events.append("telemetry-disabled")

    def factory(*, params):
        assert events == ["telemetry-disabled"]
        for field in ("Det.model_path", "Rec.model_path"):
            assert Path(params[field]).is_file()
            assert Path(params[field]).parent == model_dir
        assert params["EngineConfig.onnxruntime.use_cuda"] is False
        assert params["EngineConfig.onnxruntime.use_dml"] is False
        events.append("engine-created")
        return object()

    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(disable_telemetry_events=disable))
    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(__file__=str(package / "__init__.py"), RapidOCR=factory))
    monkeypatch.setattr(a1, "_MODELS", hashes)
    monkeypatch.setattr(a1, "_ENGINE", None)
    monkeypatch.delenv("ORT_DISABLE_TELEMETRY", raising=False)
    first = a1._engine()
    assert a1._engine() is first
    assert events == ["telemetry-disabled", "engine-created"]


def test_missing_model_fails_before_engine_or_download(tmp_path, monkeypatch):
    events = []
    monkeypatch.setitem(sys.modules, "onnxruntime", SimpleNamespace(disable_telemetry_events=lambda: events.append("disabled")))

    def forbidden(**_):
        pytest.fail("Missing model must not construct an engine or start a download")

    monkeypatch.setitem(sys.modules, "rapidocr", SimpleNamespace(__file__=str(tmp_path / "__init__.py"), RapidOCR=forbidden))
    monkeypatch.setattr(a1, "_ENGINE", None)
    with pytest.raises(RuntimeError, match="lokalnego modelu"):
        a1._engine()
    assert events == ["disabled"]


def test_only_numeric_callout_text_is_normalized_without_guessing_letters():
    assert a1._numeric("(178") == "178"
    assert a1._numeric(" [0004] ") == "0004"
    for value in ("1x7", "O12", "l31", "12/3", "-12", "123456", ""):
        assert a1._numeric(value) is None


def test_consensus_rejects_confident_truncated_and_conflicting_numbers():
    assert a1._consensus([("189", .93), ("18", .90), ("18", .97)])["status"] == "uncertain"
    assert a1._consensus([("133", .99), ("138", .98)])["status"] == "uncertain"
    assert a1._consensus([("133", .97), ("133", .95), ("33", .70)])["status"] == "ok"
    assert a1._consensus([("133", .99)])["status"] == "uncertain"
    review = a1._consensus([("189", .93), ("18", .90), ("18", .97)])
    assert review["reason"] == "truncated_text"
    assert review["text"] == "189"
    assert {item["text"] for item in review["alternatives"]} == {"18", "189"}
    for complete, clipped, confidence in (("208", "28", .73), ("167", "67", .56)):
        review = a1._consensus([(complete, confidence), (clipped, .96), (clipped, .95)])
        assert review["text"] == complete and review["status"] == "uncertain"
    full_word = a1._consensus([("134", .99), ("1341", .65)], prefer_complete=False)
    assert full_word["text"] == "134" and full_word["status"] == "uncertain"


def test_transparent_ink_is_composited_on_white_before_analysis(monkeypatch):
    np = pytest.importorskip("numpy")
    pytest.importorskip("cv2")
    image = Image.new("RGBA", (32, 24), (0, 0, 180, 0))
    image.putpixel((5, 6), (0, 20, 180, 255))
    masks = {}
    monkeypatch.setattr(a1, "_engine", lambda: object())

    def capture(engine, mask, color, occluder=None):
        masks[color] = mask.copy()
        return []

    monkeypatch.setattr(a1, "_analyze_mask", capture)
    result = a1.recognize_raster_a1(_png(image))
    assert (result["width"], result["height"]) == (32, 24)
    assert np.count_nonzero(masks["blue"]) == 1
    assert masks["blue"][6, 5]
    assert not np.any(masks["dark"])


def test_uncircled_number_with_outgoing_stroke_cannot_use_its_center():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((150, 240), np.uint8)
    cv2.rectangle(mask, (70, 55), (85, 75), 1, 2)
    box = [65, 50, 90, 80]
    assert not a1._has_outgoing_ink(mask, box)
    cv2.line(mask, (85, 70), (160, 115), 1, 2)
    assert a1._has_outgoing_ink(mask, box)


def test_detached_broken_leader_is_ambiguous_but_nearby_short_digit_is_not():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((150, 240), np.uint8)
    cv2.rectangle(mask, (70, 55), (85, 75), 1, 2)
    box = [65, 50, 90, 80]
    cv2.line(mask, (51, 54), (51, 74), 1, 2)
    assert not a1._has_outgoing_ink(mask, box)
    cv2.line(mask, (58, 85), (40, 103), 1, 2)
    cv2.line(mask, (36, 107), (15, 128), 1, 2)
    assert a1._has_outgoing_ink(mask, box)


def test_single_digit_crop_without_whole_text_detection_is_only_an_alternative(monkeypatch):
    np = pytest.importorskip("numpy")
    mask = np.zeros((120, 120), np.uint8)
    circle = (60., 60., 30., 30., 0., 1.)
    monkeypatch.setattr(a1, "_circles", lambda *_: (mask, 1., [circle], [circle]))
    monkeypatch.setattr(a1, "_leader_data", lambda *_: [{"hasLeader": False, "anchor": [60., 60.], "leaderEndpoints": []}])
    monkeypatch.setattr(a1, "_text_candidates", lambda *_: [])
    monkeypatch.setattr(a1, "_read_line", lambda *_: ("5", .99))
    mask[50:70, 50:70] = 1
    result = a1._analyze_mask(object(), mask, "blue")
    assert result[0]["text"] == ""
    assert result[0]["status"] == "uncertain"
    assert result[0]["reason"] == "unread_callout"
    assert result[0]["alternatives"][0]["text"] == "5"


def test_possible_circle_does_not_offer_its_center_as_a_tentative_label_anchor(monkeypatch):
    np = pytest.importorskip("numpy")
    mask = np.zeros((120, 120), np.uint8)
    mask[52:68, 55:65] = 1
    possible = (60., 60., 30., 30., 0., .7)
    monkeypatch.setattr(a1, "_circles", lambda *_: (mask, 1., [], [possible]))
    monkeypatch.setattr(a1, "_text_candidates", lambda *_: [{"text": "178", "confidence": .99, "box": [50, 50, 70, 70]}])
    monkeypatch.setattr(a1, "_read_line", lambda *_: ("178", .99))
    monkeypatch.setattr(a1, "_has_outgoing_ink", lambda *_: False)
    result = a1._analyze_mask(object(), mask, "blue")[0]
    assert result["status"] == "uncertain" and result["textStatus"] == "ok"
    assert result["associationStatus"] == "uncertain" and result["reason"] == "possible_circle"
    assert result["anchor"] is None and result["hasLeader"]


def test_unread_coloured_callout_is_retained_without_inventing_a_number(monkeypatch):
    np = pytest.importorskip("numpy")
    mask = np.zeros((120, 120), np.uint8)
    mask[52:68, 55:65] = 1
    circle = (60., 60., 30., 30., 0., .95)
    monkeypatch.setattr(a1, "_circles", lambda *_: (mask, 1., [circle], [circle]))
    monkeypatch.setattr(a1, "_leader_data", lambda *_: [{"hasLeader": False, "anchor": [60., 60.], "leaderEndpoints": []}])
    monkeypatch.setattr(a1, "_text_candidates", lambda *_: [])
    monkeypatch.setattr(a1, "_read_line", lambda *_: None)
    result = a1._analyze_mask(object(), mask, "blue")[0]
    assert result["text"] == "" and result["confidence"] == 0
    assert result["reason"] == "unread_callout" and result["circleConfidence"] == .95
    assert result["status"] == "uncertain" and result["associationStatus"] == "ok"
    assert a1._analyze_mask(object(), mask, "dark") == []


def test_leader_endpoint_survives_a_short_printed_gap_and_a_branch_is_ambiguous():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((200, 300), np.uint8)
    cv2.circle(mask, (55, 55), 25, 1, 2)
    cv2.line(mask, (55, 80), (55, 112), 1, 2)
    cv2.line(mask, (55, 118), (55, 175), 1, 2)
    circle = (55., 55., 25., 25., 0., 1.)
    printed = np.zeros_like(mask)
    printed[112:119, 50:60] = 1
    first = a1._leader_data(mask, [circle], 1., printed)[0]
    assert first["hasLeader"]
    assert first["anchor"] == pytest.approx([55, 175], abs=3)
    cv2.line(mask, (55, 140), (220, 140), 1, 2)
    second = a1._leader_data(mask, [circle], 1., printed)[0]
    assert second["hasLeader"] and len(second["leaderEndpoints"]) == 2
    assert second["anchor"] is None


def test_arrowhead_is_not_joined_to_an_unrelated_mark_across_white_paper():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((130, 220), np.uint8)
    cv2.circle(mask, (55, 55), 25, 1, 2)
    cv2.line(mask, (80, 55), (145, 55), 1, 1)
    cv2.circle(mask, (145, 55), 4, 1, 1)
    cv2.line(mask, (145, 47), (145, 20), 1, 1)
    result = a1._leader_data(mask, [(55., 55., 25., 25., 0., 1.)], 1., np.zeros_like(mask))[0]
    # The tiny arrowhead thins to its own centre. It must not claim the far
    # end of the separate upper pen stroke, across the blank-paper gap.
    assert result["hasLeader"]
    assert result["anchor"] == pytest.approx([145, 55], abs=3)


def test_detached_start_beside_circle_is_not_a_second_leader_destination():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((200, 300), np.uint8)
    cv2.circle(mask, (55, 55), 25, 1, 2)
    # Start lies outside the erased circle, beyond a short printing/scan gap.
    cv2.line(mask, (55, 87), (55, 170), 1, 2)
    circle = (55., 55., 25., 25., 0., 1.)
    result = a1._leader_data(mask, [circle], 1.)[0]
    assert result["hasLeader"] and len(result["leaderEndpoints"]) == 1
    assert result["anchor"] == pytest.approx([55, 170], abs=3)
    # A real fork retains both destination tips; no closest-end shortcut.
    cv2.line(mask, (55, 130), (160, 100), 1, 2)
    fork = a1._leader_data(mask, [circle], 1.)[0]
    assert fork["anchor"] is None
    assert len(fork["leaderEndpoints"]) >= 2


def test_printed_ink_network_cannot_spread_ocr_conflicts_to_many_fields():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    mask = np.zeros((200, 300), np.uint8)
    cv2.circle(mask, (55, 55), 25, 1, 2)
    cv2.line(mask, (55, 80), (55, 170), 1, 2)
    for y in (95, 115, 135, 155):
        cv2.line(mask, (20, y), (200, y), 1, 2)
    result = a1._leader_data(mask, [(55., 55., 25., 25., 0., 1.)], 1.)[0]
    assert result["hasLeader"]
    assert result["leaderEndpointCount"] > 4
    assert result["reason"] == "leader_network"
    assert result["anchor"] is None and result["leaderEndpoints"] == []


def test_real_bundled_models_recognize_callout_without_network(monkeypatch):
    # The process-lifetime opt-out MUST precede even importorskip/import.
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("rapidocr")

    def offline(*_args, **_kwargs):
        pytest.fail("Local OCR must not open a network connection")

    monkeypatch.setattr(socket.socket, "connect", offline)
    assert a1.selftest_raster_a1()


def test_plain_black_map_number_is_not_automatically_an_a1(monkeypatch):
    monkeypatch.setenv("ORT_DISABLE_TELEMETRY", "1")
    pytest.importorskip("onnxruntime")
    pytest.importorskip("rapidocr")
    image = Image.new("RGB", (180, 90), "white")
    ImageDraw.Draw(image).text((30, 25), "21", font=ImageFont.load_default(size=30), fill="black")
    result = a1.recognize_raster_a1(_png(image))
    assert not any(item["status"] == "ok" for item in result["annotations"])


def test_bad_or_oversized_raster_is_rejected_before_model_initialization(monkeypatch):
    monkeypatch.setattr(a1, "_engine", lambda: pytest.fail("Must reject before initialization"))
    with pytest.raises(ValueError):
        a1.recognize_raster_a1(b"")
    monkeypatch.setattr(a1, "MAX_PIXELS", 99)
    with pytest.raises(ValueError, match="14 mln"):
        a1.recognize_raster_a1(_png(Image.new("RGB", (10, 10), "white")))

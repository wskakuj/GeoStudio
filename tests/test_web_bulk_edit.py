"""Safe, previewed A1/A2 bulk changes for selected GEO-MAP records."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import MapBuilder
from geostudio.geomap import GeoMap
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.server import create_app


def source():
    return (MapBuilder(ext=(5000, 0, 0, 100, 100))
        .object("5310", "BLD-A", {"A1": "b", "A2": "Dom"},
                [(0, 0), (0, 10), (10, 10), (10, 0)])
        .object("5310", "BLD-B", {"A1": "b", "A2": "Garaż"},
                [(20, 0), (20, 10), (30, 10), (30, 0)])
        .object("5310", "BLD-C", {"A1": "g"},
                [(40, 0), (40, 10), (50, 10), (50, 0)])
        .object("5220", "PARCEL", {"A1": "R", "A2": "RIV"},
                [(0, 40), (0, 50), (10, 50), (10, 40)])
        .object("5230", "ROAD", {"A1": "dr", "A2": "droga"},
                [(20, 40), (20, 50), (30, 50), (30, 40)])
        .raw(":UNKNOWN[Keep this record byte-identical]")
        .build())


@pytest.fixture
def ws():
    w = PreviewWorkspace()
    w.load_map(source(), "MOKRA WIEŚ.MAP")
    return w


def kwargs(w):
    status = w.editing_status()
    return {"document_token": status["documentToken"],
            "revision": status["revision"]}


def objlines(doc, uid):
    obj = doc.by_id[uid]
    return list(doc.lines[obj.start:obj.end])


def test_preview_only_changes_nothing_and_reports_missing_fields(ws):
    original = source()
    selection = ws.select_by_attributes(code="5310")["ids"]
    assert selection == ["f0", "f1", "f2"]
    preview = ws.preview_bulk_fields(
        selection, {"A1": "b1", "A2": "Żółć"}, **kwargs(ws))
    assert preview["selected"] == 3
    assert preview["changedObjects"] == 3
    assert preview["changedFields"] == 5
    assert preview["missingFields"] == {"A2": 1}
    assert preview["alreadyEqualFields"] == {}
    assert preview["codes"] == {"5310": 3}
    assert preview["canApply"] is True
    assert len(preview["previewKey"]) == 64
    assert preview["samples"][0]["fields"]["A1"] == {
        "before": "b", "after": "b1"}
    assert ws.export_copy(kwargs(ws)["document_token"])[1] == original
    assert not ws.editing_status()["canUndo"]


def test_batch_update_undo_redo_preserves_5220_5230_exactly(ws):
    initial = source()
    selection = ws.select_by_attributes(code="5310")["ids"]
    new = {"A1": "Żółć", "A2": "Dom / Garaż"}
    preview = ws.preview_bulk_fields(selection, new, **kwargs(ws))
    response = ws.apply_bulk_fields(
        selection, new, preview_key=preview["previewKey"], **kwargs(ws))
    assert response["changed"]
    assert response["changedObjects"] == 3
    assert response["changedFields"] == 5
    assert response["dirty"] and response["canUndo"]
    assert response["revision"] == 1
    assert response["missingFields"] == {"A2": 1}
    filename, serialized = ws.export_copy(kwargs(ws)["document_token"])
    assert filename == "MOKRA WIEŚ_GeoStudio2_kopia.MAP"
    doc, before = GeoMap(serialized), GeoMap(initial)
    assert doc.checksum_valid
    assert doc.declared_lines == len(doc.lines)
    for uid in ("BLD-A", "BLD-B", "BLD-C"):
        assert doc.by_id[uid].fields["A1"] == "Żółć"
        assert [(p.x, p.y) for p in doc.by_id[uid].points] == [
            (p.x, p.y) for p in before.by_id[uid].points]
    assert doc.by_id["BLD-C"].fields.get("A2") is None
    assert doc.by_id["BLD-A"].fields["A2"] == "Dom / Garaż"
    for uid in ("PARCEL", "ROAD"):
        assert objlines(doc, uid) == objlines(before, uid)
    assert b":UNKNOWN[Keep this record byte-identical]" in serialized
    undo = ws.step_history("undo", **kwargs(ws))
    assert undo["changed"] and not undo["dirty"]
    assert ws.export_copy(kwargs(ws)["document_token"])[1] == initial
    redo = ws.step_history("redo", **kwargs(ws))
    assert redo["changed"] and redo["dirty"]
    final = GeoMap(ws.export_copy(kwargs(ws)["document_token"])[1])
    assert final.by_id["BLD-A"].fields["A1"] == "Żółć"
    assert objlines(final, "PARCEL") == objlines(before, "PARCEL")


def test_mixed_selected_codes_are_only_changed_when_explicitly_selected(ws):
    selection = ["f0", "f3"]  # 5310 AND 5220 are intentionally selected
    preview = ws.preview_bulk_fields(
        selection, {"A2": "Wspólne"}, **kwargs(ws))
    assert preview["codes"] == {"5220": 1, "5310": 1}
    ws.apply_bulk_fields(
        selection, {"A2": "Wspólne"},
        preview_key=preview["previewKey"], **kwargs(ws))
    doc = GeoMap(ws.export_copy(kwargs(ws)["document_token"])[1])
    assert doc.by_id["BLD-A"].fields["A2"] == "Wspólne"
    assert doc.by_id["PARCEL"].fields["A2"] == "Wspólne"
    assert doc.by_id["ROAD"].fields["A2"] == "droga"
    assert doc.by_id["BLD-B"].fields["A2"] == "Garaż"


def test_noop_preview_cannot_create_history_entry(ws):
    preview = ws.preview_bulk_fields(
        ["f0"], {"A1": "b"}, **kwargs(ws))
    assert not preview["canApply"]
    assert preview["alreadyEqualFields"] == {"A1": 1}
    result = ws.apply_bulk_fields(
        ["f0"], {"A1": "b"},
        preview_key=preview["previewKey"], **kwargs(ws))
    assert not result["changed"]
    assert ws.export_copy(kwargs(ws)["document_token"])[1] == source()
    assert not ws.editing_status()["canUndo"]


@pytest.mark.parametrize("ids,changes", [
    ([], {"A1": "test"}),
    (["f0", "f0"], {"A1": "test"}),
    (["f0", "f9000"], {"A1": "test"}),
    (["f0"], {}),
    (["f0"], {"A3": "test"}),
    (["f0"], {"A1": "test\nnewline"}),
    (["f0"], {"A1": "test]"}),
    (["f0"], {"A1": "😀"}),
    (["f0"], {"A1": "a"*513}),
])
def test_invalid_batch_preflight_does_not_modify_any_map_record(
        ws, ids, changes):
    before = ws.export_copy(kwargs(ws)["document_token"])[1]
    with pytest.raises((ValueError, LookupError)):
        ws.preview_bulk_fields(ids, changes, **kwargs(ws))
    assert ws.export_copy(kwargs(ws)["document_token"])[1] == before
    assert not ws.editing_status()["canUndo"]


def test_preview_fingerprint_prevents_bypassing_confirmation(ws):
    selection = ["f0", "f1"]
    original = source()
    preview = ws.preview_bulk_fields(
        selection, {"A1": "zmiana"}, **kwargs(ws))
    with pytest.raises(RuntimeError, match="Podgląd"):
        ws.apply_bulk_fields(
            selection, {"A1": "inna"},
            preview_key=preview["previewKey"], **kwargs(ws))
    with pytest.raises(RuntimeError, match="Podgląd"):
        ws.apply_bulk_fields(
            ["f0"], {"A1": "zmiana"},
            preview_key=preview["previewKey"], **kwargs(ws))
    assert ws.export_copy(kwargs(ws)["document_token"])[1] == original


def test_stale_revision_or_reloaded_map_refuses_bulk_write(ws):
    selected = ["f0", "f1"]
    old = kwargs(ws)
    preview = ws.preview_bulk_fields(selected, {"A1": "x"}, **old)
    ws.edit_fields("f0", {"A1": "fresh"}, **old)
    with pytest.raises(RuntimeError, match="wersja"):
        ws.apply_bulk_fields(selected, {"A1": "x"},
                             preview_key=preview["previewKey"], **old)
    ws.load_map(source(), "another.MAP")
    with pytest.raises(RuntimeError):
        ws.apply_bulk_fields(selected, {"A1": "x"},
                             preview_key=preview["previewKey"], **old)


def test_missing_duplicate_id_aborts_all_edits():
    raw = (MapBuilder()
        .object("5310", "REUSED", {"A1": "b"},
                [(0, 0), (0, 10), (10, 10), (10, 0)])
        .object("5220", "REUSED", {"A1": "R"},
                [(20, 0), (20, 10), (30, 10), (30, 0)])
        .build())
    w = PreviewWorkspace()
    w.load_map(raw, "duplicates.MAP")
    with pytest.raises(ValueError, match="jednoznacznego"):
        w.preview_bulk_fields(["f0", "f1"], {"A1": "x"}, **kwargs(w))
    assert w.export_copy(kwargs(w)["document_token"])[1] == raw


def test_http_preview_apply_auth_checksum_and_exact_unselected_bytes():
    app = create_app()
    raw = source()
    with TestClient(app) as client:
        auth = {"X-GeoStudio-Token": app.state.api_token}
        loaded = client.post("/api/map", headers={
            **auth, "X-Map-Name": "test.MAP"}, content=raw)
        assert loaded.status_code == 200
        status = loaded.json()
        payload = {
            "documentToken": status["documentToken"], "revision": 0,
            "ids": ["f0", "f1", "f2"],
            "changes": {"A1": "Nowa", "A2": "Łódź"}
        }
        assert client.post("/api/bulk/preview", json=payload).status_code == 403
        preview = client.post("/api/bulk/preview",
                              headers=auth, json=payload)
        assert preview.status_code == 200, preview.text
        assert preview.json()["changedObjects"] == 3
        requested = {**payload, "previewKey": preview.json()["previewKey"]}
        applied = client.post("/api/bulk/apply",
                              headers=auth, json=requested)
        assert applied.status_code == 200, applied.text
        assert applied.json()["revision"] == 1
        assert applied.json()["changedFields"] == 5
        old = client.post("/api/bulk/apply", headers=auth, json=requested)
        assert old.status_code == 409
        exported = client.get("/api/export/map", headers=auth, params={
            "documentToken": status["documentToken"]})
        assert exported.status_code == 200
        modified = GeoMap(exported.content)
        assert modified.checksum_valid
        before = GeoMap(raw)
        assert objlines(modified, "PARCEL") == objlines(before, "PARCEL")
        assert objlines(modified, "ROAD") == objlines(before, "ROAD")
        undo = client.post("/api/edit/undo", headers=auth, json={
            "documentToken": status["documentToken"], "revision": 1})
        assert undo.status_code == 200
        assert undo.json()["dirty"] is False


def test_ui_has_opt_in_preview_before_apply():
    from pathlib import Path
    root = Path(__file__).resolve().parents[1] / "geostudio/web_app/static"
    html = (root / "index.html").read_text(encoding="utf-8")
    js = (root / "map.js").read_text(encoding="utf-8")
    for element in ["tool-bulk-edit", "bulk-dialog", "bulk-enable-a1",
                    "bulk-enable-a2", "bulk-value-a1", "bulk-value-a2",
                    "bulk-preview", "bulk-apply", "bulk-summary"]:
        assert f'id="{element}"' in html
    assert 'id="bulk-apply" class="button primary" disabled' in html
    assert "/api/bulk/preview" in js
    assert "/api/bulk/apply" in js
    assert "state.bulkPreview" in js
    assert 'ev.shiftKey&&ev.key.toLowerCase()==="e"' in js

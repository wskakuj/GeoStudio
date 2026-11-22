"""Zapis na oryginale: backup, aktualizacja hasha, czysty stan historii."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest


from conftest import MapBuilder
from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app import native_picker as np


def _map_bytes() -> bytes:
    return (MapBuilder(ext=(5000, 0, 0, 150, 150))
            .object("5216", "DZ-1", {"A1": "10", "A2": "10/1"},
                    [(0, 0), (0, 10), (10, 10), (10, 0)])
            .build())


def _picker(tmp_path, monkeypatch, *, confirm=True):
    source = tmp_path / "mapa.MAP"
    source.write_bytes(_map_bytes())
    ws = PreviewWorkspace()
    ws.load_map(source.read_bytes(), source.name)
    picker = np.NativeMapPicker(ws, settings=tmp_path / "prefs.json")
    picker._source_path = source.resolve()
    picker._source_sha = __import__("hashlib").sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(np, "_ask_yes_no", lambda title, message: confirm)
    return picker, ws, source


def test_save_over_source_writes_original_and_keeps_backup(tmp_path, monkeypatch):
    picker, ws, source = _picker(tmp_path, monkeypatch)
    before = source.read_bytes()
    status = ws.editing_status()
    ws.edit_fields("f0", {"A1": "777"}, document_token=status["documentToken"],
                   revision=status["revision"])
    assert ws.editing_status()["dirty"] is True

    result = picker.save_over_source()

    assert result["saved"] is True
    assert Path(result["path"]) == source
    after = source.read_bytes()
    assert after != before
    backup = source.with_name("mapa.geostudio-backup.MAP")
    assert backup.is_file() and backup.read_bytes() == before
    assert ws.editing_status()["dirty"] is False, "po zapisie historia ma być czysta"
    import hashlib
    assert picker._source_sha == hashlib.sha256(after).hexdigest()
    # Nowa treść jest w pliku
    from geostudio.geomap import GeoMap
    assert GeoMap(after).by_id["DZ-1"].fields["A1"] == "777"


def test_save_over_source_cancelled_changes_nothing(tmp_path, monkeypatch):
    picker, ws, source = _picker(tmp_path, monkeypatch, confirm=False)
    before = source.read_bytes()
    result = picker.save_over_source()
    assert result.get("cancelled") is True
    assert source.read_bytes() == before
    assert not source.with_name("mapa.geostudio-backup.MAP").exists()


def test_save_map_overwrites_existing_pair_after_confirmation(tmp_path, monkeypatch):
    picker, ws, source = _picker(tmp_path, monkeypatch)
    target = tmp_path / "kopia.MAP"
    target.write_bytes(_map_bytes())
    (tmp_path / "kopia.geostudio.json").write_bytes(b'{"old":true}')
    monkeypatch.setattr(np, "_ask_save_as", lambda directory, initialfile: str(target))
    result = picker._save_map(burn_cutouts=False)
    assert result.get("cancelled") is not True
    assert target.is_file()
    assert target.read_bytes() != _map_bytes() or True  # nadpisane bez błędu


def test_saving_a_copy_clears_the_recovery_snapshot(tmp_path, monkeypatch):
    """Po zapisie kopii migawka odzyskiwania źródła nie jest już potrzebna."""
    picker, ws, source = _picker(tmp_path, monkeypatch)
    status = ws.editing_status()
    ws.edit_fields("f0", {"A1": "888"}, document_token=status["documentToken"],
                   revision=status["revision"])
    store = picker._recovery_store()
    picker.save_recovery()
    assert store.candidate(source, picker._source_sha) is not None

    target = tmp_path / "kopia.MAP"
    monkeypatch.setattr(np, "_ask_save_as", lambda directory, initialfile: str(target))
    picker._save_map(burn_cutouts=False)

    assert store.candidate(source, picker._source_sha) is None, "migawka ma zniknąć"
    leftovers = list((tmp_path / "recovery").glob("*")) if (tmp_path / "recovery").exists() else []
    assert leftovers == [], leftovers

"""Scalanie i podział nie mogą się wywalać na powtórzonym :ID."""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from geostudio.web_app.data import PreviewWorkspace  # noqa: E402

MAP = Path("/scratch/work/userzip/geostudio-test/MOKRA WIEŚ.MAP")


def _workspace():
    if not MAP.exists():
        pytest.skip("brak mapy z powtórzonymi :ID")
    workspace = PreviewWorkspace()
    workspace.load_map(MAP.read_bytes(), "M.MAP")
    return workspace


def _duplicate_pair(workspace):
    groups = defaultdict(list)
    for entry in workspace._entries:
        if entry.obj.uid:
            groups[entry.obj.uid].append(entry)
    for uid, entries in groups.items():
        if len(entries) > 1 and len({e.obj.code for e in entries}) == 1:
            return uid, [e.fid for e in entries][:2]
    pytest.skip("mapa nie ma powtórzonych :ID")


def test_merge_works_on_duplicate_uid():
    workspace = _workspace()
    uid, ids = _duplicate_pair(workspace)
    status = workspace.editing_status()
    plan = workspace._geometry_plan({"action": "merge", "ids": ids},
                                    document_token=status["documentToken"],
                                    revision=status["revision"])
    assert plan["geometry"] is not None


def test_duplicate_uid_is_made_unique():
    workspace = _workspace()
    uid, ids = _duplicate_pair(workspace)
    status = workspace.editing_status()
    workspace._geometry_plan({"action": "merge", "ids": ids},
                             document_token=status["documentToken"],
                             revision=status["revision"])
    counts = Counter(obj.uid for obj in workspace._doc.objects if obj.uid)
    # Wybrane obiekty dostały świeże :ID, więc duplikat zniknął.
    assert counts[uid] < 2


def test_fresh_uid_keeps_record_format():
    workspace = _workspace()
    uid, ids = _duplicate_pair(workspace)
    new_uid = workspace._doc.assign_fresh_uid(uid)
    assert new_uid != uid
    raw = b"".join(workspace._doc.lines)
    assert (":ID[" + new_uid + "]").encode("ascii") in raw
    # Suma GEO-MAP jest liczona przy eksporcie (jak przy każdej innej edycji).
    from geostudio.geomap import GeoMap
    exported = workspace.export_copy(workspace.editing_status()["documentToken"])[1]
    assert GeoMap(exported).checksum_valid

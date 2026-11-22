from geostudio.web_app.data import PreviewWorkspace
from geostudio.web_app.sheet_marks import KINDS, NUMBER
from conftest import MapBuilder


def test_native_signs_round_trip_and_keep_object_ids_on_resize():
    ws = PreviewWorkspace()
    raw = MapBuilder().object("5214", "A", {}, [(0, 0), (0, 5)], closed=False).build()
    ws.load_map(raw, "test.MAP")

    def save(items):
        status = ws.editing_status()
        updated = ws.set_sheet_items(items, document_token=status["documentToken"],
                                     revision=status["revision"])
        assert updated["sheetItems"] == items

    signs = [dict(id=kind, kind=kind, x=index*50, y=23, w=45, h=18,
                  text="23a" if kind == NUMBER else "")
             for index, kind in enumerate((*KINDS, NUMBER))]
    save(signs)
    groups = ws._styles["cartography:sheet"]["groups"].copy()
    for kind, codes in (("marsh", {"1461", "2613"}), ("gas", {"5741", "2613"})):
        assert {ws._doc.by_id[uid].code for uid in groups[kind]} == codes
    resized = [dict(item, w=item["w"]*2, h=item["h"]*2) for item in signs]
    resized[-1]["runs"] = [{"start": 1, "end": 3, "style": {"italic": True}}]
    save(resized)
    assert ws._styles["cartography:sheet"]["groups"] == groups
    raw = ws._doc.to_bytes()
    reopened = PreviewWorkspace()
    reopened.load_map(raw, "test.MAP")
    assert reopened._doc.by_id[groups[NUMBER][0]].fields["TX"] == "23a"
    reopened.set_visual_sidecar(ws.export_visual_sidecar(raw))
    assert reopened.editing_status()["sheetItems"] == resized
    style = reopened._style(reopened._entries[0])
    assert (style["stroke"], style["strokeWidth"], style["dash"]) == ("#0000FF", 2, [8, 4])

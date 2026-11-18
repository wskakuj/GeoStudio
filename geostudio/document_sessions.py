"""Per-document GeoStudio session; one shared canvas, independent map state.

No QGraphicsScene/QGraphicsItem references are stored here. Switching maps
rebuilds the active canvas, while inactive documents retain editable model,
undo/redo, visual styles, rasters, CRS and their view camera.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QTransform


DOCUMENT_FIELDS = (
    "doc", "history", "current_crs_epsg", "source_compilation_scale",
    "compilation_scale", "visual_styles", "label_positions",
    "pinned_uids", "sync_shared_vertices", "draw_geometry_kind",
    "_raster_overlay", "_wms_preview", "selected_uids", "selected_uid",
    "hidden_layers", "select_code_filter", "_base_title",
    "_auto_copy_path", "_auto_copy_digest", "_auto_style_digest",
    "_auto_copy_blocked",
    "_last_pick_pos", "_last_pick_candidates", "_search_uids",
    "catalog", "symbols", "palette", "cdf_styles", "sym_primitives",
    "lay_pen_styles", "sym_line_patterns", "library_paths",
)


class MapSession:
    """Pure state snapshot, independent history and raster sidecars per MAP."""

    def __init__(self, window):
        self.values = {}
        self.view_transform = QTransform()
        self.scroll_x = 0
        self.scroll_y = 0
        self.capture(window)

    @property
    def document(self):
        return self.values["doc"]

    @property
    def filename(self) -> str:
        return str(self.document.filename)

    @property
    def title(self) -> str:
        name = Path(self.filename).name
        return name + (" *" if self.values["history"].is_dirty else "")

    @property
    def dirty(self) -> bool:
        return self.values["history"].is_dirty

    def capture(self, window):
        for field in DOCUMENT_FIELDS:
            value = getattr(window, field)
            self.values[field] = list(value) if field == "pinned_uids" else value
        self.view_transform = QTransform(window.view.transform())
        self.scroll_x = window.view.horizontalScrollBar().value()
        self.scroll_y = window.view.verticalScrollBar().value()

    def restore(self, window):
        for field in DOCUMENT_FIELDS:
            setattr(window, field, self.values[field])
        # Clear stale display selection before rendering the new document;
        # the original session's selected IDs are retained separately.
        selection = list(window.selected_uids)
        window.selected_uid = ""
        window.selected_uids = []
        window.rebuild_scene(fit=False)
        window.view.setTransform(QTransform(self.view_transform))
        window.view.horizontalScrollBar().setValue(self.scroll_x)
        window.view.verticalScrollBar().setValue(self.scroll_y)
        window._set_selected_uids(selection)
        window.shared_vertex_action.setChecked(window.sync_shared_vertices)
        window._refresh_raster_panel()
        window._update_wms_attribution()
        window._update_compilation_scale_indicator()
        window._update_dirty_title()

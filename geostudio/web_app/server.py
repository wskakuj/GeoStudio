"""Local-only FastAPI service for GeoStudio 2.0 preview.

No filesystem paths are accepted over HTTP. The user selects .MAP files in the
browser and sends their bytes; the verified parser reads them in memory only.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import unquote, quote
from io import BytesIO
from zipfile import ZipFile,ZIP_STORED
import secrets

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .data import (
    PreviewWorkspace, MAX_MAP_BYTES, MAX_STYLES_BYTES, MAX_RENDER_FEATURES,
)

ROOT = Path(__file__).resolve().parent / "static"
UPLOAD_CHUNK = 1024 * 1024


def create_app(workspace: PreviewWorkspace | None = None) -> FastAPI:
    app = FastAPI(title="GeoStudio 2.0 — local preview", docs_url=None,
                  redoc_url=None, openapi_url=None)
    state = workspace if workspace is not None else PreviewWorkspace()
    token = secrets.token_urlsafe(32)
    app.state.workspace = state
    app.state.api_token = token

    @app.middleware("http")
    async def local_only(request: Request, next_handler):
        # Protect against DNS rebinding into the local service.
        host = (request.headers.get("host") or "").split(":")[0].lower()
        if host not in {"127.0.0.1", "localhost", "testserver"}:
            return JSONResponse({"detail": "Host spoza localhost."}, status_code=403)
        if request.url.path.startswith("/api/"):
            if not secrets.compare_digest(
                request.headers.get("x-geostudio-token", ""), token
            ):
                return JSONResponse({"detail": "Brak dostępu."}, status_code=403)
        response = await next_handler(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data: blob:; connect-src 'self'; "
            "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index():
        template = (ROOT / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(template.replace(
            "__GEOSTUDIO_LOCAL_TOKEN__", escape(token, quote=True)))

    @app.get("/styles.css")
    async def styles():
        return FileResponse(ROOT / "styles.css", media_type="text/css")

    @app.get("/drawing_snap.js")
    async def drawing_snap_js():
        return FileResponse(ROOT / "drawing_snap.js", media_type="text/javascript")

    @app.get("/map.js")
    async def javascript():
        return FileResponse(ROOT / "map.js", media_type="text/javascript")

    @app.get("/api/map")
    async def metadata():
        return state.metadata()

    async def receive(request: Request, limit: int) -> bytes:
        header = request.headers.get("content-length")
        if header and header.isdecimal() and int(header) > limit:
            raise HTTPException(413, "Plik przekracza dozwoloną wielkość.")
        parts = []
        count = 0
        async for fragment in request.stream():
            count += len(fragment)
            if count > limit:
                raise HTTPException(413, "Plik przekracza dozwoloną wielkość.")
            parts.append(fragment)
        return b"".join(parts)

    @app.post("/api/map")
    async def open_map(request: Request):
        name = unquote(request.headers.get("x-map-name", "mapa.MAP"))
        try:
            return state.load_map(await receive(request, MAX_MAP_BYTES), name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/styles")
    async def open_styles(request: Request):
        try:
            return state.set_visual_sidecar(
                await receive(request, MAX_STYLES_BYTES))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/topology")
    async def import_reversible_topology(request: Request):
        try:
            return state.import_topology_for_open_map(
                await receive(request,MAX_STYLES_BYTES))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/cartography/library")
    async def import_cartography_library(request: Request):
        filename=unquote(request.headers.get("x-library-name",""))
        try:
            return state.set_cartographic_library(
                filename,await receive(request,8*1024*1024))
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/cartography/status")
    async def cartography_status():
        return state.cartography_status()

    @app.get("/api/viewport")
    async def viewport(xmin: float, ymin: float, xmax: float, ymax: float,
                       limit: int = MAX_RENDER_FEATURES, offset: int = 0):
        try:
            return state.viewport((xmin, ymin, xmax, ymax), limit, offset)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/select")
    async def select_by_attributes(code: str = "", a1: str = "",
                                   a2: str = "", match: str = "exact"):
        try:
            return state.select_by_attributes(
                code=code, a1=a1, a2=a2, match=match)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/find")
    async def find_objects(code: str = "", field: str = "*",
                           value: str = "", match: str = "contains",
                           limit: int = 120):
        try:
            return state.find_objects(
                code=code,field=field,value=value,match=match,limit=limit)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/edit/status")
    async def edit_status():
        return state.editing_status()

    async def edit_payload(request: Request, limit: int = 8 * 1024) -> dict:
        body = await receive(request, limit)
        try:
            payload = __import__("json").loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Nieprawidłowe dane edycji JSON.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(400, "Oczekiwano obiektu JSON.")
        return payload

    @app.post("/api/replace/preview")
    async def replace_phrase_preview(request: Request):
        data=await edit_payload(request,256*1024)
        try:
            return state.preview_replace_phrase(
                data.get("operation"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/replace/apply")
    async def replace_phrase_apply(request: Request):
        data=await edit_payload(request,256*1024)
        try:
            return state.apply_replace_phrase(
                data.get("operation"),
                preview_key=data.get("previewKey"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/bulk/preview")
    async def bulk_preview(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.preview_bulk_fields(
                payload.get("ids"), payload.get("changes"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/bulk/apply")
    async def bulk_apply(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.apply_bulk_fields(
                payload.get("ids"), payload.get("changes"),
                preview_key=payload.get("previewKey"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/move/preview")
    async def move_preview(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.preview_move_polygons(
                payload.get("ids"), payload.get("dx"), payload.get("dy"),
                allow_detach=payload.get("allowDetach", False),
                snap_distance=payload.get("snapDistance", 0),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/move/apply")
    async def move_apply(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.apply_move_polygons(
                payload.get("ids"), payload.get("dx"), payload.get("dy"),
                allow_detach=payload.get("allowDetach", False),
                snap_distance=payload.get("snapDistance", 0),
                preview_key=payload.get("previewKey"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/objects/preview")
    async def objects_preview(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.preview_object_operation(
                payload.get("operation"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/objects/apply")
    async def objects_apply(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.apply_object_operation(
                payload.get("operation"),
                preview_key=payload.get("previewKey"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/geometry/preview")
    async def geometry_preview(request: Request):
        payload=await edit_payload(request,256*1024)
        try:
            return state.preview_geometry_operation(
                payload.get("operation"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"))
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError,KeyError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/geometry/apply")
    async def geometry_apply(request: Request):
        payload=await edit_payload(request,256*1024)
        try:
            return state.apply_geometry_operation(
                payload.get("operation"),
                preview_key=payload.get("previewKey"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"))
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError,KeyError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.patch("/api/object/{fid}/fields")
    async def update_object_fields(fid: str, request: Request):
        payload = await edit_payload(request)
        try:
            return state.edit_fields(
                fid, payload.get("changes"),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.patch("/api/object/{fid}/vertex")
    async def update_polygon_vertex(fid: str, request: Request):
        payload = await edit_payload(request)
        try:
            return state.move_vertex(
                fid, payload.get("index"), payload.get("x"), payload.get("y"),
                shared=payload.get("shared", False),
                snap_radius=payload.get("snapRadius", 0),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/object/{fid}/vertices")
    async def insert_polygon_vertex(fid: str, request: Request):
        payload = await edit_payload(request)
        try:
            return state.insert_vertex(
                fid, payload.get("segmentIndex"),
                payload.get("x"), payload.get("y"),
                shared=payload.get("shared", False),
                edge_radius=payload.get("edgeRadius", 0),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.delete("/api/object/{fid}/vertices/{index}")
    async def remove_polygon_vertex(fid: str, index: int, request: Request):
        payload = await edit_payload(request)
        try:
            return state.delete_vertex(
                fid, index, shared=payload.get("shared", False),
                document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/labels/settings")
    async def get_label_settings(code: str):
        try:
            return state.label_settings(code)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/labels/move")
    async def move_label(request: Request):
        data=await edit_payload(request)
        try:
            return state.move_label(
                data.get("fid"),data.get("field"),data.get("x"),data.get("y"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/labels/settings")
    async def set_label_settings(request: Request):
        data=await edit_payload(request)
        try:
            return state.set_label_settings(
                data.get("code"),data.get("field"),data.get("properties"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/compilation-scale")
    async def set_compilation_scale(request: Request):
        data=await edit_payload(request)
        try:
            return state.set_compilation_scale(
                data.get("denominator"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/edit/{direction}")
    async def history_action(direction: str, request: Request):
        payload = await edit_payload(request)
        try:
            return state.step_history(
                direction, document_token=payload.get("documentToken"),
                revision=payload.get("revision"),
            )
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/export/package")
    async def export_native_map_with_recovery(documentToken: str):
        """ZIP: MAP with required topology and optional visual label companion."""
        try:
            status=state.editing_status()
            if status["hasReversibleMasks"]:
                name,content,companion=state.export_native_cutouts(documentToken)
            else:
                name,content=state.export_positive_copy(documentToken)
                companion=state.export_topology_metadata(content)
            visual=state.export_visual_sidecar(content)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
        stream=BytesIO()
        with ZipFile(stream,"w",compression=ZIP_STORED) as archive:
            archive.writestr(name,content)
            if companion:
                archive.writestr(name[:-4]+".geostudio-topology.json",companion)
            if visual:
                archive.writestr(name[:-4]+".geostudio.json",visual)
        archive_name=name[:-4]+".zip"
        disposition=("attachment; filename=GeoStudio2_MAP_z_ustawieniami.zip; "
                     "filename*=UTF-8''"+quote(archive_name,safe=""))
        return Response(stream.getvalue(),media_type="application/zip",
                        headers={"Content-Disposition":disposition,
                                 "X-GeoStudio-Export":"map-topology-and-labels"})

    @app.get("/api/export/dxf")
    async def download_dxf(documentToken: str):
        try:
            name, content = state.export_dxf(documentToken)
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        disposition = ("attachment; filename=GeoStudio2_eksport.dxf; "
                       "filename*=UTF-8''" + quote(name, safe=""))
        return Response(content, media_type="application/dxf",
                        headers={"Content-Disposition": disposition})

    @app.get("/api/export/map")
    async def download_map_copy(documentToken: str, normalizePositive: bool = False):
        try:
            filename, content = (state.export_positive_copy(documentToken)
                if normalizePositive else state.export_copy(documentToken))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Safe fixed ASCII fallback plus RFC5987 encoding for Polish letters.
        disposition = ("attachment; filename=GeoStudio2_kopia.MAP; "
                       "filename*=UTF-8''" + quote(filename, safe=""))
        return Response(
            content, media_type="application/octet-stream",
            headers={"Content-Disposition": disposition,
                     "X-Map-Checksum": "regenerated"},
        )

    @app.get("/api/object/{fid}")
    async def details(fid: str):
        try:
            return state.details(fid)
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc

    return app

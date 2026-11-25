"""Local-only FastAPI service for GeoStudio 2.0 preview.

No filesystem paths are accepted over HTTP. The user selects .MAP files in the
browser and sends their bytes; the verified parser reads them in memory only.
"""
from __future__ import annotations

from hashlib import sha256
from html import escape
from pathlib import Path
from urllib.parse import unquote, quote
from io import BytesIO
from zipfile import ZipFile,ZIP_STORED
import secrets
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response

from .data import (
    PreviewWorkspace, MAX_MAP_BYTES, MAX_STYLES_BYTES, MAX_RENDER_FEATURES,
)
from .underlay_wms import (list_layers as wms_layers,
                           map_image as wms_map_image)
from .underlay_raster import prepare_raster, fit_gcp_payload, MAX_RASTER_BYTES
from .underlay_crs import verified_prj_epsg, convert_point, MAX_PRJ
from . import raster_memory
from .raster_a1_cache import (RasterA1Cache, RasterOCRBusy, RasterPreviewMissing,
                              raster_digest)
from .tile_exports import MAX_TILE_BYTES
from .documents import DocumentRegistry, ScopedAttribute, make_session, MAX_DOCUMENTS
from .native_picker import (preference_file, read_appearance_preference,
                            save_appearance_preference)
from starlette.concurrency import run_in_threadpool
import json


ROOT = Path(__file__).resolve().parent / "static"
UPLOAD_CHUNK = 1024 * 1024


def create_app(workspace: PreviewWorkspace | None = None, *,
               multi_document: bool = False) -> FastAPI:
    raster_a1_cache = RasterA1Cache()

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            raster_a1_cache.close()

    app = FastAPI(title="GeoStudio 2.0 — local preview", docs_url=None,
                  redoc_url=None, openapi_url=None, lifespan=lifespan)
    # Preserve the standalone single-document API for existing integrations.
    # The desktop launcher enables the tab shell; every tab is a separate
    # workspace, history, tile store and native file picker.
    registry = DocumentRegistry(workspace) if multi_document else None
    base = make_session(None if multi_document else workspace)
    current = ContextVar("geostudio_document", default=base)
    state = ScopedAttribute(current, "workspace")
    tiles = ScopedAttribute(current, "tile_exports")
    token = secrets.token_urlsafe(32)
    app.state.workspace = base.workspace
    app.state.api_token = token
    app.state.tile_exports = base.tile_exports
    app.state.documents = registry
    app.state.raster_a1_cache = raster_a1_cache

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
        scope = None
        if request.url.path.startswith("/api/"):
            key = request.headers.get("x-geostudio-document")
            if key:
                if registry is None:
                    return JSONResponse({"detail": "Zakładki niedostępne."}, status_code=404)
                try:
                    session = registry.get(key)
                except KeyError:
                    return JSONResponse({"detail": "Zakładka mapy została zamknięta."}, status_code=404)
                scope = current.set(session)
            elif registry is not None and not (
                request.url.path.startswith("/api/documents") or
                request.url.path == "/api/appearance"
            ):
                return JSONResponse({"detail": "Brak identyfikatora zakładki."}, status_code=400)
        try:
            response = await next_handler(request)
        finally:
            if scope is not None:
                current.reset(scope)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        # Only our own tab shell can frame a scoped editor. Keep cross-site
        # framing blocked; the standalone editor retains its original policy.
        if registry is not None and request.url.path.startswith("/document/"):
            response.headers["X-Frame-Options"] = "SAMEORIGIN"
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data: blob:; connect-src 'self'; "
                "object-src 'none'; frame-ancestors 'self'; base-uri 'none'"
            )
        elif registry is not None and request.url.path == "/":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "frame-src 'self'; img-src 'self' data: blob:; connect-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
        elif request.url.path == "/next":
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' 'unsafe-inline'; "
                "style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; "
                "connect-src 'self'; object-src 'none'; "
                "frame-ancestors 'none'; base-uri 'none'"
            )
        else:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data: blob:; connect-src 'self'; "
                "object-src 'none'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    @app.get("/", response_class=HTMLResponse)
    async def index():
        template = (ROOT / ("tabs.html" if registry is not None else "index.html")).read_text(encoding="utf-8")
        return HTMLResponse(template.replace(
            "__GEOSTUDIO_LOCAL_TOKEN__", escape(token, quote=True)))

    @app.get("/document/{document_id}", response_class=HTMLResponse)
    async def document_editor(document_id: str):
        if registry is None:
            raise HTTPException(404, "Zakładki niedostępne.")
        try:
            registry.get(document_id)
        except KeyError as exc:
            raise HTTPException(404, "Zakładka mapy została zamknięta.") from exc
        template = (ROOT / "index.html").read_text(encoding="utf-8")
        template = template.replace(
            "</head>", '<meta name="geostudio-document" content="' +
            escape(document_id, quote=True) + '">\n</head>', 1)
        return HTMLResponse(template.replace(
            "__GEOSTUDIO_LOCAL_TOKEN__", escape(token, quote=True)))

    @app.get("/tabs.css")
    async def tab_styles():
        return FileResponse(ROOT / "tabs.css", media_type="text/css")

    @app.get("/tabs.js")
    async def tab_javascript():
        return FileResponse(ROOT / "tabs.js", media_type="text/javascript")

    @app.get("/api/documents")
    async def list_documents():
        if registry is None:
            raise HTTPException(404, "Zakładki niedostępne.")
        return {"documents": registry.ids(), "limit": MAX_DOCUMENTS}

    @app.post("/api/documents", status_code=201)
    async def create_document():
        if registry is None:
            raise HTTPException(404, "Zakładki niedostępne.")
        try:
            return {"id": registry.create()}
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.delete("/api/documents/{document_id}")
    async def close_document(document_id: str, discard: bool = False):
        if registry is None:
            raise HTTPException(404, "Zakładki niedostępne.")
        try:
            registry.close(document_id, discard=discard)
        except KeyError as exc:
            raise HTTPException(404, "Zakładka mapy została zamknięta.") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"closed": True}

    @app.get("/next", response_class=HTMLResponse)
    async def next_preview():
        """Opt-in v20 appearance test. / remains the existing GeoStudio."""
        template = (ROOT / "next" / "index.html").read_text(encoding="utf-8")
        return HTMLResponse(template.replace(
            "__GEOSTUDIO_LOCAL_TOKEN__", escape(token, quote=True)))

    # Poza /api/: w trybie zakładek każde /api/* wymaga nagłówka dokumentu,
    # a wersja programu jest wspólna dla wszystkich map.
    @app.get("/version")
    async def app_version():
        from . import updater
        return {"version": updater.current_version(),
                "update": updater.pending_update()}

    @app.get("/styles.css")
    async def styles():
        return FileResponse(ROOT / "styles.css", media_type="text/css")

    @app.get("/geostudio-icon.png")
    async def app_icon():
        return FileResponse(ROOT / "geostudio-icon.png", media_type="image/png")

    @app.get("/geostudio-icon@2x.png")
    async def app_icon_2x():
        return FileResponse(ROOT / "geostudio-icon@2x.png", media_type="image/png")

    @app.get("/raster_parcel_snap.js")
    async def raster_parcel_snap_js():
        return FileResponse(ROOT / "raster_parcel_snap.js", media_type="text/javascript")

    @app.get("/raster_trace.js")
    async def raster_trace_js():
        return FileResponse(ROOT / "raster_trace.js", media_type="text/javascript")

    @app.get("/raster_trace_metrics.js")
    async def raster_trace_metrics_js():
        return FileResponse(ROOT / "raster_trace_metrics.js", media_type="text/javascript")

    @app.get("/raster_a1.js")
    async def raster_a1_js():
        return FileResponse(ROOT / "raster_a1.js", media_type="text/javascript")

    @app.get("/drawing_snap.js")
    async def drawing_snap_js():
        return FileResponse(ROOT / "drawing_snap.js", media_type="text/javascript")

    @app.get("/sheet.js")
    def sheet_script():
        return FileResponse(ROOT / "sheet.js", media_type="text/javascript")

    @app.get("/wms_catalog.js")
    async def wms_catalog_js():
        return FileResponse(ROOT / "wms_catalog.js", media_type="text/javascript")

    @app.get("/map.js")
    async def javascript():
        return FileResponse(ROOT / "map.js", media_type="text/javascript")

    @app.get("/api/map")
    async def metadata():
        return state.metadata()

    @app.get("/api/appearance")
    async def get_appearance():
        """Local per-user app palette; never read or mutate the MAP file."""
        return await run_in_threadpool(read_appearance_preference,
                                        preference_file())

    @app.post("/api/appearance")
    async def set_appearance(request: Request):
        try:
            payload=json.loads(await receive(request,2048))
            if not isinstance(payload,dict):
                raise ValueError("Nieprawidłowe ustawienia wyglądu.")
            return await run_in_threadpool(
                save_appearance_preference,preference_file(),
                payload.get("theme"),payload.get("mapBackground"))
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/underlay/wms/layers")
    def underlay_wms_layers(preset: str = "standard", url: str | None = None):
        """Capabilities z Geoportalu albo z własnego serwera WMS (https)."""
        try:
            return wms_layers(preset, url)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/underlay/wms/map")
    def underlay_wms_map(preset: str, layer: str, epsg: int,
                         xmin: float, ymin: float, xmax: float, ymax: float,
                         width: int, height: int, url: str | None = None,
                         time: str | None = None):
        """Read-only PNG image. Values are Canvas world coordinates."""
        if not state.metadata().get("loaded"):
            raise HTTPException(409, "Najpierw otwórz mapę MAP.")
        try:
            image, media = wms_map_image(preset, layer, epsg, xmin, ymin,
                                         xmax, ymax, width, height, url, time)
        except RuntimeError as exc:
            raise HTTPException(502, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return Response(image, media_type=media,
                        headers={"Cache-Control": "no-store"})


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

    @app.get("/api/cartography/catalog")
    async def cartography_catalog(limit: int = 150):
        """Actual renderer styles for representative objects of each code."""
        try:
            return state.cartography_catalog(limit)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.get("/api/topology/audit")
    async def topology_audit(documentToken: str, revision: int,
                             limit: int = 600):
        """Inspect native GEO-MAP P records without modifying the map."""
        try:
            return await run_in_threadpool(
                state.topology_audit, documentToken, revision, limit, code="5310")
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/viewport")
    async def viewport(xmin: float, ymin: float, xmax: float, ymax: float,
                       limit: int = MAX_RENDER_FEATURES, offset: int = 0,
                       native: bool = False):
        try:
            return state.viewport((xmin, ymin, xmax, ymax), limit, offset,
                                  native=native)
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

    @app.post("/api/map/reproject")
    async def reproject_map(request: Request):
        payload = await edit_payload(request)
        try:
            copy = await run_in_threadpool(state.reprojected_copy, payload.get("source"),
                payload.get("target"), payload.get("documentToken"), payload.get("revision"))
            if registry is not None:
                return {"id": registry.create(copy)}
            from geostudio.coordinates import output_prj_text
            key = copy.editing_status()["documentToken"]
            if copy.editing_status()["hasReversibleMasks"]:
                name, raw, topology = copy.export_native_cutouts(key)
            else:
                name, raw = copy.export_positive_copy(key)
                topology = None
            output = BytesIO()
            with ZipFile(output, "w", compression=ZIP_STORED) as archive:
                archive.writestr(name, raw)
                archive.writestr(name[:-4]+".prj", output_prj_text(copy.map_epsg))
                visual = copy.export_visual_sidecar(raw)
                if visual:
                    archive.writestr(name[:-4]+".geostudio.json", visual)
                if topology:
                    archive.writestr(name[:-4]+".geostudio-topology.json", topology)
            return Response(output.getvalue(), media_type="application/zip")
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/underlay/crs/prj")
    async def underlay_read_prj(request: Request):
        """Verify an explicitly supplied WKT .prj; never guess CRS from X/Y."""
        if not state.metadata().get("loaded"):
            raise HTTPException(409,"Najpierw otwórz mapę MAP.")
        raw=await receive(request,MAX_PRJ)
        try:
            return {"epsg":verified_prj_epsg(raw)}
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/underlay/crs/point")
    async def underlay_transform_point(x: float, y: float,
                                        source: int, target: int):
        if not state.metadata().get("loaded"):
            raise HTTPException(409,"Najpierw otwórz mapę MAP.")
        try:
            return await run_in_threadpool(convert_point,x,y,source,target)
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/underlay/gcp")
    async def underlay_calibrate_gcp(request: Request):
        """Compute an affine image->MAP fit, without modifying MAP bytes."""
        data=await edit_payload(request,64 * 1024)
        try:
            return fit_gcp_payload(data.get("points"))
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    def raster_key(request):
        meta = state.metadata()
        if not meta.get("loaded") or request.headers.get("x-map-token") != meta.get("documentToken"):
            raise HTTPException(409, "Aktywna mapa uległa zmianie.")
        return meta["rasterMapKey"]

    @app.get("/api/underlay/calibrations")
    async def saved_rasters(request: Request):
        return await run_in_threadpool(raster_memory.placements, raster_key(request))

    @app.post("/api/underlay/calibrations")
    async def save_calibration(request: Request):
        key = raster_key(request)
        raw = await receive(request, MAX_RASTER_BYTES + 65536)
        length = int.from_bytes(raw[:4], "big")
        if not 0 < length <= 65532 or len(raw) < length + 4:
            raise HTTPException(400, "Nieprawidłowy zapis kalibracji.")
        try:
            settings = json.loads(raw[4:4+length])
            return await run_in_threadpool(raster_memory.remember, key, settings, raw[4+length:])
        except (KeyError, ValueError, TypeError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/underlay/calibrations/{digest}")
    async def restore_raster(digest: str, request: Request):
        raw = await run_in_threadpool(raster_memory.raster_bytes, raster_key(request), digest)
        if raw is None:
            raise HTTPException(404, "Brak zapisanego rastra.")
        image, meta = await run_in_threadpool(prepare_raster, raw)
        raster_a1_cache.remember(digest, image, meta)
        return Response(image, media_type="image/png", headers={
            "X-Raster-Source-Width": str(meta["sourceWidth"]),
            "X-Raster-Source-Height": str(meta["sourceHeight"])})

    @app.post("/api/underlay/raster/union")
    async def union_raster_pieces(request: Request):
        data = await edit_payload(request, 8 * 1024 * 1024)
        try:
            return await run_in_threadpool(raster_memory.merged_ring, data.get("rings"))
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/underlay/raster/prepare")
    async def underlay_prepare_tiff(request: Request):
        """Decode a raster into a bounded PNG preview without changing MAP."""
        if not state.metadata().get("loaded"):
            raise HTTPException(409,"Najpierw otwórz mapę MAP.")
        payload=await receive(request,MAX_RASTER_BYTES)
        try:
            image,meta=await run_in_threadpool(prepare_raster,payload)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
        digest = sha256(payload).hexdigest()
        raster_a1_cache.remember(digest, image, meta)
        return Response(image,media_type="image/png",headers={
            "X-Raster-Digest":digest,
            "X-Raster-EPSG":str(meta["epsg"] or ""),
            "X-Raster-Affine":json.dumps(meta["coefficients"]),
            "X-Raster-Width":str(meta["width"]),
            "X-Raster-Height":str(meta["height"]),
            "X-Raster-Source-Width":str(meta["sourceWidth"]),
            "X-Raster-Source-Height":str(meta["sourceHeight"]),
        })

    @app.post("/api/underlay/raster/a1")
    async def recognize_raster_numbers(request: Request):
        # OCR uses the prepared image only. A1 coordinates stay in PNG pixels
        # and are independent of map revisions, calibrations and worker sizes.
        map_key = raster_key(request)
        data = await edit_payload(request, 4096)
        try:
            digest = raster_digest(data.get("digest"))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        try:
            if not raster_a1_cache.contains(digest):
                def restore_preview():
                    raw = raster_memory.raster_bytes(map_key, digest)
                    return prepare_raster(raw) if raw is not None else None
                await run_in_threadpool(raster_a1_cache.restore, digest, restore_preview)
            result = await run_in_threadpool(raster_a1_cache.recognize, digest)
        except RasterPreviewMissing:
            # The frontend may re-upload its existing local File and retry
            # once only for this explicit code, never for a model failure or
            # the unrelated 404 returned when a document tab has been closed.
            return JSONResponse({"detail": "Dodaj raster ponownie, aby odczytać A1.",
                                 "code": "raster_preview_missing"}, status_code=404)
        except RasterOCRBusy as exc:
            return JSONResponse({"detail": str(exc), "code": "ocr_busy"},
                                status_code=503, headers={"Retry-After": "3"})
        except TimeoutError:
            return JSONResponse({"detail": "Odczyt A1 trwa zbyt długo. Numer możesz wpisać ręcznie.",
                                 "code": "ocr_timeout"}, status_code=504)
        except Exception:
            return JSONResponse({"detail": "Nie udało się odczytać A1 lokalnie. Numer możesz wpisać ręcznie.",
                                 "code": "ocr_unavailable"}, status_code=503)
        # Opening another MAP while the background job was running must not
        # deliver its result into a different document in the same tab.
        raster_key(request)
        return result

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

    @app.post("/api/underlay/raster/fit")
    async def fit_trace_outline(request: Request):
        payload = await edit_payload(request, 256 * 1024)
        try:
            return state.fit_trace_outline(payload.get("points"),
                document_token=payload.get("documentToken"), revision=payload.get("revision"),
                seed_points=payload.get("seedPoints", [payload["seedPoint"]] if "seedPoint" in payload else None),
                snap_distance=payload.get("snapDistance", 0), locked_points=payload.get("lockedPoints"))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, KeyError, TypeError) as exc:
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
        payload = await edit_payload(request, 32 * 1024)
        try:
            return state.move_vertex(
                fid, payload.get("index"), payload.get("x"), payload.get("y"),
                shared=payload.get("shared", False),
                snap_radius=payload.get("snapRadius", 0),follow=payload.get("follow"),
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

    @app.get("/api/cartography/outline")
    async def get_outline_settings(code: str):
        try:
            return state.outline_settings(code)
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/cartography/outline")
    async def set_outline_settings(request: Request):
        data=await edit_payload(request)
        try:
            return state.set_outline_settings(
                data.get("code"),data.get("stroke"),
                data.get("strokeWidth"),reset=data.get("reset",False),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/cartography/fills")
    async def get_fill_rules():
        return {"rules": state.fill_rules()}

    @app.post("/api/cartography/fills")
    async def set_fill_rules(request: Request):
        data = await edit_payload(request)
        try:
            return state.set_fill_rules_editable(
                data.get("rules"), document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409, str(exc)) from exc
        except (ValueError, TypeError) as exc:
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

    @app.post("/api/objects/dash")
    async def set_object_dash(request: Request):
        data=await edit_payload(request)
        try:
            return state.set_line_dash(
                data.get("uid"), data.get("dash"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/labels/auto-layout-5310")
    async def auto_layout_5310(request: Request):
        data=await edit_payload(request)
        try:
            return state.auto_layout_5310_labels(
                data.get("scope", "all"),
                data.get("scale", 5000),
                data.get("ids"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/labels/reset-leaders")
    async def reset_label_leaders(request: Request):
        data=await edit_payload(request)
        try:
            return state.reset_label_leaders(
                data.get("ids"),
                document_token=data.get("documentToken"),
                revision=data.get("revision"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/select/code")
    async def select_by_code(request: Request):
        data=await request.json()
        try:
            return state.select_by_code(data.get("code"), data.get("bbox"),
                                        data.get("limit", 5000))
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/labels/leader")
    async def set_label_leader(request: Request):
        data=await edit_payload(request)
        try:
            return state.set_label_leader(
                data.get("fid"),data.get("slot"),data.get("enabled"),
                data.get("anchor"),data.get("preferLeft"),
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

    @app.post("/api/sheet-items")
    async def set_sheet_items(request: Request):
        data=await edit_payload(request,512*1024)
        try:
            return state.set_sheet_items(
                data.get("items"),
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
            if state.map_epsg:
                from geostudio.coordinates import output_prj_text
                archive.writestr(name[:-4]+".prj", output_prj_text(state.map_epsg))
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


    @app.post("/api/export/tiles/start")
    async def begin_large_raster_export(request: Request):
        """Start a temporary disk-backed ZIP, bound to this exact MAP revision."""
        try:
            data=json.loads(await receive(request,64*1024))
            if not isinstance(data,dict):
                raise ValueError("Nieprawidłowe opcje eksportu.")
            ticket=tiles.begin(
                data.get("documentToken"),data.get("revision"),
                data.get("filename"),data.get("format"),
                data.get("columns"),data.get("rows"),data.get("manifest",""))
            return {"ticket":ticket}
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/export/tiles/{ticket}/part/{index}")
    async def add_large_raster_tile(ticket: str,index: int,request: Request):
        """One bounded browser-rendered tile, not a giant Canvas bitmap."""
        data=await receive(request,MAX_TILE_BYTES)
        try:
            tiles.add(ticket,index,data)
            return {"index":index,"stored":True}
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/export/tiles/{ticket}/finish")
    async def finish_large_raster_export(ticket: str):
        try:
            return tiles.finish(ticket)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/export/tiles/{ticket}/download")
    async def download_large_raster_export(ticket: str):
        """Browser fallback; FileResponse streams the archive from disk."""
        try:
            filename,path=tiles.archive(ticket)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
        return FileResponse(path,media_type="application/zip",
            filename=filename)

    @app.post("/api/export/mosaic/start")
    async def begin_single_tiff(request: Request):
        """Prepare one huge TIFF file without using a huge browser canvas."""
        try:
            data=json.loads(await receive(request,64*1024))
            if not isinstance(data,dict):
                raise ValueError("Nieprawidłowe parametry TIFF.")
            ticket=tiles.begin_mosaic(
                data.get("documentToken"),data.get("revision"),
                data.get("filename"),data.get("width"),data.get("height"),
                data.get("dpi"),data.get("tileWidth"),data.get("tileHeight"),data.get("format","tiff"))
            return {"ticket":ticket}
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/export/mosaic/{ticket}/part/{index}")
    async def add_single_tiff_part(ticket: str, index: int, request: Request):
        try:
            data=await receive(request,MAX_TILE_BYTES)
            await run_in_threadpool(tiles.add_mosaic,
                                    ticket,index,data)
            return {"index":index,"stored":True}
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/export/mosaic/{ticket}/finish")
    async def complete_single_tiff(ticket: str):
        try:
            return await run_in_threadpool(tiles.finish_mosaic,ticket)
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.get("/api/export/mosaic/{ticket}/download")
    async def download_single_tiff(ticket: str):
        """Stream a single TIFF/BigTIFF file from temporary disk."""
        try:
            filename,path=tiles.archive(ticket)
            if not filename.endswith((".tif",".jpg",".png")):
                raise ValueError("Wybrany eksport nie jest obrazem TIFF.")
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except LookupError as exc:
            raise HTTPException(404,str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400,str(exc)) from exc
        return FileResponse(path,media_type={".jpg":"image/jpeg",".png":"image/png",".tif":"image/tiff"}[path.suffix],filename=filename)

    @app.post("/api/export/buffer")
    async def save_generated_export_buffer(request: Request):
        try:
            data=await receive(request,120*1024*1024)
            name=unquote(request.headers.get("x-export-name",""))
            extension=request.headers.get("x-export-format","").lower()
            document_token=request.headers.get("x-document-token","")
            revision=int(request.headers.get("x-document-revision","-1"))
            ticket=state.store_generated_export(
                document_token,revision,name,extension,data)
            return {"ticket":ticket}
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc

    @app.post("/api/export/pdf")
    async def download_vector_pdf(request: Request):
        """True vector A0-A4 PDF; user-authored legend/frame/table in JSON."""
        raw=await receive(request,2*1024*1024)
        try:
            payload=json.loads(raw)
            if not isinstance(payload,dict):
                raise ValueError("Nieprawidłowe parametry PDF.")
            filename,pdf=await run_in_threadpool(
                state.export_vector_pdf,payload.get("documentToken"),
                payload.get("options"))
        except RuntimeError as exc:
            raise HTTPException(409,str(exc)) from exc
        except (ValueError,TypeError) as exc:
            raise HTTPException(400,str(exc)) from exc
        return Response(pdf,media_type="application/pdf",
            headers={"Content-Disposition":("attachment; filename=GeoStudio2_arkusz.pdf; "+
                "filename*=UTF-8''"+quote(filename,safe=""))})

    @app.get("/api/export/dxf")
    async def download_dxf(documentToken: str, bounds: str | None = None):
        try:
            region=json.loads(bounds) if bounds is not None else None
            name, content = state.export_dxf(documentToken, bounds=region)
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

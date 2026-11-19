"""Local-only FastAPI service for GeoStudio 2.0 preview.

No filesystem paths are accepted over HTTP. The user selects .MAP files in the
browser and sends their bytes; the verified parser reads them in memory only.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import unquote, quote
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

    @app.get("/api/viewport")
    async def viewport(xmin: float, ymin: float, xmax: float, ymax: float,
                       limit: int = MAX_RENDER_FEATURES):
        try:
            return state.viewport((xmin, ymin, xmax, ymax), limit)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/edit/status")
    async def edit_status():
        return state.editing_status()

    async def edit_payload(request: Request) -> dict:
        body = await receive(request, 8 * 1024)
        try:
            payload = __import__("json").loads(body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Nieprawidłowe dane edycji JSON.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(400, "Oczekiwano obiektu JSON.")
        return payload

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

    @app.get("/api/export/map")
    async def download_map_copy(documentToken: str):
        try:
            filename, content = state.export_copy(documentToken)
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

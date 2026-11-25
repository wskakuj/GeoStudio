"""Stage 12B raster helpers. Image pixels are never written into the MAP.

GEO-MAP coordinates: X=northing, Y=easting. Browser image pixels:
u grows right, v grows down. The affine coefficients always map
(u,v) -> (X northing, Y easting), the same convention as fit_affine().
"""
from __future__ import annotations

from io import BytesIO
from math import ceil, floor, isfinite, nextafter, sqrt
from threading import Lock
from typing import Any

from geostudio.raster_georef import GroundControlPoint, fit_affine

MAX_RASTER_BYTES = 48 * 1024 * 1024
# Preview tiles may be kept entirely in browser memory. Source rasters can
# exceed this cap, but an image preview must remain reasonably small.
MAX_SOURCE_PIXELS = 80_000_000
MAX_RASTER_PIXELS = 14_000_000
MAX_ALPHA_PREVIEW_PIXELS = 10_000_000
MAX_PREVIEW_EDGE = 8192  # Typical WebView2/GPU texture-safe maximum.
PDF_SOURCE_DPI = 300
# PDFium is not thread safe, even when concurrent requests open different files.
_PDF_LOCK = Lock()


def parse_world_text(text: str) -> tuple[float, float, float, float, float, float]:
    """ESRI A,D,B,E,C,F (east/north) -> GeoStudio affine X/Y at pixel CORNERS.

    Standard world file C,F refer to the centre of the upper-left pixel.
    Internal Canvas coordinates use pixel corners; adjust by half a pixel.
    """
    values = text.lstrip("\ufeff").splitlines()
    if len(values) != 6:
        raise ValueError("Plik world wymaga dokładnie sześciu liczb.")
    try:
        A, D, B, E, C, F = (float(z.strip()) for z in values)
    except ValueError as exc:
        raise ValueError("Plik world zawiera nieprawidłowe współczynniki.") from exc
    if not all(isfinite(x) for x in (A, B, C, D, E, F)):
        raise ValueError("Współczynniki pliku world muszą być skończone.")
    if abs(A * E - B * D) < 1e-12:
        raise ValueError("Transformacja pliku world jest osobliwa.")
    return (D, E, F - (D + E) / 2,
            A, B, C - (A + B) / 2)


def fit_gcp_payload(items: Any) -> dict:
    if not isinstance(items, list) or not 3 <= len(items) <= 60:
        raise ValueError("Potrzeba od 3 do 60 par punktów kontrolnych GCP.")
    points = []
    for row in items:
        if not isinstance(row, dict) or set(row) != {"u", "v", "x", "y"}:
            raise ValueError("Każdy GCP wymaga pól u, v, x, y.")
        try:
            numbers = [float(row[name]) for name in ("u", "v", "x", "y")]
        except (ValueError, TypeError) as exc:
            raise ValueError("GCP zawiera nieprawidłowe liczby.") from exc
        if not all(isfinite(n) for n in numbers):
            raise ValueError("Współrzędne GCP muszą być skończone.")
        points.append(GroundControlPoint(*numbers))
    fitted = fit_affine(points)
    return {"coefficients": list(fitted.coefficients),
            "rmse": fitted.rmse,
            "residuals": list(fitted.residuals),
            "count": len(points)}


def _epsg_from_tags(tags) -> int | None:
    # GeoKeyDirectoryTag: (version, revision, minor, count, [4-word keys]).
    keys = tags.get(34735)
    if keys and len(keys) >= 4:
        n = min(int(keys[3]), 4096)
        for i in range(n):
            offset = 4 + 4 * i
            if offset + 4 > len(keys):
                break
            key, location, count, value = (int(x) for x in keys[offset:offset+4])
            if key == 3072 and location == 0 and count == 1:
                return value
    return None


def _geo_transform(tags) -> tuple[float, ...] | None:
    # Reject PixelIsPoint unless properly shifted. We must not silently
    # position its centre control point at the corner of the pixel.
    keys = tags.get(34735) or ()
    if len(keys) >= 4:
        for i in range(min(int(keys[3]), 4096)):
            k = 4 + 4 * i
            if k + 4 <= len(keys) and tuple(keys[k:k+4]) == (1025, 0, 1, 2):
                raise ValueError("GeoTIFF PixelIsPoint wymaga innej korekty piksela.")
    matrix = tags.get(34264)
    if matrix:
        if len(matrix) != 16:
            raise ValueError("Nieprawidłowa macierz GeoTIFF.")
        vals = tuple(float(x) for x in matrix)
        # TIFF ground (east,north) -> GEO-MAP (north,east).
        coeff = (vals[4], vals[5], vals[7], vals[0], vals[1], vals[3])
    else:
        scale, tie = tags.get(33550), tags.get(33922)
        if not scale or not tie:
            return None
        if len(scale) < 2 or len(tie) < 6:
            raise ValueError("GeoTIFF zawiera niepełne znaczniki georeferencji.")
        sx, sy = float(scale[0]), float(scale[1])
        u0, v0 = float(tie[0]), float(tie[1])
        east0, north0 = float(tie[3]), float(tie[4])
        # TIFF Tiepoint includes the origin of the pixel AREA.
        coeff = (0., -sy, north0 + sy * v0,
                 sx, 0., east0 - sx * u0)
    if not all(isfinite(n) for n in coeff) or abs(coeff[0]*coeff[4]-coeff[1]*coeff[3]) < 1e-12:
        raise ValueError("Nieprawidłowa transformacja GeoTIFF.")
    return coeff


def _prepare_pdf(content: bytes) -> tuple[bytes, dict]:
    """Render one map sheet through the same image/georeferencing pipeline.

    PDF source coordinates use a stable 300 dpi grid. Render directly to the
    bounded preview size; never allocate the full-sized source bitmap first.
    Multi-page documents require an explicit page choice outside this importer.
    """
    import pypdfium2 as pdfium

    try:
        with _PDF_LOCK, pdfium.PdfDocument(content) as document:
            if len(document) != 1:
                raise ValueError("PDF zawiera kilka stron. Zapisz wybrany arkusz jako osobny PDF lub obraz.")
            page = document[0]
            try:
                page_width, page_height = page.get_size()
                if not all(isfinite(v) and v > 0 for v in (page_width, page_height)):
                    raise ValueError("PDF ma nieprawidłowy rozmiar strony.")
                source_width = ceil(page_width * PDF_SOURCE_DPI / 72)
                source_height = ceil(page_height * PDF_SOURCE_DPI / 72)
                pixels = source_width * source_height
                if pixels > MAX_SOURCE_PIXELS:
                    raise ValueError("Raster PDF przekracza limit 80 mln pikseli przy 300 dpi.")
                factor = min(1., sqrt(MAX_RASTER_PIXELS / pixels),
                             MAX_PREVIEW_EDGE / max(source_width, source_height))
                target_width = max(1, floor(source_width * factor))
                target_height = max(1, floor(source_height * factor))
                # Avoid ceil(250.00000000000003) inside PDFium adding a
                # spurious row and forcing a second, aspect-changing resize.
                scale = nextafter(min(target_width / page_width,
                                      target_height / page_height), 0.)
                bitmap = page.render(scale=scale, rev_byteorder=True)
                try:
                    rendered = bitmap.to_pil().convert("RGB")
                    # PDFium rounds raster dimensions upwards. Enforce the
                    # same hard pixel/edge limits as image previews.
                    rendered.thumbnail((target_width, target_height))
                    output = BytesIO()
                    rendered.save(output, format="PNG", compress_level=5)
                    result = output.getvalue()
                    if len(result) > MAX_RASTER_BYTES:
                        raise ValueError("Podgląd PDF jest zbyt duży.")
                    return result, {
                        "width": rendered.width, "height": rendered.height,
                        "sourceWidth": source_width, "sourceHeight": source_height,
                        "epsg": None, "coefficients": None,
                    }
                finally:
                    bitmap.close()
            finally:
                page.close()
    except pdfium.PdfiumError as exc:
        raise ValueError("Nie można odczytać PDF. Sprawdź, czy plik nie jest uszkodzony lub zabezpieczony hasłem.") from exc


def prepare_raster(content: bytes, *, tiff_only: bool = False) -> tuple[bytes, dict]:
    """Prepare a browser-safe preview and keep original pixel coordinates.

    Large rasters are downsampled solely for display. The original image
    dimensions and (when present) GeoTIFF affine are returned separately.
    Georeferencing must be composed with the preview-to-source pixel ratio
    before drawing on the Canvas. User GCPs remain in source pixels.
    """
    if not content or len(content) > MAX_RASTER_BYTES:
        raise ValueError("Raster jest pusty lub przekracza limit 48 MB pliku.")
    if not tiff_only and content.lstrip().startswith(b"%PDF-"):
        return _prepare_pdf(content)
    try:
        from PIL import Image
        with Image.open(BytesIO(content)) as image:
            if tiff_only and image.format != "TIFF":
                raise ValueError("Przesłano plik inny niż TIFF.")
            if image.format not in ("TIFF", "PNG", "JPEG", "WEBP"):
                raise ValueError("Obsługiwane rastry: TIFF, PNG, JPG, WebP i jednostronicowy PDF.")
            source_width, source_height = image.size
            pixels = source_width * source_height
            if source_width < 1 or source_height < 1 or pixels > MAX_SOURCE_PIXELS:
                raise ValueError(
                    "Raster przekracza bezpieczny limit 80 mln pikseli źródła.")
            tags = image.tag_v2 if image.format == "TIFF" else {}
            epsg = _epsg_from_tags(tags)
            transform = _geo_transform(tags)
            if epsg and epsg not in (2180, 2176, 2177, 2178, 2179):
                raise ValueError("GeoTIFF używa nieobsługiwanego EPSG: " + str(epsg))
            has_alpha = "A" in image.getbands() or "transparency" in image.info
            max_pixels = MAX_ALPHA_PREVIEW_PIXELS if has_alpha else MAX_RASTER_PIXELS
            factor = min(1., sqrt(max_pixels / pixels),
                         MAX_PREVIEW_EDGE / max(source_width, source_height))
            if factor < 1.:
                width = max(1, int(source_width * factor))
                height = max(1, int(source_height * factor))
                # JPEG's built-in decoder can downsample before allocating
                # the full decoded source; other formats use thumbnail.
                if image.format == "JPEG":
                    image.draft("RGB", (width, height))
                image.thumbnail((width, height), Image.Resampling.LANCZOS)
            rendered = image.convert("RGBA" if has_alpha else "RGB")
            output = BytesIO()
            rendered.save(output, format="PNG", compress_level=5)
            result = output.getvalue()
            if len(result) > MAX_RASTER_BYTES:
                raise ValueError(
                    "Podgląd jest zbyt duży; użyj mniej szczegółowego rastra.")
            return result, {
                "width": rendered.width,
                "height": rendered.height,
                "sourceWidth": source_width,
                "sourceHeight": source_height,
                "epsg": epsg,
                "coefficients": transform,
            }
    except (OSError, Image.DecompressionBombError) as exc:
        raise ValueError("Nie można bezpiecznie odczytać rastra.") from exc


def prepare_geotiff(content: bytes) -> tuple[bytes, dict]:
    """Compatibility entry point for callers requiring TIFF input."""
    return prepare_raster(content, tiff_only=True)

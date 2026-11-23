"""Sklejanie kafelków: każdy fragment musi trafić na swoje miejsce.

Test koduje położenie w kolorze: każdy kafelek odpowiada kolorowym rogiem,
więc po sklejeniu sprawdzamy, czy góra/dół i lewo/prawo się zgadzają.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image

from geostudio.web_app import underlay_wms


def _tile(colour):
    buffer = BytesIO()
    Image.new("RGB", (10, 10), colour).save(buffer, format="PNG")
    return buffer.getvalue()


def test_stitch_places_tiles_by_compass():
    # parts: 0 = N-low/E-low, 1 = N-high/E-low, 2 = N-low/E-high, 3 = N-high/E-high
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
    tiles = [_tile(colour) for colour in colours]
    data = underlay_wms._stitch(tiles, 20, 20, 10, 10)
    image = Image.open(BytesIO(data)).convert("RGB")

    def near(pixel, expected, tol=40):
        return all(abs(a - b) <= tol for a, b in zip(pixel, expected))

    # Lewy górny = N-high/E-low (zielony), prawy górny = N-high/E-high (żółty)
    assert near(image.getpixel((5, 5)), colours[1])
    assert near(image.getpixel((15, 5)), colours[3])
    # Lewy dolny = N-low/E-low (czerwony), prawy dolny = N-low/E-high (niebieski)
    assert near(image.getpixel((5, 15)), colours[0])
    assert near(image.getpixel((15, 15)), colours[2])


def test_stitch_keeps_requested_size():
    tiles = [_tile((10, 20, 30)) for _ in range(4)]
    data = underlay_wms._stitch(tiles, 33, 21, 16, 10)
    assert Image.open(BytesIO(data)).size == (33, 21)

"""Sprawdzanie i instalowanie aktualizacji z GitHuba (wzorzec jak w FORESTLY).

Działa tylko w spakowanym programie (``sys.frozen``): pobiera instalator
Inno Setup z najnowszego wydania i uruchamia go w trybie cichym, po czym
zamyka bieżącą instancję. Wersja deweloperska nic nie podmienia.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_USER = "wskakuj"
GITHUB_REPO = "GeoStudio"
USER_AGENT = "GeoStudio-Updater"
API_LATEST = f"https://api.github.com/repos/{GITHUB_USER}/{GITHUB_REPO}/releases/latest"
ASSET_PATTERN = re.compile(r"\.exe$", re.IGNORECASE)


_VERSION_PREFIX = re.compile(r"^\s*v?(\d+(?:\.\d+)*)")


def parse_version(value: str) -> tuple[int, ...]:
    """'v2.0.10' -> (2, 0, 10); bierze tylko wiodący numer wersji.

    Tag bez numeru na początku (np. 'preview.8') nie jest wersją i nie
    może zostać uznany za nowszy od 2.0.0.
    """
    match = _VERSION_PREFIX.match(str(value or ""))
    if not match:
        return (0,)
    return tuple(int(part) for part in match.group(1).split("."))


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


# Musi być zgodna z pyproject.toml; używana, gdy metadane pakietu nie są
# spakowane (PyInstaller kopiuje je przez --copy-metadata geostudio-pl).
FALLBACK_VERSION = "2.0.3"


def current_version() -> str:
    """Wersja z metadanych pakietu, z bezpiecznym fallbackiem."""
    try:
        from importlib.metadata import version
        return version("geostudio-pl")
    except Exception:
        return FALLBACK_VERSION


def fetch_latest_release(timeout: float = 6.0) -> dict:
    """Zwraca dict z API GitHuba (tag_name, body, assets, html_url)."""
    request = urllib.request.Request(API_LATEST, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8"))
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise ValueError("Odpowiedź GitHuba bez numeru wersji.")
    return data


def installer_asset(release: dict) -> dict | None:
    """Pierwszy załącznik .exe (instalator Inno Setup)."""
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        if ASSET_PATTERN.search(name):
            return asset
    return None


def check_for_update(current: str | None = None, timeout: float = 6.0) -> dict | None:
    """None = brak nowszej wersji albo błąd sieci; dict = dostępna aktualizacja."""
    current = current or current_version()
    try:
        release = fetch_latest_release(timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError, json.JSONDecodeError):
        return None
    latest = str(release.get("tag_name") or "")
    if not latest or not is_newer(latest, current):
        return None
    asset = installer_asset(release)
    return {
        "version": latest,
        "current": current,
        "notes": str(release.get("body") or "")[:4000],
        "page": str(release.get("html_url") or ""),
        "assetName": str(asset.get("name")) if asset else "",
        "assetUrl": str(asset.get("browser_download_url")) if asset else "",
        "size": int(asset.get("size") or 0) if asset else 0,
    }


def download_installer(url: str, target: Path | None = None,
                       timeout: float = 120.0, progress=None,
                       show_window: bool = False) -> Path:
    """Pobiera instalator do pliku tymczasowego; progress(done, total).

    ``show_window`` otwiera okno postępu (Tk) na czas pobierania — bez niego
    użytkownik widzi tylko ciszę do chwili startu instalatora.
    """
    if not url:
        raise ValueError("Brak adresu instalatora w wydaniu.")
    target = target or Path(tempfile.gettempdir()) / "GeoStudio2-Setup-latest.exe"
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response, \
            open(target, "wb") as out:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(262144)
            if not chunk:
                break
            out.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if target.stat().st_size <= 0:
        raise ValueError("Pobrany instalator jest pusty.")
    return target


def download_with_progress(url: str, version: str = "") -> Path:
    """Pobiera instalator pokazując okno postępu (używane przy aktualizacji)."""
    import tkinter as tk
    from tkinter import ttk
    root = tk.Tk()
    root.title("GeoStudio — aktualizacja")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    tk.Label(root, text=("Pobieranie wersji " + (version or "")).strip(),
             font=("Segoe UI", 11, "bold"), anchor="w", padx=16, pady=(14, 4)
             ).pack(fill="x")
    label = tk.Label(root, text="Łączenie z GitHub…", anchor="w", padx=16)
    label.pack(fill="x")
    bar = ttk.Progressbar(root, length=360, mode="determinate", maximum=100)
    bar.pack(padx=16, pady=12)
    root.update_idletasks()
    width = root.winfo_reqwidth()
    root.geometry(f"{max(width, 400)}x{root.winfo_reqheight()}+"
                  f"{(root.winfo_screenwidth()-400)//2}+"
                  f"{(root.winfo_screenheight()-200)//2}")

    def on_progress(done: int, total: int) -> None:
        if total:
            bar["value"] = min(100, done * 100 / total)
            label.config(text=f"Pobrano {done/1048576:.1f} z {total/1048576:.1f} MB")
        else:
            label.config(text=f"Pobrano {done/1048576:.1f} MB")
        root.update()

    try:
        path = download_installer(url, progress=on_progress)
        bar["value"] = 100
        label.config(text="Pobrano — uruchamiam instalator…")
        root.update()
        return path
    finally:
        root.destroy()


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def launch_installer(installer: Path) -> None:
    """Uruchamia instalator cicho i zamyka bieżący program."""
    if not is_frozen():
        raise RuntimeError("Aktualizacja działa tylko w spakowanym programie.")
    installer = Path(installer)
    if not installer.is_file():
        raise FileNotFoundError(str(installer))
    # Inno Setup: /SILENT = bez pytań, ale z paskiem; /CLOSEAPPLICATIONS
    # zamyka działającą instancję; /NORESTART zostawia restart użytkownikowi.
    subprocess.Popen(
        [str(installer), "/SILENT", "/CLOSEAPPLICATIONS", "/NORESTART"],
        close_fds=True,
    )
    os._exit(0)

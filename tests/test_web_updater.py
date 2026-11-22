"""Aktualizator: porównanie wersji i decyzja o aktualizacji (bez sieci)."""
from __future__ import annotations

import json

import pytest

from geostudio.web_app import updater


@pytest.mark.parametrize("latest,current,expected", [
    ("v2.0.1", "2.0.0", True),
    ("v2.0.0", "2.0.0", False),
    ("v1.9.9", "2.0.0", False),
    ("2.0.10", "2.0.9", True),
    ("v2.1", "2.0.9", True),
    ("preview.8", "2.0.0", False),
    ("", "2.0.0", False),
])
def test_is_newer(latest, current, expected):
    assert updater.is_newer(latest, current) is expected


def test_parse_version_ignores_prefixes():
    assert updater.parse_version("v2.0.10-preview") == (2, 0, 10)
    assert updater.parse_version(None) == (0,)


def _release(tag, assets):
    return {"tag_name": tag, "body": "nota", "html_url": "https://example/rel",
            "assets": assets}


def test_check_for_update_returns_installer(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest_release",
                        lambda timeout=6.0: _release("v2.0.1", [
                            {"name": "notes.txt", "browser_download_url": "u0", "size": 1},
                            {"name": "GeoStudio2-Setup-2.0.1-x64.exe",
                             "browser_download_url": "u1", "size": 42},
                        ]))
    info = updater.check_for_update(current="2.0.0")
    assert info is not None
    assert info["version"] == "v2.0.1"
    assert info["assetName"].endswith(".exe")
    assert info["assetUrl"] == "u1"
    assert info["size"] == 42


def test_check_for_update_none_when_current(monkeypatch):
    monkeypatch.setattr(updater, "fetch_latest_release",
                        lambda timeout=6.0: _release("v2.0.0", []))
    assert updater.check_for_update(current="2.0.0") is None


def test_check_for_update_swallows_network_errors(monkeypatch):
    def boom(timeout=6.0):
        raise OSError("brak sieci")
    monkeypatch.setattr(updater, "fetch_latest_release", boom)
    assert updater.check_for_update(current="2.0.0") is None


def test_download_installer_writes_file(tmp_path, monkeypatch):
    class FakeResponse:
        headers = {"Content-Length": "5"}
        def __init__(self): self._sent = False
        def read(self, n):
            if self._sent: return b""
            self._sent = True
            return b"hello"
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(updater.urllib.request, "urlopen", lambda *a, **k: FakeResponse())
    seen = []
    target = updater.download_installer("http://example/setup.exe",
                                        target=tmp_path / "setup.exe",
                                        progress=lambda d, t: seen.append((d, t)))
    assert target.read_bytes() == b"hello"
    assert seen == [(5, 5)]


def test_launch_installer_refuses_outside_frozen(tmp_path, monkeypatch):
    monkeypatch.setattr(updater, "is_frozen", lambda: False)
    with pytest.raises(RuntimeError):
        updater.launch_installer(tmp_path / "x.exe")


def test_update_script_shows_a_progress_window(tmp_path):
    script = updater.build_update_script(
        "https://example.com/setup.exe", tmp_path / "setup.exe", "v2.0.5")
    # Okno WinForms z paskiem postępu i licznikiem MB.
    assert "System.Windows.Forms.Form" in script
    assert "ProgressBar" in script
    # Pobieranie jest synchroniczne: czytamy strumień i wołamy DoEvents,
    # zamiast zdarzeń WebClienta (ich $script:done żyje w innym runspace).
    assert "GetResponseStream" in script
    assert "DoEvents" in script
    assert "Pobrano" in script and "MB" in script
    assert "Unblock-File" in script
    # Adres i plik docelowy trafiają do skryptu jako literały PowerShell.
    assert "https://example.com/setup.exe" in script
    assert str(tmp_path / "setup.exe") in script
    # Po pobraniu uruchamia instalator cicho.
    assert "/SILENT" in script and "Start-Process" in script


def test_update_script_quotes_apostrophes(tmp_path):
    script = updater.build_update_script(
        "https://example.com/o'brien.exe", tmp_path / "x.exe", "v2")
    assert "o''brien.exe" in script


def test_start_update_launches_powershell(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(updater.subprocess, "Popen",
                        lambda args, **kwargs: calls.append(args))
    target = updater.start_update("https://example.com/setup.exe", "v2.0.5")
    assert target.name == "GeoStudio2-Setup-latest.exe"
    assert calls and calls[0][0] == "powershell"
    assert "-STA" in calls[0]
    assert "https://example.com/setup.exe" in calls[0][-1]


def test_update_script_relaunches_the_app_after_install(tmp_path):
    script = updater.build_update_script(
        "https://example.com/setup.exe", tmp_path / "setup.exe", "v2.0.9")
    # Instalator cicho, czekamy na koniec i uruchamiamy program.
    assert "WaitForExit()" in script
    assert "Programs" in script and "GeoStudio2.exe" in script
    assert "Start-Process -FilePath $exe" in script


def test_tabs_bridge_exposes_update_methods():
    """Pasek zakładek woła mostek bez document_id — metody muszą tam być."""
    from geostudio.web_app.documents import DocumentNativeBridge
    assert callable(getattr(DocumentNativeBridge, "check_update", None))
    assert callable(getattr(DocumentNativeBridge, "install_update", None))


def test_tabs_badge_waits_for_the_bridge():
    from pathlib import Path
    js = Path("geostudio/web_app/static/tabs.js").read_text(encoding="utf-8")
    assert "function waitForBridge(" in js
    assert "pywebview?.api" in js
    assert "Mostek aplikacji nie jest gotowy" in js


def test_update_script_finds_install_dir_in_registry(tmp_path):
    script = updater.build_update_script(
        "https://example.com/setup.exe", tmp_path / "setup.exe", "2.0.12")
    # Nie zgadujemy jednej ścieżki: rejestr, typowa lokalizacja, skan Programów.
    assert "CurrentVersion" in script and "InstallLocation" in script
    assert "Get-ChildItem" in script and "GeoStudio2.exe" in script


def test_update_dialog_is_compact(tmp_path):
    from pathlib import Path
    tabs = Path("geostudio/web_app/static/tabs.js").read_text(encoding="utf-8")
    css = Path("geostudio/web_app/static/tabs.css").read_text(encoding="utf-8")
    assert "function showUpdatePrompt(" in tabs
    # Okno aktualizacji nie może być systemowym confirmem.
    assert "showUpdatePrompt(info.current" in tabs
    assert "Pobrać i zainstalować teraz" not in tabs
    assert ".update-card" in css and ".update-actions" in css
    assert "Pobierz i zainstaluj" in tabs

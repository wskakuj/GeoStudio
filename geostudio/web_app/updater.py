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
FALLBACK_VERSION = "2.0.52"


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


def _ps_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


UPDATE_SCRIPT_TEMPLATE = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing

$form = New-Object System.Windows.Forms.Form
$form.Text = 'GeoStudio 2.0 - aktualizacja'
$form.ClientSize = New-Object System.Drawing.Size(480, 150)
$form.StartPosition = 'CenterScreen'
$form.TopMost = $true
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.MinimizeBox = $false

$title = New-Object System.Windows.Forms.Label
$title.Text = '__LABEL__'
$title.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$title.SetBounds(16, 14, 440, 22)
$form.Controls.Add($title)

$bar = New-Object System.Windows.Forms.ProgressBar
$bar.SetBounds(16, 44, 440, 22)
$bar.Minimum = 0
$bar.Maximum = 100
$form.Controls.Add($bar)

$status = New-Object System.Windows.Forms.Label
$status.Text = 'Laczenie z GitHub...'
$status.SetBounds(16, 74, 440, 20)
$form.Controls.Add($status)

$form.Show()
$form.Refresh()
[System.Windows.Forms.Application]::DoEvents()

$target = '__TARGET__'
$url = '__URL__'

function Fail($message) {
    $status.Text = 'Blad pobierania'
    $form.Refresh()
    [System.Windows.Forms.MessageBox]::Show($message, 'GeoStudio 2.0 - aktualizacja') | Out-Null
    $form.Close()
    exit 1
}

try {
    if (Test-Path $target) { Remove-Item $target -Force -ErrorAction SilentlyContinue }

    $request = [System.Net.HttpWebRequest]::Create($url)
    $request.UserAgent = 'GeoStudio-Updater'
    $request.AllowAutoRedirect = $true
    $request.Proxy = $null
    $request.Timeout = 30000
    $request.ReadWriteTimeout = 60000
    $response = $request.GetResponse()
    $total = $response.ContentLength
    $input = $response.GetResponseStream()
    $output = [System.IO.File]::Create($target)
    $buffer = New-Object byte[] 1048576
    $received = 0

    while (($read = $input.Read($buffer, 0, $buffer.Length)) -gt 0) {
        $output.Write($buffer, 0, $read)
        $received += $read
        if ($total -gt 0) {
            $value = [int](100 * $received / $total)
            if ($value -gt 100) { $value = 100 }
            $bar.Value = $value
            $status.Text = ('Pobrano {0:N1} z {1:N1} MB' -f ($received / 1MB), ($total / 1MB))
        } else {
            $status.Text = ('Pobrano {0:N1} MB' -f ($received / 1MB))
        }
        $form.Refresh()
        [System.Windows.Forms.Application]::DoEvents()
    }

    $output.Flush()
    $output.Close()
    $input.Close()
    $response.Close()

    if (-not (Test-Path $target) -or (Get-Item $target).Length -lt 1024) {
        Fail 'Pobrany plik jest pusty lub niekompletny.'
    }

    $bar.Value = 100
    $status.Text = 'Pobrano - instaluje...'
    $form.Refresh()
    [System.Windows.Forms.Application]::DoEvents()

    try { Unblock-File -Path $target -ErrorAction Stop } catch { }

    Start-Sleep -Milliseconds 600
    $form.Close()

    $installer = Start-Process -FilePath $target -ArgumentList '/SILENT', '/CLOSEAPPLICATIONS' -PassThru
    $installer.WaitForExit()

    # Sciezka instalacji bywa inna (u Ciebie np. D:\GeoStudio), wiec czytamy
    # rejestr: InstallLocation, DisplayIcon i UninstallString, a potem szukamy
    # po dyskach. Katalog z instalatora NIE jest wyznacznikiem.
    $exe = $null
    $appId = '{A755B3EB-320E-4139-8A44-FA5FB6912C9A}_is1'
    $roots = @(
        'HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall',
        'HKLM:\Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'
    )

    function From-Registry {
        foreach ($root in $roots) {
            $key = Join-Path $root $appId
            if (-not (Test-Path $key)) { continue }
            $entry = Get-ItemProperty $key -ErrorAction SilentlyContinue
            if (-not $entry) { continue }
            if ($entry.InstallLocation) {
                $candidate = Join-Path $entry.InstallLocation 'GeoStudio2.exe'
                if (Test-Path $candidate) { return $candidate }
            }
            if ($entry.DisplayIcon) {
                $icon = ($entry.DisplayIcon -split ',')[0].Trim('"', ' ')
                if ($icon -like '*GeoStudio2.exe' -and (Test-Path $icon)) { return $icon }
            }
            if ($entry.UninstallString) {
                $folder = Split-Path (($entry.UninstallString -replace '"', '').Trim()) -Parent
                if ($folder) {
                    $candidate = Join-Path $folder 'GeoStudio2.exe'
                    if (Test-Path $candidate) { return $candidate }
                }
            }
        }
        return $null
    }

    function From-Drives {
        # Tylko dyski lokalne — skan dysków sieciowych mógłby trwać minutami.
        $drives = [System.IO.DriveInfo]::GetDrives() |
            Where-Object { $_.DriveType -eq 'Fixed' -and $_.IsReady }
        foreach ($drive in $drives) {
            foreach ($name in @('GeoStudio', 'GeoStudio2', 'GeoStudio 2.0')) {
                $candidate = Join-Path $drive.Root $name
                $hit = Join-Path $candidate 'GeoStudio2.exe'
                if (Test-Path $hit) { return $hit }
            }
            $found = Get-ChildItem ($drive.Root + 'GeoStudio*') -Filter 'GeoStudio2.exe' `
                -Recurse -Depth 2 -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($found) { return $found.FullName }
        }
        return $null
    }

    for ($attempt = 0; $attempt -lt 12 -and -not $exe; $attempt++) {
        $exe = From-Registry
        if (-not $exe) { $exe = From-Drives }
        if (-not $exe) { Start-Sleep -Milliseconds 500 }
    }

    if ($exe) {
        Start-Process -FilePath $exe
    } else {
        Start-Process explorer.exe (Join-Path $env:LOCALAPPDATA 'Programs')
    }
} catch {
    Fail ('Nie udalo sie pobrac aktualizacji: ' + $_.Exception.Message)
}
"""


def build_update_script(url: str, target: Path, version: str = "") -> str:
    """Skrypt PowerShell z oknem postępu (WinForms), jak w FORESTLY.

    Szablon jest zwykłym stringiem (r-string), a podstawiamy tylko trzy
    wartości — dzięki temu nie ma walki z nawiasami i backslashami f-stringa.
    """
    label = ("Pobieranie wersji " + version).strip()
    return (UPDATE_SCRIPT_TEMPLATE
            .replace("__LABEL__", label.replace("'", "''"))
            .replace("__TARGET__", str(target).replace("'", "''"))
            .replace("__URL__", url.replace("'", "''")))


def start_update(url: str, version: str = "",
                 installer_name: str = "GeoStudio2-Setup-latest.exe") -> Path:
    """Uruchamia okno pobierania (PowerShell) i zwraca ścieżkę instalatora."""
    if not url:
        raise ValueError("Brak adresu instalatora w wydaniu.")
    target = Path(tempfile.gettempdir()) / installer_name
    script = build_update_script(url, target, version)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass",
         "-Command", script],
        close_fds=True, creationflags=creationflags,
    )
    return target


_PENDING_UPDATE: dict | None = None


def set_pending_update(info: dict | None) -> None:
    """Zapamiętuje wynik sprawdzenia z startu, żeby pokazać go w interfejsie."""
    global _PENDING_UPDATE
    _PENDING_UPDATE = dict(info) if info else None


def pending_update() -> dict | None:
    """Informacja o dostępnej aktualizacji znalezionej przy starcie."""
    if not _PENDING_UPDATE:
        return None
    return {"version": _PENDING_UPDATE.get("version", ""),
            "available": bool(_PENDING_UPDATE.get("assetUrl"))}


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

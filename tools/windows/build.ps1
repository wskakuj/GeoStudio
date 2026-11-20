# Build a self-contained Windows preview app. No administrator rights needed.
param([switch]$SkipInstaller)
$ErrorActionPreference = "Stop"
$Repo = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
Set-Location $Repo
Write-Host "Building GeoStudio 2.0 from $Repo"
python -m pip install -e ".[web]"
if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
python -m pip install "pyinstaller>=6.10,<7"
if ($LASTEXITCODE -ne 0) { throw "PyInstaller installation failed." }

$Args = @(
    "--noconfirm", "--clean", "--onedir", "--windowed",
    "--name", "GeoStudio2",
    "--collect-data", "geostudio.web_app",
    "--collect-submodules", "webview",
    "--hidden-import", "uvicorn.logging",
    "--hidden-import", "uvicorn.loops.auto",
    "--hidden-import", "uvicorn.protocols.http.auto",
    "--hidden-import", "uvicorn.protocols.websockets.auto",
    "--hidden-import", "uvicorn.lifespan.on",
    "--hidden-import", "shapely",
    "tools/windows/geostudio2_entry.py"
)
python -m PyInstaller @Args
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed." }

$Executable = Join-Path $Repo "dist/GeoStudio2/GeoStudio2.exe"
if (-not (Test-Path $Executable)) { throw "Missing packaged executable: $Executable" }
& $Executable --help | Out-Null
if ($LASTEXITCODE -ne 0) { throw "Packaged EXE failed smoke test: --help" }

if (-not $SkipInstaller) {
    $Iscc = Join-Path ([Environment]::GetFolderPath("ProgramFilesX86")) "Inno Setup 6/ISCC.exe"
    if (-not (Test-Path $Iscc)) {
        $Iscc = Join-Path $env:ProgramFiles "Inno Setup 6/ISCC.exe"
    }
    if (-not (Test-Path $Iscc)) {
        throw "Install Inno Setup 6 (https://jrsoftware.org/isinfo.php) to create installer, or use -SkipInstaller for portable EXE."
    }
    & $Iscc (Join-Path $Repo "tools/windows/geostudio2.iss")
    if ($LASTEXITCODE -ne 0) { throw "Inno Setup compilation failed." }
}
Write-Host "Built portable app in dist/GeoStudio2/"
if (-not $SkipInstaller) { Write-Host "Built installer in dist/installer/" }

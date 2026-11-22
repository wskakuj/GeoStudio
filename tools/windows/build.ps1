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
    # Force UTF-8 inside the frozen app: a cp1252 console cannot print the
    # Polish help text and used to abort the smoke test.
    "--python-option", "X utf8",
    # Without this a windowed crash opens a modal dialog and the process
    # never exits, so the CI step hangs until the job timeout.
    "--disable-windowed-traceback",
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

# Every packaged run is bounded: a hung EXE must fail the build, never eat the
# whole job timeout. Both streams are captured for the CI log.
function Invoke-PackagedExe {
    param([string]$Exe, [string[]]$Arguments, [int]$TimeoutSeconds = 180)
    $stamp = [guid]::NewGuid().ToString("N")
    $out = Join-Path $env:TEMP "geostudio-$stamp.out.txt"
    $err = Join-Path $env:TEMP "geostudio-$stamp.err.txt"
    $process = Start-Process -FilePath $Exe -ArgumentList $Arguments `
        -RedirectStandardOutput $out -RedirectStandardError $err `
        -WindowStyle Hidden -PassThru
    try {
        if (-not $process.WaitForExit($TimeoutSeconds * 1000)) {
            & taskkill.exe /PID $process.Id /T /F | Out-Null
            throw ("Packaged EXE timed out after $TimeoutSeconds s: " + ($Arguments -join " "))
        }
        $process.WaitForExit()
        foreach ($log in @($out, $err)) {
            if (Test-Path $log) { Get-Content -Encoding UTF8 $log | Where-Object { $_ } | Write-Host }
        }
        return $process.ExitCode
    } finally {
        $process.Dispose()
        foreach ($log in @($out, $err)) {
            if (Test-Path $log) { Remove-Item $log -Force -ErrorAction SilentlyContinue }
        }
    }
}

$helpCode = Invoke-PackagedExe -Exe $Executable -Arguments @("--help")
if ($helpCode -ne 0) { throw "Packaged EXE failed smoke test: --help (exit $helpCode)" }
# --help prints to a redirected stdout, so it never exercises the no-console
# path a double-clicked --windowed EXE hits. --selftest starts the server with
# sys.stdout/stderr set to None and expects HTTP 200.
$selfCode = Invoke-PackagedExe -Exe $Executable -Arguments @("--selftest") -TimeoutSeconds 300
if ($selfCode -ne 0) { throw "Packaged EXE failed headless self-test (exit $selfCode)" }

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

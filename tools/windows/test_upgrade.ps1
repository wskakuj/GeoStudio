# Run only on a disposable Windows CI runner. No production user or map data.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)
$ErrorActionPreference = "Stop"
if ($env:GITHUB_ACTIONS -cne "true" -or $env:RUNNER_ENVIRONMENT -cne "github-hosted") {
    throw "Upgrade test is restricted to disposable GitHub-hosted CI."
}
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$installer = & "$PSScriptRoot/check_installer.ps1" -Version $Version
$expected = (Get-Content (Join-Path $root "dist/installer/SHA256SUMS.txt") -Raw).Trim().Split(" ")[0]
if ((Get-FileHash -Algorithm SHA256 $installer.FullName).Hash -ine $expected) {
    throw "Candidate checksum mismatch."
}
$registry = "HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\{A755B3EB-320E-4139-8A44-FA5FB6912C9A}_is1"
if (Test-Path -LiteralPath $registry) { throw "Upgrade runner is not clean." }
$scratch = Join-Path $env:RUNNER_TEMP ("geostudio-upgrade-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $scratch | Out-Null
$folder = Join-Path $scratch "existing installation"
$old = Join-Path $scratch "GeoStudio2-Setup-2.0.108-x64.exe"
# The exact already published 108 asset; check its independently recorded digest.
Invoke-WebRequest -Uri "https://github.com/wskakuj/GeoStudio/releases/download/v2.0.108/GeoStudio2-Setup-2.0.108-x64.exe" -OutFile $old -TimeoutSec 180
if ((Get-FileHash -Algorithm SHA256 $old).Hash -ine "6b00e79780735df19f99189d428f987ba580533647625b3b8d39e2d85e4871d1") {
    throw "The published 108 installer changed; refusing to execute."
}
function Invoke-CheckedProcess {
    param([string]$Path, [string[]]$Arguments, [int]$TimeoutSeconds = 180)
    $proc = Start-Process -FilePath $Path -ArgumentList $Arguments -PassThru
    try {
        if (-not $proc.WaitForExit($TimeoutSeconds * 1000)) {
            & taskkill.exe /PID $proc.Id /T /F | Out-Null
            throw "Timed out: $Path"
        }
        if ($proc.ExitCode -ne 0) { throw "Process failed: $Path (exit $($proc.ExitCode))" }
    } finally { $proc.Dispose() }
}
function Assert-Installation([string]$ExpectedVersion) {
    $record = Get-ItemProperty -LiteralPath $registry
    if ($record.DisplayVersion -cne $ExpectedVersion) {
        throw "Installed version does not match $ExpectedVersion."
    }
    if ($record.InstallLocation.TrimEnd('\') -ine $folder.TrimEnd('\')) {
        throw "Installer did not preserve the existing directory."
    }
    if (-not (Test-Path (Join-Path $folder "GeoStudio2.exe"))) {
        throw "Installed EXE missing."
    }
}
$silent = @("/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/CLOSEAPPLICATIONS")
$dirArg = '/DIR="' + $folder + '"'
$oldLog = '/LOG="' + (Join-Path $scratch "old-install.log") + '"'
$newLog = '/LOG="' + (Join-Path $scratch "upgrade.log") + '"'
Invoke-CheckedProcess -Path $old -Arguments ($silent + @($dirArg, $oldLog))
Assert-Installation "2.0.108"
# A synthetic untracked work file must survive upgrading the existing folder.
$sentinel = Join-Path $folder "ci-preserve-user-file.txt"
Set-Content -LiteralPath $sentinel -Encoding ascii "geostudio-upgrade-test"
# Deliberately omit /DIR for the new installer, just as the old updater does.
Invoke-CheckedProcess -Path $installer.FullName -Arguments ($silent + @($newLog))
Assert-Installation $Version
if ((Get-Content -LiteralPath $sentinel -Raw).Trim() -cne "geostudio-upgrade-test") {
    throw "An unrelated file was not preserved."
}
$exe = Join-Path $folder "GeoStudio2.exe"
Invoke-CheckedProcess -Path $exe -Arguments @("--selftest-release", $Version)
Invoke-CheckedProcess -Path $exe -Arguments @("--selftest") -TimeoutSeconds 300
Write-Host "Verified in-place upgrade from 2.0.108 to $Version, with configured login, invitations and offline support."

# Validate the actual Inno Setup binary using the numeric PE version resource.
# FileVersion is a display string and Inno Setup may pad it with spaces.
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^\d+\.\d+\.\d+$')]
    [string]$Version
)
$ErrorActionPreference = "Stop"
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$expected = "GeoStudio2-Setup-$Version-x64.exe"
$installers = @(Get-ChildItem -Path (Join-Path $root "dist/installer/*.exe") -File)
if ($installers.Count -ne 1 -or $installers[0].Name -cne $expected) {
    throw "Expected exactly one installer named $expected."
}
$installer = $installers[0]
if ($installer.Length -lt 1000000) {
    throw "Installer is unexpectedly small: $($installer.Name)"
}
$info = $installer.VersionInfo
$actual = [System.Version]::new(
    $info.FileMajorPart, $info.FileMinorPart, $info.FileBuildPart, $info.FilePrivatePart
)
$expectedVersion = [System.Version]::Parse("$Version.0")
if ($actual -ne $expectedVersion) {
    throw "Installer numeric file version $actual does not match $expectedVersion."
}
Write-Host "Validated installer: $($installer.FullName) (PE version $actual)"
$installer

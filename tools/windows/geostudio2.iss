#define MyAppName "GeoStudio 2.0"
#define MyAppVersion "2.0.22"
#define MyAppExe "GeoStudio2.exe"

[Setup]
SetupIconFile=..\..\geostudio.ico
AppId={{A755B3EB-320E-4139-8A44-FA5FB6912C9A}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=GeoStudio
DefaultDirName={localappdata}\Programs\GeoStudio2
DefaultGroupName=GeoStudio 2.0
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\dist\installer
OutputBaseFilename=GeoStudio2-Setup-2.0.22-x64
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\{#MyAppExe}
SetupLogging=yes
CloseApplications=yes
RestartApplications=no
VersionInfoVersion=0.14.0.0

[Files]
Source: "..\..\dist\GeoStudio2\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GeoStudio 2.0 (Preview)"; Filename: "{app}\{#MyAppExe}"
Name: "{autodesktop}\GeoStudio 2.0"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "Utwórz skrót na pulpicie"; Flags: unchecked

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "Uruchom GeoStudio 2.0"; Flags: nowait postinstall skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  Result := True;
  if not IsWin64 then begin
    MsgBox('GeoStudio 2.0 wymaga 64-bitowego systemu Windows.', mbCriticalError, MB_OK);
    Result := False;
  end;
end;

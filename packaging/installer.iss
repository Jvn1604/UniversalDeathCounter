; Inno Setup script for DePhantom Universal Death Counter (DUDC).
;
; Produces a proper Windows installer (Setup.exe) that installs the app,
; creates Start Menu / optional Desktop shortcuts, and registers an
; uninstaller — i.e. exactly the "download and install" experience users
; expect, rather than a bare standalone .exe.
;
; Build locally (Windows, with Inno Setup 6 installed):
;   1. Build the executable first:  pyinstaller packaging/UniversalDeathCounter.spec
;   2. Compile this script:         iscc packaging/installer.iss
;   3. Output appears in dist_installer/UniversalDeathCounterSetup.exe
;
; This is also run automatically by .github/workflows/build-windows.yml.

#define AppName "DePhantom Universal Death Counter"
; The version's single source of truth is APP_VERSION in
; src/utils/constants.py. CI passes it in with /DAppVersion=...; this
; fallback is only for quick local builds.
#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define AppPublisher "Jeeventhiran Sivanantham"
#define AppExeName "UniversalDeathCounter.exe"

[Setup]
AppId={{B27B6A0E-6E2E-4E6D-9A1A-UNIVDEATHCTR}}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
OutputDir=..\dist_installer
OutputBaseFilename=UniversalDeathCounterSetup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icons\app_icon.ico
ArchitecturesInstallIn64BitMode=x64compatible
DisableProgramGroupPage=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
; PyInstaller folder build: the .exe plus its _internal\ libraries.
Source: "..\dist\UniversalDeathCounter\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Code]
{ What to show: everything, the death counter only, or the speedrun timer only.
  Written to edition.txt; the app applies it once (Settings changes it later).
  Updates keep the previous answer. }
var
  EditionPage: TInputOptionWizardPage;

procedure InitializeWizard;
begin
  EditionPage := CreateInputOptionPage(wpSelectTasks,
    'What do you want to use?',
    'You can change this any time in Settings, General, Features.',
    'DUDC shows only what you pick:', True, False);
  EditionPage.Add('Everything: death counter and speedrun timer');
  EditionPage.Add('Death counter only');
  EditionPage.Add('Speedrun timer only');
  case GetPreviousData('Edition', 'all') of
    'counter': EditionPage.SelectedValueIndex := 1;
    'speedrun': EditionPage.SelectedValueIndex := 2;
  else
    EditionPage.SelectedValueIndex := 0;
  end;
end;

function EditionValue: String;
begin
  case EditionPage.SelectedValueIndex of
    1: Result := 'counter';
    2: Result := 'speedrun';
  else
    Result := 'all';
  end;
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'Edition', EditionValue);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    SaveStringToFile(ExpandConstant('{app}\edition.txt'), EditionValue, False);
end;

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent
; In-app updates run the installer silently: reopen the app afterwards, as
; the player (not as administrator, which the installer runs as).
Filename: "{app}\{#AppExeName}"; Flags: nowait skipifnotsilent runasoriginaluser

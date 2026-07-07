; Inno Setup script for Universal Death Counter.
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

#define AppName "Universal Death Counter"
#define AppVersion "1.5.0"
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
Source: "..\dist\{#AppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppName}"; Flags: nowait postinstall skipifsilent

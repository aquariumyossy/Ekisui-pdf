; Per-user, unsigned installer. Start menu entry and uninstall via Windows settings.

#define MyAppName "ekisui-pdf"
#define MyAppVersion "0.1.0"
#define MyAppExe "ekisui-pdf.exe"

[Setup]
AppId={{E4B7A1C2-6D58-4F0E-9A31-7C2E8B6D4F10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=ekisui-pdf contributors
DefaultDirName={localappdata}\ekisui-pdf
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64
ArchitecturesInstallIn64BitMode=x64
OutputDir=..\dist
OutputBaseFilename=ekisui-pdf-0.1.0-win64-setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
SetupIconFile=..\assets\icon\ekisui.ico
UninstallDisplayIcon={app}\ekisui.ico
LicenseFile=..\LICENSE
InfoBeforeFile=..\THIRD_PARTY_NOTICES.md

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "..\dist\ekisui-pdf\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\assets\icon\ekisui.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\ekisui.ico"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; IconFilename: "{app}\ekisui.ico"

[Run]
Filename: "{app}\{#MyAppExe}"; Description: "ekisui-pdf を起動する"; Flags: nowait postinstall skipifsilent

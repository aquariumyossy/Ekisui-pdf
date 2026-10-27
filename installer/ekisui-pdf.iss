; 易水PDF のインストーラ。署名はしない。
#define AppVersion "0.1.0"

[Setup]
AppId={{A4C8E1D2-7B39-4F6A-9E15-2D8C6B0A4F77}
AppName=易水PDF
AppVersion={#AppVersion}
AppVerName=易水PDF {#AppVersion}
AppPublisher=ekisui-pdf
DefaultDirName={localappdata}\ekisui-pdf
DefaultGroupName=易水PDF
DisableProgramGroupPage=no
OutputDir=..\dist-installer
OutputBaseFilename=ekisui-pdf-{#AppVersion}-win64-setup
Compression=lzma2
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
WizardStyle=modern
UninstallDisplayName=易水PDF
LicenseFile=..\LICENSE
InfoBeforeFile=info-before.txt
SetupLogging=yes

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\ekisui-pdf\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\THIRD_PARTY_NOTICES.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\licenses\*"; DestDir: "{app}\licenses"; Flags: ignoreversion

[Icons]
Name: "{group}\易水PDF"; Filename: "{app}\ekisui-pdf.exe"
Name: "{group}\ライセンスと第三者表記"; Filename: "{app}\THIRD_PARTY_NOTICES.md"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\ekisui-pdf.exe"; Description: "易水PDFを起動する"; Flags: nowait postinstall skipifsilent

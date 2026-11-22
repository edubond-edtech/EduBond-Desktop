; Inno Setup script — builds EduKit-Setup-<version>.exe from desktop\dist\EduKit
; Compiled automatically by build_windows.bat (needs Inno Setup 6: https://jrsoftware.org/isdl.php)

#define AppName "EduKit"
; the GitHub build passes /DAppVersion=<tag version>; local builds use the default below
#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif
#define AppPublisher "EduBond"
#define AppExe "EduKit.exe"

[Setup]
AppId={{8C1F5D2A-6B7E-4E1B-9A43-2F0D7C5E3B91}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; installs without administrator rights (per user); an admin can still choose "all users"
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist\installer
OutputBaseFilename=EduKit-Setup-{#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\dist\EduKit\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\EduBond - رحلة إلى مكة"; Filename: "{app}\{#AppExe}"
Name: "{group}\Uninstall EduKit"; Filename: "{uninstallexe}"
Name: "{autodesktop}\EduBond - رحلة إلى مكة"; Filename: "{app}\{#AppExe}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start EduKit now"; Flags: nowait postinstall skipifsilent

; Lessons, students and results live in %APPDATA%\EduKit and are kept when EduKit is
; uninstalled or upgraded, so installing a new version never loses classroom data.

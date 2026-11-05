; Inno Setup script: builds CrespoBeautify-Setup.exe (free: https://jrsoftware.org/isinfo.php)
; Build on Windows:  iscc windows\CrespoBeautify.iss    -> windows\Output\CrespoBeautify-Setup.exe
#define AppName "CrespoBeautify"
[Setup]
AppName={#AppName}
AppVersion=1.0
DefaultDirName={localappdata}\CrespoBeautify
DisableDirPage=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=CrespoBeautify-Setup
OutputDir=Output
Compression=lzma2
SolidCompression=yes
UninstallDisplayName={#AppName}

[Files]
Source: "..\crespoqa\*"; DestDir: "{app}\app\crespoqa"; Flags: recursesubdirs ignoreversion; Excludes: "__pycache__"
Source: "..\requirements-runtime.txt"; DestDir: "{app}\app"; Flags: ignoreversion
Source: "Start-CrespoBeautify.cmd"; DestDir: "{app}\app\windows"; Flags: ignoreversion
Source: "Setup-CrespoBeautify.ps1"; DestDir: "{app}"; Flags: ignoreversion

[Run]
Filename: "powershell.exe"; Parameters: "-NoProfile -ExecutionPolicy Bypass -File ""{app}\Setup-CrespoBeautify.ps1"" -InstallDir ""{app}"""; StatusMsg: "Installing LibreOffice, Poppler, the AI model and the app (this takes a while)..."; Flags: waituntilterminated

[UninstallDelete]
Type: filesandordirs; Name: "{app}\venv"
Type: filesandordirs; Name: "{app}\app"

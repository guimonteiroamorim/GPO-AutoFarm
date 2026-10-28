; Instala o aplicativo compilado pelo PyInstaller em modo --onedir.
; Coloque este arquivo na mesma pasta que main.py.
[Setup]
AppId=GPO_AutoFarm_v11
AppName=GPO_AutoFarm_v11
AppVersion=11.0
AppVerName=GPO_AutoFarm_v11
DefaultDirName={localappdata}\Programs\GPO_AutoFarm_v11
DefaultGroupName=GPO_AutoFarm_v11
PrivilegesRequired=lowest
WizardStyle=modern
DisableWelcomePage=no
LicenseFile=TERMOS.txt
OutputDir=instalador
OutputBaseFilename=GPO_AutoFarm_v11_Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\GPO_AutoFarm_v11.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na area de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "dist\GPO_AutoFarm_v11\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\GPO_AutoFarm_v11"; Filename: "{app}\GPO_AutoFarm_v11.exe"
Name: "{autodesktop}\GPO_AutoFarm_v11"; Filename: "{app}\GPO_AutoFarm_v11.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\GPO_AutoFarm_v11.exe"; Description: "Abrir GPO_AutoFarm_v11"; Flags: nowait postinstall skipifsilent

; Instala o aplicativo compilado pelo PyInstaller em modo --onedir.
; Coloque este arquivo na mesma pasta que main.py.
[Setup]
AppId=RobloxAutoFarm
AppName=Roblox AutoFarm
AppVersion=11.0
AppVerName=Roblox AutoFarm v11
DefaultDirName={localappdata}\Programs\RobloxAutoFarm
DefaultGroupName=Roblox AutoFarm
PrivilegesRequired=lowest
WizardStyle=modern
DisableWelcomePage=no
LicenseFile=TERMOS.txt
OutputDir=instalador
OutputBaseFilename=Roblox_AutoFarm_v11_Setup
Compression=lzma
SolidCompression=yes
UninstallDisplayIcon={app}\RobloxAutoFarm.exe

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar um atalho na area de trabalho"; GroupDescription: "Atalhos:"; Flags: unchecked

[Files]
Source: "dist\RobloxAutoFarm\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Roblox AutoFarm"; Filename: "{app}\RobloxAutoFarm.exe"
Name: "{autodesktop}\Roblox AutoFarm"; Filename: "{app}\RobloxAutoFarm.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\RobloxAutoFarm.exe"; Description: "Abrir Roblox AutoFarm"; Flags: nowait postinstall skipifsilent

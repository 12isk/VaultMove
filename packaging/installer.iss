; Inno Setup script for VaultMove (built in CI: ISCC /DMyAppVersion=x.y.z packaging\installer.iss)
; Per-user install by default (no admin), optional "start with Windows", Start menu entry.
; The uninstaller removes the program and its Run entry. It never touches the backup drive (vault).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B7E-4C1D-9E2F-5A4B3C2D1E0F}
AppName=VaultMove
AppVersion={#MyAppVersion}
AppVerName=VaultMove {#MyAppVersion}
AppPublisher=VaultMove
DefaultDirName={localappdata}\Programs\VaultMove
DefaultGroupName=VaultMove
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=VaultMove-Setup-{#MyAppVersion}
SetupIconFile=vaultmove.ico
UninstallDisplayIcon={app}\VaultMove.exe
UninstallDisplayName=VaultMove
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=force
RestartApplications=no
MinVersion=10.0

[Languages]
Name: "en"; MessagesFile: "compiler:Default.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"

[CustomMessages]
en.StartupTask=Start VaultMove when I sign in to Windows (recommended)
fr.StartupTask=Lancer VaultMove à l’ouverture de session Windows (recommandé)
en.DesktopTask=Create a desktop shortcut
fr.DesktopTask=Créer un raccourci sur le Bureau
en.OpenApp=Open VaultMove
fr.OpenApp=Ouvrir VaultMove
en.RemoveSettings=Also remove VaultMove settings from this PC?%n%nYour backup drive is never modified.
fr.RemoveSettings=Supprimer aussi les réglages de VaultMove sur ce PC ?%n%nVotre disque de sauvegarde n’est jamais modifié.

[Tasks]
Name: "startup"; Description: "{cm:StartupTask}"
Name: "desktopicon"; Description: "{cm:DesktopTask}"; Flags: unchecked

[Files]
Source: "..\dist\VaultMove\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\VaultMove"; Filename: "{app}\VaultMove.exe"
Name: "{autodesktop}\VaultMove"; Filename: "{app}\VaultMove.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VaultMove"; \
  ValueData: """{app}\VaultMove.exe"" --background"; Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{app}\VaultMove.exe"; Description: "{cm:OpenApp}"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM VaultMove.exe /F"; Flags: runhidden; RunOnceId: "StopVaultMove"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usPostUninstall then
  begin
    { The app can add this value itself from Settings; remove it in every case. }
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'VaultMove');
    if not UninstallSilent then
      if MsgBox(ExpandConstant('{cm:RemoveSettings}'), mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
        DelTree(ExpandConstant('{userappdata}\VaultMove'), True, True, True);
  end;
end;

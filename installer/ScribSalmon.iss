; Build: ISCC /DAppVersion=1.4.0 /DAppVersionNumeric=1.4.0.0 /DDistDir=<abs>\dist\ScribSalmon installer\ScribSalmon.iss
; AppId below identifies the app for upgrades/uninstall. NEVER change it after the first release.
#define AppName "ScribSalmon"
#define AppExe  "ScribSalmon.exe"
#define AppAumid "OmeletteSalmon.ScribSalmon"
#define AppMutex "ScribSalmonAppMutex"
#ifndef AppVersion
  #define FH FileOpen(AddBackslash(SourcePath) + "..\VERSION")
  #define AppVersion Trim(FileRead(FH))
  #expr FileClose(FH)
#endif
#ifndef AppVersionNumeric
  #define AppVersionNumeric AppVersion
#endif
#ifndef DistDir
  #define DistDir AddBackslash(SourcePath) + "..\dist\ScribSalmon"
#endif
#if !FileExists(DistDir + "\" + AppExe)
  #error dist\ScribSalmon\ScribSalmon.exe not found - run pyinstaller first
#endif
#if !FileExists(DistDir + "\THIRD_PARTY_NOTICES.txt") || !FileExists(DistDir + "\LICENSE")
  #error LICENSE / THIRD_PARTY_NOTICES.txt missing from dist (run the notices step)
#endif
#if !FileExists(AddBackslash(SourcePath) + "..\packaging\ScribSalmon.exe.config")
  #error packaging\ScribSalmon.exe.config missing
#endif
[Setup]
AppId={{BED9A63F-69FD-4F73-9969-C560612805CD}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher=OmeletteSalmon
AppPublisherURL=https://github.com/akirasane/ScribSalmon
AppSupportURL=https://github.com/akirasane/ScribSalmon/issues
AppUpdatesURL=https://github.com/akirasane/ScribSalmon/releases
VersionInfoVersion={#AppVersionNumeric}
PrivilegesRequired=lowest
DefaultDirName={autopf}\{#AppName}
UsePreviousAppDir=yes
DisableDirPage=auto
DisableProgramGroupPage=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=Output
OutputBaseFilename=ScribSalmon-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#AppExe}
UninstallDisplayName={#AppName}
LicenseFile=..\LICENSE
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
LZMAUseSeparateProcess=yes
CloseApplications=yes
RestartApplications=no
SetupMutex=ScribSalmonSetupMutex
SetupLogging=yes
[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
[Files]
Source: "{#DistDir}\*"; DestDir: "{app}"; Excludes: "ScribSalmon.exe.config"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\packaging\ScribSalmon.exe.config"; DestDir: "{app}"; Flags: ignoreversion
[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppAumid}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExe}"; AppUserModelID: "{#AppAumid}"; Tasks: desktopicon
[Run]
Filename: "{app}\{#AppExe}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\{#AppExe}"; Flags: nowait; Check: HasParam('/RELAUNCH')
[UninstallDelete]
Type: filesandordirs; Name: "{app}\_internal"
Type: dirifempty; Name: "{app}"
[Code]
const
  AppMutexName = '{#AppMutex}';
  WV2 = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
function HasParam(const P: String): Boolean;
var i: Integer;
begin
  Result := False;
  for i := 1 to ParamCount do
    if CompareText(ParamStr(i), P) = 0 then begin Result := True; Exit; end;
end;
function WaitForAppExit(Seconds: Integer): Boolean;
var i: Integer;
begin
  for i := 1 to Seconds * 4 do begin
    if not CheckForMutexes(AppMutexName) then begin Result := True; Exit; end;
    Sleep(250);
  end;
  Result := not CheckForMutexes(AppMutexName);
end;
function EnsureAppClosed(): Boolean;
begin
  Result := True;
  while CheckForMutexes(AppMutexName) do
    if SuppressibleMsgBox('ScribSalmon is still running. Close it, then click Retry.', mbError, MB_RETRYCANCEL, IDCANCEL) = IDCANCEL then begin
      Result := False; Exit;
    end;
end;
function GoodPv(Root: Integer; const Key: String): Boolean;
var pv: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', pv) and (pv <> '') and (pv <> '0.0.0.0');
end;
function WebView2Installed(): Boolean;
begin
  Result := GoodPv(HKLM32, WV2) or GoodPv(HKLM64, WV2) or GoodPv(HKCU, WV2);
end;
function InitializeSetup(): Boolean;
var Code: Integer;
begin
  if HasParam('/UPDATE') then WaitForAppExit(60);
  Result := EnsureAppClosed();
  if not Result then Exit;
  if not WebView2Installed() then begin
    Log('WebView2 runtime not found');
    if not WizardSilent() then
      if MsgBox('ScribSalmon needs the Microsoft Edge WebView2 Runtime, which was not found.'#13#10#13#10 +
                'Open the download page now? Setup will continue either way.', mbConfirmation, MB_YESNO) = IDYES then
        ShellExec('open', 'https://developer.microsoft.com/microsoft-edge/webview2/', '', '', SW_SHOWNORMAL, ewNoWait, Code);
  end;
end;
function NextButtonClick(CurPageID: Integer): Boolean;
var d: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then begin
    d := Lowercase(RemoveBackslashUnlessRoot(WizardDirValue));
    if (d = Lowercase(ExpandConstant('{userdocs}\ScribSalmon'))) or (d = Lowercase(ExpandConstant('{userappdata}\ScribSalmon'))) then begin
      MsgBox('That folder holds your ScribSalmon notes/settings. Choose another install folder.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
function InitializeUninstall(): Boolean;
begin
  Result := EnsureAppClosed();
end;
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent()) then
    if MsgBox('Also delete ScribSalmon settings (including saved API keys) in ' + ExpandConstant('{userappdata}\ScribSalmon') + '?'#13#10#13#10 +
              'Your notes in Documents\ScribSalmon are kept either way.', mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDNO then Exit
    else DelTree(ExpandConstant('{userappdata}\ScribSalmon'), True, True, True);
end;

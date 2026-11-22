; Hephaestus V1.2.1 Windows 安装脚本（Inno Setup 6.5+）
; 设计要点：
; 1. 默认按用户安装到 %LOCALAPPDATA%\Programs\Hephaestus，无需管理员权限；
; 2. 用户数据始终位于 %LOCALAPPDATA%\Hephaestus（数据库、日志、配置），与安装目录分离；
; 3. 卸载只删除安装目录内由安装程序写入的文件，绝不删除用户数据库；
; 4. 覆盖升级使用同一 AppId，保留安装目录与用户数据；
; 5. 安装前检测 WebView2 Runtime，缺失时给出中文提示并打开微软官方下载页；
; 6. 禁止把程序安装到用户数据目录，避免误删风险。

#define AppName "Hephaestus"
#define AppVersion "1.2.1"
#define AppPublisher "Hephaestus"
#define AppExeName "Hephaestus.exe"
#define AppGuid "{{7C4E2B1A-9F3D-4A6E-8B52-1D9C0E7A3F64}"

[Setup]
AppId={#AppGuid}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL=https://github.com/jionbobby-commits/Hephaestus
AppSupportURL=https://github.com/jionbobby-commits/Hephaestus
AppUpdatesURL=https://github.com/jionbobby-commits/Hephaestus
AppComments=本地优先的 Windows 笔记应用，数据只保存在本机。
DefaultDirName={localappdata}\Programs\Hephaestus
DefaultGroupName=Hephaestus
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=commandline
ArchitecturesAllowed=x64compatible
MinVersion=10.0
OutputDir=..\dist\installer
OutputBaseFilename=Hephaestus-Setup-{#AppVersion}
SetupIconFile=..\desktop\assets\Hephaestus.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex=Hephaestus-Desktop-V1.1
VersionInfoVersion=1.2.1
VersionInfoCompany={#AppPublisher}
VersionInfoDescription=Hephaestus {#AppVersion} 安装程序
VersionInfoProductName={#AppName}
VersionInfoProductVersion=1.2.1
VersionInfoOriginalFileName=Hephaestus-Setup-{#AppVersion}.exe

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
; PyInstaller onedir 产物：Hephaestus.exe + _internal（含 static 前端资源）
Source: "..\dist\Hephaestus\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
; 随程序安装的说明文档（不包含任何用户数据）
Source: "..\README.md"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\docs\windows-desktop.md"; DestDir: "{app}\docs"; Flags: ignoreversion
Source: "..\VERSION"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Hephaestus"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"
Name: "{group}\卸载 Hephaestus"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Hephaestus"; Filename: "{app}\{#AppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,Hephaestus}"; Flags: nowait postinstall skipifsilent

; 注意：这里刻意不写 [UninstallDelete]。
; 用户数据库位于 %LOCALAPPDATA%\Hephaestus\hephaestus.db，不在 {app} 下，
; 因此卸载程序只会移除自己安装的文件，数据库、日志与配置都会保留。

[Code]
const
  WebView2ClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2DownloadUrl = 'https://developer.microsoft.com/microsoft-edge/webview2/';

function ReadWebView2Version(): String;
var
  Value: String;
begin
  Result := '';
  if RegQueryStringValue(HKLM64, WebView2ClientKey, 'pv', Value) then
    Result := Trim(Value);
  if (Result = '') and RegQueryStringValue(HKLM32, WebView2ClientKey, 'pv', Value) then
    Result := Trim(Value);
  if (Result = '') and RegQueryStringValue(HKCU64, WebView2ClientKey, 'pv', Value) then
    Result := Trim(Value);
  if (Result = '') and RegQueryStringValue(HKCU32, WebView2ClientKey, 'pv', Value) then
    Result := Trim(Value);
  if (Result = '0.0.0.0') or (Result = '0.0.0') then
    Result := '';
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if ReadWebView2Version() = '' then
  begin
    if MsgBox(
      '未检测到 Microsoft WebView2 Runtime。' + #13#10#13#10 +
      'Hephaestus 需要 WebView2 才能显示界面（Windows 10/11 通常已自带）。' + #13#10 +
      '是否现在打开微软官方下载页面？安装完成后重新运行本安装程序即可。' + #13#10#13#10 +
      '提示：Hephaestus 已内置运行环境，不需要安装 Python。',
      mbConfirmation, MB_YESNO) = IDYES then
    begin
      ShellExec('open', WebView2DownloadUrl, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
    end;
  end;
end;

function NextButtonClick(CurPageID: Integer): Boolean;
var
  AppDir: String;
  DataDir: String;
begin
  Result := True;
  if CurPageID = wpSelectDir then
  begin
    AppDir := RemoveBackslashUnlessRoot(ExpandConstant('{app}'));
    DataDir := RemoveBackslashUnlessRoot(ExpandConstant('{localappdata}\Hephaestus'));
    if CompareText(AppDir, DataDir) = 0 then
    begin
      MsgBox(
        '不能把程序安装到用户数据目录：' + #13#10 + DataDir + #13#10#13#10 +
        '该目录保存笔记数据库，卸载时不会被删除。请选择其他安装目录。',
        mbError, MB_OK);
      Result := False;
    end;
  end;
end;

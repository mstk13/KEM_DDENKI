[Setup]
AppName=ケンモチ電機
AppVersion=1.0
AppPublisher=ケンモチ電機
DefaultDirName={autopf}\KenmouchiDenki
DefaultGroupName=ケンモチ電機
UninstallDisplayIcon={app}\icon.ico
OutputDir=output
OutputBaseFilename=KenmouchiDenki_Setup
SetupIconFile=..\portal\icon.ico
Compression=lzma
SolidCompression=yes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest

[Languages]
Name: "japanese"; MessagesFile: "compiler:Languages\Japanese.isl"

[Files]
Source: "..\portal\icon.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\portal\icon-192.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\portal\icon-512.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "launcher.html"; DestDir: "{app}"; Flags: ignoreversion
Source: "config_server.bat"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autodesktop}\ケンモチ電機"; Filename: "{app}\launcher.html"; IconFilename: "{app}\icon.ico"
Name: "{group}\ケンモチ電機"; Filename: "{app}\launcher.html"; IconFilename: "{app}\icon.ico"
Name: "{group}\サーバー設定変更"; Filename: "{app}\config_server.bat"; IconFilename: "{app}\icon.ico"
Name: "{group}\アンインストール"; Filename: "{uninstallexe}"

[Run]
Filename: "{app}\config_server.bat"; Description: "サーバーIPアドレスを設定"; Flags: postinstall shellexec

[Code]
// Nothing extra needed - config_server.bat handles IP setup

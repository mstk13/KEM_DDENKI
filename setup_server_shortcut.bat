@echo off
chcp 65001 >nul
title ケンモチ電機 - サーバーPCショートカット作成

echo.
echo サーバーPC用デスクトップショートカットを作成します...
echo.

REM --- アイコンをコピー ---
set ICON_DIR=%LOCALAPPDATA%\KenmouchiDenki
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

REM WSLのportalからWindows側にコピー
set WSL_ICON=\\wsl$\Ubuntu\home\masakem\KEM_DDENKI\portal\icon.ico
if exist "%WSL_ICON%" (
    copy "%WSL_ICON%" "%ICON_DIR%\icon.ico" >nul
) else (
    REM Try with wsl.localhost
    set WSL_ICON=\\wsl.localhost\Ubuntu\home\masakem\KEM_DDENKI\portal\icon.ico
    if exist "%WSL_ICON%" (
        copy "%WSL_ICON%" "%ICON_DIR%\icon.ico" >nul
    ) else (
        echo [警告] WSLからアイコンをコピーできませんでした。
        echo 手動で portal\icon.ico を %ICON_DIR% にコピーしてください。
    )
)

REM --- デスクトップにショートカットを作成 ---
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $sc = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ケンモチ電機.lnk'); ^
   $sc.TargetPath = 'http://localhost:8080'; ^
   $sc.IconLocation = '%ICON_DIR%\icon.ico,0'; ^
   $sc.Description = 'ケンモチ電機 施工コスト最適化システム'; ^
   $sc.Save()"

echo.
echo デスクトップに「ケンモチ電機」アイコンを作成しました。
echo.
echo ※ アプリを使うには、先にWSLで start_wsl.sh を実行してください。
echo.
pause

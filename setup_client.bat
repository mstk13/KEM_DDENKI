@echo off
chcp 65001 >nul
title ケンモチ電機 - クライアントセットアップ

echo.
echo ============================================
echo   ケンモチ電機 クライアントセットアップ
echo ============================================
echo.

REM --- サーバーIPを入力 ---
set /p SERVER_IP="サーバーPCのIPアドレスを入力してください (例: 192.168.0.27): "

if "%SERVER_IP%"=="" (
    echo IPアドレスが入力されませんでした。
    pause
    exit /b 1
)

echo.
echo サーバーIP: %SERVER_IP%
echo.

REM --- アイコンをダウンロード ---
set ICON_DIR=%LOCALAPPDATA%\KenmouchiDenki
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

echo アイコンをダウンロード中...
powershell -Command "Invoke-WebRequest -Uri 'http://%SERVER_IP%:8080/icon.ico' -OutFile '%ICON_DIR%\icon.ico'" 2>nul

if not exist "%ICON_DIR%\icon.ico" (
    echo.
    echo [エラー] アイコンのダウンロードに失敗しました。
    echo サーバーPCでアプリが起動しているか確認してください。
    echo サーバーPCで: cd ~/KEM_DDENKI ^&^& bash start_wsl.sh
    pause
    exit /b 1
)

echo アイコンをダウンロードしました。

REM --- デスクトップにショートカットを作成 ---
echo ショートカットを作成中...

powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $sc = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ケンモチ電機.lnk'); ^
   $sc.TargetPath = 'http://%SERVER_IP%:8080'; ^
   $sc.IconLocation = '%ICON_DIR%\icon.ico,0'; ^
   $sc.Description = 'ケンモチ電機 施工コスト最適化システム'; ^
   $sc.Save()"

echo.
echo ============================================
echo   セットアップ完了！
echo ============================================
echo.
echo デスクトップに「ケンモチ電機」アイコンが作成されました。
echo ダブルクリックでアプリ選択画面が開きます。
echo.
pause

@echo off
chcp 65001 >nul

echo ========================================
echo   ケンモチ電機 クライアントセットアップ
echo ========================================
echo.
echo   サーバーPCへブラウザでアクセスするための
echo   デスクトップショートカットを作成します。
echo.

set /p SERVER_IP="サーバーPCのIPアドレスを入力 (例: 192.168.0.27): "

if "%SERVER_IP%"=="" (
    echo [エラー] IPアドレスが入力されていません。
    pause
    exit /b 1
)

:: アイコンをダウンロード
set ICON_DIR=%LOCALAPPDATA%\KenmouchiDenki
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

echo.
echo [1/2] アイコンをダウンロード中...
powershell -Command "try { Invoke-WebRequest -Uri 'http://%SERVER_IP%/icon.ico' -OutFile '%ICON_DIR%\icon.ico' -TimeoutSec 5 } catch { Write-Host '[警告] アイコンのダウンロードに失敗。デフォルトアイコンを使用します。' }" 2>nul

:: デスクトップショートカットを作成
echo [2/2] ショートカットを作成中...
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $sc = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\ケンモチ電機.lnk'); ^
   $sc.TargetPath = 'http://%SERVER_IP%/'; ^
   if (Test-Path '%ICON_DIR%\icon.ico') { $sc.IconLocation = '%ICON_DIR%\icon.ico,0' }; ^
   $sc.Save()"

echo.
echo ========================================
echo   セットアップ完了
echo ========================================
echo.
echo   デスクトップの「ケンモチ電機」アイコンを
echo   ダブルクリックしてアプリを開いてください。
echo.
echo   接続先: http://%SERVER_IP%/
echo ========================================
echo.
pause

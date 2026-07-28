@echo off
chcp 65001 >nul

echo ========================================
echo   ケンモチ電機 クライアントセットアップ
echo ========================================
echo.
echo   サーバーPCの各アプリへのデスクトップ
echo   ショートカットを作成します。
echo.

set /p SERVER_IP="サーバーPCのIPアドレスを入力 (例: 192.168.0.35): "

if "%SERVER_IP%"=="" (
    echo [エラー] IPアドレスが入力されていません。
    pause
    exit /b 1
)

:: アイコン保存先
set ICON_DIR=%LOCALAPPDATA%\KenmouchiDenki
if not exist "%ICON_DIR%" mkdir "%ICON_DIR%"

echo.
echo [1/2] アイコンをダウンロード中...
powershell -Command "try { Invoke-WebRequest -Uri 'http://%SERVER_IP%/icon.ico' -OutFile '%ICON_DIR%\icon.ico' -TimeoutSec 5 } catch { Write-Host '[情報] アイコンのダウンロードをスキップ' }" 2>nul

echo [2/2] ショートカットを作成中...

:: デスクトップパス
for /f "usebackq tokens=*" %%D in (`powershell -Command "[Environment]::GetFolderPath('Desktop')"`) do set DESKTOP=%%D

:: ショートカット作成用フォルダ
set FOLDER=%DESKTOP%\ケンモチ電機
if not exist "%FOLDER%" mkdir "%FOLDER%"

:: --- 各アプリのショートカットを作成 ---
call :MakeShortcut "ポータル（トップ）"      "http://%SERVER_IP%/"
call :MakeShortcut "入札案件管理"            "http://%SERVER_IP%/bid/"
call :MakeShortcut "材料管理"                "http://%SERVER_IP%/material/"
call :MakeShortcut "作業日報"                "http://%SERVER_IP%/nippou/"
call :MakeShortcut "人事評価（入力）"        "http://%SERVER_IP%/eval/"
call :MakeShortcut "人事評価（管理）"        "http://%SERVER_IP%/eval-admin/"
call :MakeShortcut "営業管理"                "http://%SERVER_IP%/eigyo/"
call :MakeShortcut "日報管理（勤怠）"        "http://%SERVER_IP%/nippou-kanri/"

echo.
echo ========================================
echo   セットアップ完了
echo ========================================
echo.
echo   デスクトップの「ケンモチ電機」フォルダに
echo   各アプリのショートカットを作成しました。
echo.
echo   接続先: http://%SERVER_IP%/
echo ========================================
echo.
pause
exit /b 0

:: --- ショートカット作成サブルーチン ---
:MakeShortcut
set NAME=%~1
set URL=%~2
powershell -Command ^
  "$ws = New-Object -ComObject WScript.Shell; ^
   $sc = $ws.CreateShortcut('%FOLDER%\%NAME%.lnk'); ^
   $sc.TargetPath = '%URL%'; ^
   if (Test-Path '%ICON_DIR%\icon.ico') { $sc.IconLocation = '%ICON_DIR%\icon.ico,0' }; ^
   $sc.Save()"
echo   + %NAME%
exit /b 0

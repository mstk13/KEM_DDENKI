@echo off
chcp 65001 >nul
title ケンモチ電機 - サーバー設定

echo.
echo ==========================================
echo   ケンモチ電機 - サーバーIPアドレス設定
echo ==========================================
echo.
echo サーバーPCのIPアドレスを入力してください。
echo （サーバーPCのWSLで以下を実行して確認できます）
echo   cmd.exe /c "ipconfig" ^| grep IPv4
echo.

set /p SERVER_IP="IPアドレス (例: 192.168.0.27): "

if "%SERVER_IP%"=="" (
    echo IPアドレスが入力されませんでした。
    pause
    exit /b 1
)

REM Write config.js to app directory
echo var KEC_SERVER_IP = '%SERVER_IP%'; > "%~dp0config.js"

echo.
echo サーバーIPを %SERVER_IP% に設定しました。
echo デスクトップの「ケンモチ電機」アイコンをクリックしてご利用ください。
echo.
pause

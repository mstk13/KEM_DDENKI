@echo off
chcp 65001 >nul
title 営業訪問者 管理アプリ（自動再起動つき）
cd /d "%~dp0"

rem Python の場所（無ければ py ランチャーにフォールバック）
set "PY=C:\Users\Kenmo\AppData\Local\Programs\Python\Python312\python.exe"
if not exist "%PY%" set "PY=py"
set PYTHONIOENCODING=utf-8

rem ブラウザを開く（起動直後は表示が出ないことがあるので、その場合は再読み込み）
start "" http://localhost:8503

echo ============================================================
echo   営業訪問者 管理アプリ ( http://localhost:8503 )
echo   このウィンドウを閉じるとアプリは停止します。
echo   クラッシュしても自動で再起動します。
echo ============================================================

:loop
"%PY%" -m streamlit run app.py
echo.
echo アプリが停止しました。5秒後に自動で再起動します...
timeout /t 5 /nobreak >nul
goto loop

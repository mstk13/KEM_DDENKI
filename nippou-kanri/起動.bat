@echo off
chcp 65001 > nul
title 作業日報 自動抽出・勤怠管理システム
cd /d "%~dp0"

echo ============================================
echo  作業日報 自動抽出・勤怠管理システム
echo  http://localhost:8510  で開きます
echo  終了するには、この黒い画面を閉じてください
echo ============================================
echo.

start "" http://localhost:8510
py -3 -m streamlit run app.py --server.port 8510

echo.
echo アプリが終了しました。上のメッセージを確認してください。
pause

@echo off
rem === 作業日報アプリ 起動用（ダブルクリックで実行） ===
cd /d "%~dp0"
echo.
echo  Starting Sagyo-Nippou app ...
echo  Open  http://localhost:8501  in your browser.
echo  (Press Ctrl+C in this window to stop)
echo.
py -m streamlit run app.py
echo.
echo  --- app stopped ---
pause

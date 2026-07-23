@echo off
cd /d "%~dp0"
py -3 -m streamlit run app.py --server.port 8510 --server.headless true > "%~dp0streamlit.log" 2>&1

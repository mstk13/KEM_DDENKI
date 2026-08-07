@echo off
chcp 932 >nul
setlocal

echo ========================================
echo   KEM_DDENKI - All Apps (LAN mode)
echo ========================================
echo.

cd /d "%~dp0"

call .venv\Scripts\activate.bat

echo [1/4] Material Manager (port 5000)
cd material_manager
start "" /b python -c "from app import app; app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)"
cd ..

echo [2/4] Bid Manager (port 8501)
cd bid_manager
start "" /b streamlit run app.py --server.port 8501 --server.headless true --server.address 0.0.0.0
cd ..

echo [3/4] Work Report (port 8502)
cd sagyo-nippou
start "" /b streamlit run app.py --server.port 8502 --server.headless true --server.address 0.0.0.0
cd ..

echo [4/4] Evaluation (port 8503)
cd evaluation
start "" /b streamlit run app.py --server.port 8503 --server.headless true --server.address 0.0.0.0
cd ..

timeout /t 5 /nobreak >nul

echo.
echo ========================================
echo   Started!
echo.
echo   This PC:
echo     http://localhost:5000
echo     http://localhost:8501
echo     http://localhost:8502
echo     http://localhost:8503
echo.
echo   Other PCs:
echo     http://192.168.0.27:5000
echo     http://192.168.0.27:8501
echo     http://192.168.0.27:8502
echo     http://192.168.0.27:8503
echo.
echo   Do NOT close this window.
echo ========================================

pause >nul

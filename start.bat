@echo off
chcp 65001 >nul
setlocal

echo ========================================
echo   ケンモチ電機 施工コスト最適化システム
echo ========================================
echo.

:: スクリプトのディレクトリに移動
cd /d "%~dp0"

:: Python チェック
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [エラー] Python が見つかりません。setup.bat を先に実行してください。
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

:: venv チェック
if not exist ".venv\Scripts\activate.bat" (
    echo [エラー] 仮想環境が見つかりません。setup.bat を先に実行してください。
    pause
    exit /b 1
)

:: venv 有効化
call .venv\Scripts\activate.bat

:: ===== 自動アップデート =====
where git >nul 2>&1
if %errorlevel% equ 0 (
    echo [アップデート確認中...]
    git fetch origin main --quiet 2>nul

    :: ローカルとリモートのハッシュを比較
    for /f %%i in ('git rev-parse HEAD') do set LOCAL_HASH=%%i
    for /f %%i in ('git rev-parse origin/main') do set REMOTE_HASH=%%i

    if not "!LOCAL_HASH!"=="!REMOTE_HASH!" (
        echo [更新あり] 最新版をダウンロード中...

        :: ローカル変更がある場合は退避
        git stash --quiet 2>nul

        git pull origin main --quiet
        if %errorlevel% equ 0 (
            echo [更新完了] 依存パッケージを更新中...
            pip install -r bid_manager\requirements.txt -r material_manager\requirements.txt -r sagyo-nippou\requirements.txt --quiet

            :: DB マイグレーション（テーブル追加のみ、既存データは維持）
            cd bid_manager
            %PYTHON% database.py 2>nul
            cd ..
            cd material_manager
            %PYTHON% -c "from db import init_db; init_db()" 2>nul
            cd ..
            cd sagyo-nippou
            %PYTHON% database.py 2>nul
            cd ..

            echo [完了] アプリを最新版で起動します。
        ) else (
            echo [警告] 更新に失敗しました。現在のバージョンで起動します。
            git stash pop --quiet 2>nul
        )
    ) else (
        echo [最新版です]
    )
) else (
    echo [スキップ] Git 未インストールのため自動アップデートをスキップ。
)
echo.

:: ===== アプリ起動 =====

:: 1. 材料管理 (Flask, port 5000)
echo [1/3] 材料管理を起動中... (port 5000)
cd material_manager
%PYTHON% -c "from db import init_db; init_db()" 2>nul
start "" /b %PYTHON% -c "from app import app; app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)"
cd ..

:: 2. 入札案件管理 (Streamlit, port 8501)
echo [2/3] 入札案件管理を起動中... (port 8501)
cd bid_manager
start "" /b streamlit run app.py --server.port 8501 --server.headless true
cd ..

:: 3. 作業日報 (Streamlit, port 8502)
echo [3/3] 作業日報を起動中... (port 8502)
cd sagyo-nippou
start "" /b streamlit run app.py --server.port 8502 --server.headless true
cd ..

:: ポータルを開く
timeout /t 3 /nobreak >nul
start "" portal\index.html

echo.
echo ========================================
echo   起動完了！
echo   ポータル:   portal\index.html
echo   材料管理:   http://localhost:5000
echo   入札管理:   http://localhost:8501
echo   作業日報:   http://localhost:8502
echo.
echo   このウィンドウを閉じるとアプリも停止します。
echo   Ctrl+C で停止できます。
echo ========================================

:: 待機（ウィンドウを開いたまま維持）
pause >nul

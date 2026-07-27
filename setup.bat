@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

echo ========================================
echo   ケンモチ電機 施工コスト最適化システム
echo   初回セットアップ
echo ========================================
echo.

:: Python チェック
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo [エラー] Python が見つかりません。
        echo https://www.python.org/downloads/ からインストールしてください。
        echo インストール時に「Add Python to PATH」にチェックを入れてください。
        pause
        exit /b 1
    )
    set PYTHON=py
) else (
    set PYTHON=python
)

echo [INFO] Python: %PYTHON%
%PYTHON% --version
echo.

:: Git チェック
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [警告] Git が見つかりません。自動アップデート機能が使えません。
    echo https://git-scm.com/downloads からインストールを推奨します。
    echo.
)

:: venv 作成
if not exist ".venv" (
    echo [1/4] 仮想環境を作成中...
    %PYTHON% -m venv .venv
    if %errorlevel% neq 0 (
        echo [エラー] 仮想環境の作成に失敗しました。
        pause
        exit /b 1
    )
    echo       完了
) else (
    echo [1/4] 仮想環境は既に存在します。スキップ。
)
echo.

:: venv 有効化
call .venv\Scripts\activate.bat

:: .env 読み込み（KEM_DATA_DIR 等の共通設定）
if exist ".env" (
    for /f "usebackq tokens=1,* delims==" %%A in (".env") do (
        set "LINE=%%A"
        if not "!LINE:~0,1!"=="#" (
            if not "%%A"=="" set "%%A=%%B"
        )
    )
)

:: データフォルダを作成（デフォルト: プロジェクト直下の data\）
if not defined KEM_DATA_DIR set "KEM_DATA_DIR=%~dp0data"
if not exist "%KEM_DATA_DIR%" (
    echo [データ] フォルダを作成中: %KEM_DATA_DIR%
    mkdir "%KEM_DATA_DIR%" 2>nul
)
echo [データ] DB保存先: %KEM_DATA_DIR%

:: 依存パッケージインストール
echo [2/4] 依存パッケージをインストール中...（数分かかる場合があります）
pip install --no-cache-dir -r bid_manager\requirements.txt -r material_manager\requirements.txt -r sagyo-nippou\requirements.txt -r evaluation\requirements.txt -r eigyo-kanri\requirements.txt -r nippou-kanri\requirements.txt --quiet
if %errorlevel% neq 0 (
    echo [エラー] パッケージのインストールに失敗しました。
    pause
    exit /b 1
)
echo       完了
echo.

:: DB 初期化
echo [3/4] データベースを初期化中...

cd bid_manager
if not exist "data" mkdir data
%PYTHON% database.py
cd ..

cd material_manager
%PYTHON% -c "from db import init_db; init_db()"
cd ..

cd sagyo-nippou
%PYTHON% database.py
cd ..

cd eigyo-kanri
if not exist ".env" if exist ".env.example" copy ".env.example" ".env" >nul
%PYTHON% database.py
cd ..

cd nippou-kanri
%PYTHON% database.py
cd ..

echo       完了
echo.

:: 完了
echo [4/4] セットアップ完了！
echo.
echo ========================================
echo   次回からは start.bat で起動できます。
echo   起動時に自動でアップデートも行います。
echo.
echo   ※ 営業管理の資料自動抽出を使うには
echo      eigyo-kanri\.env に ANTHROPIC_API_KEY を設定してください。
echo      未設定でも手動登録・一覧・閲覧は使えます。
echo ========================================
echo.
pause

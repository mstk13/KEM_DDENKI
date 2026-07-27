@echo off
chcp 65001 >nul

echo ========================================
echo   ケンモチ電機 サーバーセットアップ
echo ========================================
echo.

:: Docker チェック
where docker >nul 2>&1
if %errorlevel% neq 0 (
    echo [エラー] Docker Desktop がインストールされていません。
    echo.
    echo 以下からインストールしてください:
    echo   https://www.docker.com/products/docker-desktop/
    echo.
    echo インストール後、Docker Desktop を起動してから再度このスクリプトを実行してください。
    pause
    exit /b 1
)

echo [1/2] Docker: 検出済み

cd /d "%~dp0.."

:: .env がなければコピー
if not exist ".env" (
    copy .env.example .env >nul
    echo [INFO] .env ファイルを作成しました。必要に応じて編集してください。
)

:: 全アプリをビルド・起動
echo.
echo [2/2] 全アプリをビルド・起動中...（初回は数分かかります）
docker compose up -d --build

echo.
echo ========================================
echo   セットアップ完了
echo ========================================
echo.
echo   ブラウザで http://localhost/ を開いてください。
echo.
echo   他のPCからアクセスする場合:
echo     このPCのIPアドレスを確認: ipconfig
echo     http://[IPアドレス]/ でアクセスできます。
echo.
echo   管理コマンド: docker\manage.bat --help
echo ========================================
echo.
pause

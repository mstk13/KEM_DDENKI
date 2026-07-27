@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

if "%1"=="start" (
    docker compose up -d --build
    echo.
    echo 全アプリを起動しました。
    echo ブラウザで http://localhost/ を開いてください。
    goto :end
)

if "%1"=="stop" (
    docker compose down
    echo 全アプリを停止しました。
    goto :end
)

if "%1"=="restart" (
    if "%2"=="" (
        docker compose restart
        echo 全アプリを再起動しました。
    ) else (
        docker compose restart %2
        echo %2 を再起動しました。
    )
    goto :end
)

if "%1"=="status" (
    docker compose ps
    goto :end
)

if "%1"=="update" (
    echo 最新版を取得中...
    git pull origin main
    echo アプリを再ビルド・起動中...
    docker compose up -d --build
    echo 更新完了。
    goto :end
)

if "%1"=="logs" (
    if "%2"=="" (
        docker compose logs -f --tail=50
    ) else (
        docker compose logs -f --tail=50 %2
    )
    goto :end
)

if "%1"=="backup" (
    for /f "tokens=1-3 delims=/ " %%a in ('date /t') do set D=%%a%%b%%c
    for /f "tokens=1-2 delims=: " %%a in ('time /t') do set T=%%a%%b
    set BACKUP_DIR=backups\%D%_%T%
    mkdir "%BACKUP_DIR%" 2>nul
    for %%s in (bid_manager material_manager sagyo_nippou evaluation) do (
        docker compose cp %%s:/data/. "%BACKUP_DIR%\" 2>nul
    )
    echo バックアップ完了: %BACKUP_DIR%
    goto :end
)

if "%1"=="optional" (
    docker compose --profile optional up -d --build
    echo オプションアプリを含めて起動しました。
    goto :end
)

echo ケンモチ電機 Docker管理スクリプト
echo.
echo 使い方: %~nx0 {start^|stop^|restart^|status^|update^|logs^|backup^|optional}
echo.
echo   start          全アプリ起動
echo   stop           全アプリ停止
echo   restart [app]  再起動 (例: %~nx0 restart bid_manager)
echo   status         稼働状況の確認
echo   update         最新版に更新
echo   logs [app]     ログ表示
echo   backup         DBバックアップ
echo   optional       オプションアプリも含めて起動

:end

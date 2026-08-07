@echo off
REM Git hookをインストールするスクリプト（Windows用）
REM リポジトリのルートから実行: tools\git-hooks\install.bat

set SCRIPT_DIR=%~dp0
set HOOKS_DIR=%SCRIPT_DIR%..\..\.git\hooks

if not exist "%HOOKS_DIR%" (
    echo エラー: .git\hooks ディレクトリが見つかりません
    echo リポジトリのルートから実行してください
    pause
    exit /b 1
)

copy /Y "%SCRIPT_DIR%pre-push" "%HOOKS_DIR%\pre-push" >nul

echo.
echo === Git hook インストール完了 ===
echo push前に自動でリモートの最新状態を確認します。
echo.
pause

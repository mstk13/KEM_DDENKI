# 作業完了 - 編集内容を develop に反映する
# work_finish.bat から呼び出されます
#
# ここでは develop への反映までを行う。
# 本番(main)への反映は release.bat（管理者用）で別途行う。

$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

function Show-Title($text) {
    Write-Host ''
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor Cyan
    Write-Host '========================================' -ForegroundColor Cyan
    Write-Host ''
}

function Stop-Here($code) {
    Write-Host ''
    Read-Host '  Enter キーを押すと閉じます' | Out-Null
    exit $code
}

Show-Title '作業完了 - develop に反映します'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[エラー] Git が見つかりません。' -ForegroundColor Red
    Stop-Here 1
}

# --- ブランチ確認 ---
$branch = git branch --show-current
if ($branch -ne 'develop') {
    Write-Host "[警告] 現在のブランチは `"$branch`" です。" -ForegroundColor Yellow
    Write-Host '  編集は develop で行う決まりです（README「ブランチ運用ルール」）。'
    Write-Host '  work_start.bat から始めてください。'
    Stop-Here 1
}

# --- 変更があればコミット ---
$dirty = git status --porcelain
if ($dirty) {
    Write-Host '[変更されたファイル]' -ForegroundColor Green
    git status --short
    Write-Host ''
    Write-Host '  コミットメッセージを入力してください。'
    Write-Host '  例: feat(evaluation): 評価項目に自由記述欄を追加' -ForegroundColor DarkGray
    Write-Host '      fix(sagyo-nippou): 日付が1日ずれる不具合を修正' -ForegroundColor DarkGray
    Write-Host '      docs: READMEに起動手順を追記' -ForegroundColor DarkGray
    Write-Host ''

    $msg = Read-Host '  メッセージ'
    if ([string]::IsNullOrWhiteSpace($msg)) {
        Write-Host '[中止] メッセージが空です。' -ForegroundColor Red
        Stop-Here 1
    }

    Write-Host ''
    Write-Host "[コミット中] $msg"
    git add -A
    git commit -m $msg
    if ($LASTEXITCODE -ne 0) {
        Write-Host '[エラー] コミットに失敗しました。' -ForegroundColor Red
        Stop-Here 1
    }
} else {
    Write-Host '[情報] 未コミットの変更はありません。'
}

# --- リモートの最新を取得して取り込む ---
Write-Host ''
Write-Host '[確認中] リモートの最新状態を取得しています...'
git fetch origin --prune --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] GitHub への接続に失敗しました。' -ForegroundColor Red
    Stop-Here 1
}

# 送る前に相手の変更を取り込んでおく（push が弾かれるのを防ぐ）
git merge origin/develop --no-edit
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[エラー] 他の開発者の変更と衝突しました。' -ForegroundColor Red
    Write-Host '  そのまま画面を見せて相談してください。'
    Stop-Here 1
}

# --- 送る変更があるか ---
$commits = git log --oneline origin/develop..HEAD
if (-not $commits) {
    Write-Host '[情報] develop に反映する変更がありません。作業は完了しています。' -ForegroundColor Green
    Stop-Here 0
}

Write-Host ''
Write-Host '[反映するコミット]' -ForegroundColor Green
$commits | ForEach-Object { Write-Host "  $_" }

# --- push ---
Write-Host ''
Write-Host '[送信中] develop に push しています...'
git push origin develop
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] push に失敗しました。' -ForegroundColor Red
    Stop-Here 1
}

git fetch origin --quiet

Show-Title 'develop への反映が完了しました'

Write-Host '  現在の develop:'
git log --oneline -5 origin/develop | ForEach-Object { Write-Host "    $_" }
Write-Host ''

# --- 本番との差を知らせる ---
$unreleased = git log --oneline origin/main..origin/develop
if ($unreleased) {
    Write-Host '  本番(main)にまだ反映されていない変更:' -ForegroundColor Yellow
    $unreleased | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
    Write-Host ''
    Write-Host '  本番に反映するときは release.bat を実行してください。' -ForegroundColor Yellow
    Write-Host '  （main はサーバーが毎朝自動でpullする本番用ブランチです）'
}

Write-Host ''
Stop-Here 0

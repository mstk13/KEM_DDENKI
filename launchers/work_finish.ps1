# 作業完了 - deploy-update の変更を main に反映する
# work_finish.bat から呼び出されます

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

Show-Title '作業完了 - main に反映します'

# --- Git チェック ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[エラー] Git が見つかりません。' -ForegroundColor Red
    Stop-Here 1
}

# --- ブランチ確認 ---
$branch = git branch --show-current
if ($branch -ne 'deploy-update') {
    Write-Host "[警告] 現在のブランチは `"$branch`" です。" -ForegroundColor Yellow
    Write-Host '  このスクリプトは deploy-update 用です。'
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

# --- リモートの最新を取得 ---
Write-Host ''
Write-Host '[確認中] リモートの最新状態を取得しています...'
git fetch origin --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] GitHub への接続に失敗しました。ネットワークを確認してください。' -ForegroundColor Red
    Stop-Here 1
}

# --- 反映するコミットがあるか ---
$commits = git log --oneline origin/main..HEAD
if (-not $commits) {
    Write-Host '[情報] main に反映する変更がありません。作業は完了しています。' -ForegroundColor Green
    Stop-Here 0
}

Write-Host ''
Write-Host '[反映するコミット]' -ForegroundColor Green
$commits | ForEach-Object { Write-Host "  $_" }

# --- push ---
Write-Host ''
Write-Host '[送信中] GitHub に push しています...'
git push -u origin deploy-update
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] push に失敗しました。' -ForegroundColor Red
    Stop-Here 1
}

# --- GitHub CLI が無ければ手動案内 ---
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host ''
    Write-Host '[注意] GitHub CLI (gh) が見つかりません。' -ForegroundColor Yellow
    Write-Host '  push は完了しました。以下のページから手動で Pull Request を作成してください。'
    Write-Host '  https://github.com/mstk13/KEM_DDENKI/pull/new/deploy-update' -ForegroundColor Cyan
    Stop-Here 0
}

# --- PR 作成 ---
Write-Host ''
Write-Host '[PR作成中] Pull Request を作成しています...'
gh pr create --base main --head deploy-update --fill
if ($LASTEXITCODE -ne 0) {
    Write-Host '[注意] PR は既に存在する可能性があります。続けてマージを試みます。' -ForegroundColor Yellow
}

# --- マージ ---
# --delete-branch は使わない。gh がローカルで main に切り替えようとするが、
# main は kem_wt ワークツリーが掴んでいるため失敗し、ブランチが消し残る。
# マージ後に自分でリモートブランチを削除する。
Write-Host ''
Write-Host '[マージ中] main に反映しています...'
gh pr merge --merge
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[エラー] マージに失敗しました。' -ForegroundColor Red
    Write-Host '  コンフリクト (変更の衝突) が起きている可能性があります。'
    Write-Host '  GitHub のページで確認してください:'
    Write-Host '  https://github.com/mstk13/KEM_DDENKI/pulls' -ForegroundColor Cyan
    Stop-Here 1
}

# --- 使い終わったブランチをGitHubから削除する ---
Write-Host '[片付け中] GitHub 上の作業ブランチを削除しています...'
git push origin --delete deploy-update
if ($LASTEXITCODE -ne 0) {
    Write-Host '[注意] ブランチの削除に失敗しました。次回 work_start.bat 実行時に作り直されるため実害はありません。' -ForegroundColor Yellow
}

git fetch origin --prune --quiet

Show-Title '反映完了！'

Write-Host '  現在の main:'
git log --oneline -5 origin/main | ForEach-Object { Write-Host "    $_" }
Write-Host ''
Write-Host '  次に作業を始めるときは work_start.bat を実行してください。' -ForegroundColor Green
Write-Host ''
Stop-Here 0

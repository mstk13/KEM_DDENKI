# 本番反映 - develop の内容を main に反映する（管理者用）
# release.bat から呼び出されます
#
# main はサーバーが毎朝自動で pull する本番用ブランチ。
# 実行すると本番環境に反映されるため、確認を挟む。

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

Show-Title '本番反映 - develop を main に反映します'

Write-Host '  main はサーバーが毎朝自動で pull する本番用ブランチです。' -ForegroundColor Yellow
Write-Host ''

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[エラー] Git が見つかりません。' -ForegroundColor Red
    Stop-Here 1
}
if (-not (Get-Command gh -ErrorAction SilentlyContinue)) {
    Write-Host '[エラー] GitHub CLI (gh) が見つかりません。' -ForegroundColor Red
    Write-Host '  GitHub のページから develop → main の Pull Request を作成してください。'
    Write-Host '  https://github.com/mstk13/KEM_DDENKI/compare/main...develop' -ForegroundColor Cyan
    Stop-Here 1
}

$dirty = git status --porcelain
if ($dirty) {
    Write-Host '[警告] 未コミットの変更があります。' -ForegroundColor Yellow
    git status --short
    Write-Host ''
    Write-Host '  先に work_finish.bat で develop に反映してください。' -ForegroundColor Yellow
    Stop-Here 1
}

Write-Host '[確認中] リモートの最新状態を取得しています...'
git fetch origin --prune --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] GitHub への接続に失敗しました。' -ForegroundColor Red
    Stop-Here 1
}

# --- 本番に反映される内容 ---
$commits = git log --oneline origin/main..origin/develop
if (-not $commits) {
    Write-Host '[情報] 本番に反映する変更はありません。main は develop と同じ内容です。' -ForegroundColor Green
    Stop-Here 0
}

Write-Host ''
Write-Host '[本番に反映される変更]' -ForegroundColor Green
$commits | ForEach-Object { Write-Host "  $_" }
Write-Host ''
Write-Host '[変更されるファイル]'
git diff --stat origin/main origin/develop | ForEach-Object { Write-Host "  $_" }

# --- 確認 ---
Write-Host ''
Write-Host '  この内容を本番(main)に反映します。' -ForegroundColor Yellow
$answer = Read-Host '  よろしいですか？ (y / N)'
if ($answer -ne 'y' -and $answer -ne 'Y') {
    Write-Host '[中止] 本番には反映していません。' -ForegroundColor Green
    Stop-Here 0
}

# --- PR 作成 ---
Write-Host ''
Write-Host '[PR作成中] develop → main の Pull Request を作成しています...'
gh pr create --base main --head develop --fill
if ($LASTEXITCODE -ne 0) {
    Write-Host '[注意] PR は既に存在する可能性があります。続けてマージを試みます。' -ForegroundColor Yellow
}

# --- マージ ---
# --delete-branch は使わない。develop は常設ブランチなので消してはいけない。
Write-Host ''
Write-Host '[マージ中] main に反映しています...'
gh pr merge --merge
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[エラー] マージに失敗しました。' -ForegroundColor Red
    Write-Host '  衝突が起きている可能性があります。GitHub で確認してください:'
    Write-Host '  https://github.com/mstk13/KEM_DDENKI/pulls' -ForegroundColor Cyan
    Stop-Here 1
}

# --- develop を main に追いつかせる ---
# マージコミットが main 側だけに増えるため、戻しておかないと少しずつ離れていく。
Write-Host ''
Write-Host '[整合中] develop を main に合わせています...'
git fetch origin --quiet
git merge origin/main --no-edit
if ($LASTEXITCODE -eq 0) {
    git push origin develop --quiet
} else {
    Write-Host '[注意] develop への戻しマージで衝突しました。相談してください。' -ForegroundColor Yellow
}

git fetch origin --quiet

Show-Title '本番反映が完了しました'

Write-Host '  現在の main:'
git log --oneline -5 origin/main | ForEach-Object { Write-Host "    $_" }
Write-Host ''
Write-Host '  サーバーは翌朝の自動pullで最新版になります。' -ForegroundColor Green
Write-Host ''
Stop-Here 0

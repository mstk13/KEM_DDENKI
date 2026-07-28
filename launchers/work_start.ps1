# 作業開始 - deploy-update を最新の main から作り直す
# work_start.bat から呼び出されます

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

Show-Title '作業開始 - deploy-update を作り直します'

# --- Git チェック ---
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[エラー] Git が見つかりません。' -ForegroundColor Red
    Stop-Here 1
}

# --- 安全確認1: 未コミットの変更 ---
$dirty = git status --porcelain
if ($dirty) {
    Write-Host '[警告] 未コミットの変更があります。' -ForegroundColor Yellow
    Write-Host ''
    git status --short
    Write-Host ''
    Write-Host '  このまま進めると、これらの変更は失われます。' -ForegroundColor Yellow
    Write-Host '  先に work_finish.bat で反映するか、変更を破棄してください。' -ForegroundColor Yellow
    Stop-Here 1
}

# --- リモートの最新を取得 ---
Write-Host '[確認中] リモートの最新状態を取得しています...'
git fetch origin --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] GitHub への接続に失敗しました。ネットワークを確認してください。' -ForegroundColor Red
    Stop-Here 1
}

# --- 安全確認2: main に未反映のコミット ---
$unmerged = git log --oneline origin/main..HEAD
if ($unmerged) {
    Write-Host ''
    Write-Host '[警告] main にまだ反映されていないコミットがあります。' -ForegroundColor Yellow
    Write-Host ''
    $unmerged | ForEach-Object { Write-Host "  $_" }
    Write-Host ''
    Write-Host '  このまま進めると、これらのコミットは失われます。' -ForegroundColor Yellow
    Write-Host '  先に work_finish.bat を実行して main に反映してください。' -ForegroundColor Yellow
    Stop-Here 1
}

# --- 最新の main から作り直す ---
Write-Host '[作成中] 最新の main から deploy-update を作り直しています...'
git switch -C deploy-update origin/main --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] ブランチの作り直しに失敗しました。' -ForegroundColor Red
    Stop-Here 1
}

Show-Title '準備完了！'

Write-Host ('  ブランチ: ' + (git branch --show-current)) -ForegroundColor Green
Write-Host ''
Write-Host '  最新のコミット:'
git log --oneline -3 | ForEach-Object { Write-Host "    $_" }
Write-Host ''
Write-Host '  このまま編集を始めてください。'
Write-Host '  終わったら work_finish.bat を実行します。'
Write-Host ''
Stop-Here 0

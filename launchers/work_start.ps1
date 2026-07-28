# 作業開始 - develop を最新の状態にする
# work_start.bat から呼び出されます
#
# develop は他の開発者と共有する常設ブランチなので、作り直さない（switch -C 禁止）。
# 相手の変更を取り込んでから作業を始める。

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

Show-Title '作業開始 - develop を最新にします'

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    Write-Host '[エラー] Git が見つかりません。' -ForegroundColor Red
    Stop-Here 1
}

# --- 未コミットの変更があると切り替え・マージで失敗する ---
$dirty = git status --porcelain
if ($dirty) {
    Write-Host '[警告] 未コミットの変更があります。' -ForegroundColor Yellow
    Write-Host ''
    git status --short
    Write-Host ''
    Write-Host '  先に work_finish.bat で develop に反映するか、変更を破棄してください。' -ForegroundColor Yellow
    Stop-Here 1
}

# --- リモートの最新を取得 ---
Write-Host '[確認中] リモートの最新状態を取得しています...'
git fetch origin --prune --quiet
if ($LASTEXITCODE -ne 0) {
    Write-Host '[エラー] GitHub への接続に失敗しました。ネットワークを確認してください。' -ForegroundColor Red
    Stop-Here 1
}

# --- develop へ切り替え（無ければ origin/develop から作る） ---
$branch = git branch --show-current
if ($branch -ne 'develop') {
    Write-Host "[切替中] $branch → develop"
    git switch develop --quiet
    if ($LASTEXITCODE -ne 0) {
        git switch -c develop origin/develop --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host '[エラー] develop に切り替えられませんでした。' -ForegroundColor Red
            Stop-Here 1
        }
    }
}

# --- 他の開発者の変更を取り込む ---
Write-Host '[取込中] 他の開発者の変更（origin/develop）を取り込んでいます...'
git merge origin/develop --no-edit
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[エラー] develop の取り込みで衝突しました。' -ForegroundColor Red
    Write-Host '  同じ場所を他の開発者も変更しています。解消が必要です。'
    Write-Host '  そのまま画面を見せて相談してください。'
    Stop-Here 1
}

# --- 本番(main)側の修正を取り込む ---
# main に直接入った修正が develop に無いと、そこから分岐が始まる。
Write-Host '[取込中] 本番(main)側の修正を取り込んでいます...'
git merge origin/main --no-edit
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host '[エラー] main の取り込みで衝突しました。' -ForegroundColor Red
    Write-Host '  そのまま画面を見せて相談してください。'
    Stop-Here 1
}

Show-Title '準備完了！'

Write-Host ('  ブランチ: ' + (git branch --show-current)) -ForegroundColor Green
Write-Host ''
Write-Host '  最新のコミット:'
git log --oneline -3 | ForEach-Object { Write-Host "    $_" }

$ahead = git log --oneline origin/develop..HEAD
if ($ahead) {
    Write-Host ''
    Write-Host '  ※ まだ GitHub に送っていない変更があります:' -ForegroundColor Yellow
    $ahead | ForEach-Object { Write-Host "    $_" -ForegroundColor Yellow }
}

Write-Host ''
Write-Host '  このまま編集を始めてください。'
Write-Host '  終わったら work_finish.bat を実行します。'
Write-Host ''
Stop-Here 0

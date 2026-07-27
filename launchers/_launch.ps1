param([Parameter(Mandatory=$true)][string]$App)

# ケンモチ電機アプリ ランチャー
# サーバーが起動していなければ起動し、専用ウィンドウ(アプリモード)で開く

$ErrorActionPreference = 'SilentlyContinue'
# リポジトリ直下を、このスクリプトの位置から求める（PC ごとの設置場所に依存しない）
$root  = Split-Path $PSScriptRoot -Parent
$venv  = Join-Path $root '.venv\Scripts\python.exe'

$apps = @{
  material = @{ Port = 5000; Dir = (Join-Path $root 'material_manager'); Type = 'flask';     Script = 'app.py';       Title = '材料管理' }
  bid      = @{ Port = 8501; Dir = (Join-Path $root 'bid_manager');      Type = 'streamlit'; Script = 'app.py';       Title = '入札案件管理' }
  sagyo    = @{ Port = 8502; Dir = (Join-Path $root 'sagyo-nippou');     Type = 'streamlit'; Script = 'app.py';       Title = '作業日報' }
  eigyo    = @{ Port = 8503; Dir = (Join-Path $root 'eigyo-kanri');      Type = 'streamlit'; Script = 'app.py';       Title = '営業管理' }
  evalin   = @{ Port = 8504; Dir = (Join-Path $root 'evaluation');       Type = 'streamlit'; Script = 'app.py';       Title = '人事評価(入力)' }
  evaladm  = @{ Port = 8505; Dir = (Join-Path $root 'evaluation');       Type = 'streamlit'; Script = 'admin_app.py'; Title = '人事評価(管理)' }
  nippou   = @{ Port = 8510; Dir = (Join-Path $root 'nippou-kanri');     Type = 'streamlit'; Script = 'app.py';       Title = '日報管理' }
}

$a = $apps[$App]
if (-not $a) { exit 1 }
$port = $a.Port
$url  = "http://localhost:$port"

# 起動済みか確認
$listening = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $listening) {
  if ($a.Type -eq 'flask') {
    $code = "from db import init_db; init_db(); import app as m; m.app.run(debug=False, host='0.0.0.0', port=$port, use_reloader=False)"
    Start-Process -FilePath $venv -ArgumentList @('-c', $code) -WorkingDirectory $a.Dir -WindowStyle Hidden
  } else {
    Start-Process -FilePath $venv -ArgumentList @('-m','streamlit','run',$a.Script,'--server.port',"$port",'--server.address','0.0.0.0','--server.headless','true') -WorkingDirectory $a.Dir -WindowStyle Hidden
  }
  # 起動待ち(最大20秒)
  for ($i = 0; $i -lt 40; $i++) {
    if (Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue) { break }
    Start-Sleep -Milliseconds 500
  }
  Start-Sleep -Milliseconds 800
}

# 専用ウィンドウで開く(Edge → Chrome → 既定ブラウザ の順)
$edge   = 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
$edge2  = 'C:\Program Files\Microsoft\Edge\Application\msedge.exe'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
$appArg = "--app=$url --window-size=1280,860"

if     (Test-Path $edge)   { Start-Process -FilePath $edge   -ArgumentList $appArg }
elseif (Test-Path $edge2)  { Start-Process -FilePath $edge2  -ArgumentList $appArg }
elseif (Test-Path $chrome) { Start-Process -FilePath $chrome -ArgumentList $appArg }
else                       { Start-Process $url }

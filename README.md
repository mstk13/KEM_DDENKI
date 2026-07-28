# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

電気工事の業務フローを一気通貫でカバーする社内Webアプリ群です。

---

# ユーザー向け

## アプリの使い方

サーバーPCが既に動いている場合、**ブラウザで `http://サーバーIP/` を開くだけ**です。  
インストールは不要です。

### PC（Windows / Mac）でアイコンを作る

#### 方法1: セットアップスクリプトを使う（Windows）

1. サーバーPCまたはGitHubから `setup_client_docker.bat` を取得
2. ダブルクリックして実行
3. サーバーPCのIPアドレスを入力（例: `192.168.0.35`）
4. デスクトップに「ケンモチ電機」ショートカットが作成される

#### 方法2: ブラウザからアプリとしてインストール（Windows / Mac 共通）

1. ブラウザで `http://サーバーIP/` を開く
2. **Chrome** の場合: アドレスバー右の「インストール」アイコン（⊕）をクリック
3. **Edge** の場合: メニュー（…）→「アプリ」→「このサイトをアプリとしてインストール」
4. デスクトップに「ケンモチ電機」アイコンが作成される

> インストールしたアプリは通常のアプリと同じようにタスクバーやスタートメニューに表示されます。  
> アンインストールもアプリの設定から行えます。

---

### スマホ（iPhone / Android）でアイコンを作る

#### iPhone（Safari）

1. Safari で `http://サーバーIP/` を開く
2. 画面下の共有ボタン（□↑）をタップ
3. 「ホーム画面に追加」をタップ
4. 名前を確認して「追加」

#### Android（Chrome）

1. Chrome で `http://サーバーIP/` を開く
2. メニュー（⋮）→「ホーム画面に追加」または「アプリをインストール」
3. 「追加」をタップ

> どちらもホーム画面に「ケンモチ電機」アイコンが追加され、  
> タップするだけでポータルが開きます。そこから各アプリにアクセスできます。

---

### アプリ一覧

| アプリ | URL | 概要 |
|--------|-----|------|
| ポータル | `/` | 全アプリへのランチャーページ |
| 入札案件管理 | `/bid/` | 案件収集・進捗管理・費用分析 |
| 材料管理 | `/material/` | 見積もり vs 発注の消化率追跡 |
| 作業日報 | `/nippou/` | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | `/eval/` | アンケート方式の評価入力 |
| 人事評価（管理） | `/eval-admin/` | 結果閲覧・自己vs他己比較・PDF出力 |
| 営業管理 | `/eigyo/` | 訪問記録・資料自動抽出 |
| 日報管理 | `/nippou-kanri/` | 勤怠テキスト抽出・集計 |

---

---

# 開発者向け（GitHub: [mstk13](https://github.com/mstk13)）

以下は管理者（mstk13）がサーバーのセットアップやコードの変更を行うための手順です。

## サーバーセットアップ

### Step 1: Git をインストール

- **Windows**: https://gitforwindows.org/ からダウンロード
- **Linux**: `sudo apt install git`
- **Mac**: `xcode-select --install`

### Step 2: Docker をインストール

- **Windows / Mac**: https://www.docker.com/products/docker-desktop/ からダウンロード・インストール → PC再起動
- **Linux（Ubuntu）**: Step 3 のスクリプトが自動インストールするため手動不要

> Windows Home の場合は WSL2 が必要です。Docker Desktop が自動で案内します。

インストール確認:
```bash
docker --version     # Docker version 27.x.x と表示されればOK
```

### Step 3: アプリのセットアップと起動

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
./docker/setup_server.sh      # Linux / Mac / WSL
# docker\setup_server.bat     # Windows
```

初回は数分かかります。完了後 `http://localhost/` でポータルが開けば成功です。

### Step 4: 他のPCからのアクセス確認

サーバーのIPを確認:
```bash
ipconfig        # Windows
hostname -I     # Linux
```

他のPCのブラウザで `http://サーバーIP/` を開いて表示されればOK。

> **WSL の場合**: Windows PowerShell（管理者）でポートフォワーディングが必要:
> ```powershell
> $wslIP = (wsl hostname -I).Trim().Split(' ')[0]
> netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=$wslIP
> New-NetFirewallRule -DisplayName "KEM_DDENKI" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
> ```

---

## 管理コマンド

```bash
./docker/manage.sh status              # 稼働状況
./docker/manage.sh stop                # 全アプリ停止
./docker/manage.sh start               # 全アプリ起動
./docker/manage.sh restart evaluation   # 特定アプリだけ再起動
./docker/manage.sh update              # GitHubから最新版に更新
./docker/manage.sh logs bid_manager    # ログ確認
./docker/manage.sh backup              # DBバックアップ
```

> 毎朝5時にGitHubから自動更新されます（cron）。

---

## コードの変更とデプロイ

```bash
# 1. コードを修正
# 2. GitHubにpush
git add -A && git commit -m "変更内容" && git push origin main

# 3. サーバーに反映（自動更新を待たない場合）
./docker/manage.sh update
```

人事評価の評価項目・設問は管理アプリ（`/eval-admin/`）の「評価基準の編集」→「GitHubに反映」ボタンからもpushできます。

---

## Docker を使わない起動（開発・テスト用）

```bash
./setup.sh          # 初回セットアップ
./start_all.sh      # 全アプリ起動（http://localhost:8080）
```

個別起動:

| アプリ | コマンド |
|--------|---------|
| 入札案件管理 | `cd bid_manager && python database.py && streamlit run app.py --server.port 8501` |
| 材料管理 | `cd material_manager && python -c "from db import init_db; init_db()" && python app.py` |
| 作業日報 | `cd sagyo-nippou && python database.py && streamlit run app.py --server.port 8502` |
| 人事評価（入力） | `cd evaluation && streamlit run app.py --server.port 8504` |
| 人事評価（管理） | `cd evaluation && streamlit run admin_app.py --server.port 8505` |
| 営業管理 | `cd eigyo-kanri && python database.py && streamlit run app.py --server.port 8503` |
| 日報管理 | `cd nippou-kanri && python database.py && streamlit run app.py --server.port 8510` |

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/setup_guide.md](docs/setup_guide.md) | セットアップ詳細・トラブルシューティング |
| [docs/DEVELOPER.md](docs/DEVELOPER.md) | 個別開発・テスト・新アプリ追加手順 |
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ |
| [docs/process.md](docs/process.md) | 業務プロセスフロー |

---

## データの流れ

```
入札案件管理（案件収集・入札）
    ↓ 受注
材料管理（見積もり→発注→受領の追跡）
    ↓ 施工中
作業日報（作業員・時間・交通費の記録）
    ↓                ↓
人事評価（勤怠データ連携）  コスト分析・AI見積もり ← 将来
```

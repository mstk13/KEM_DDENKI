# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

電気工事の業務フローを一気通貫でカバーする社内Webアプリ群です。

---

# アクセスURL

本番環境と開発環境はそれぞれ別のURLで動作しています。

| 環境 | URL | 対象 | 説明 |
|------|-----|------|------|
| **本番** | http://192.168.0.35:8080/ | 全社員 | 業務で使用するアプリ群（mainブランチ） |
| **開発** | http://192.168.0.35/ | 開発者のみ | 開発・テスト用（devブランチ）。GitHub反映ボタン・開発管理あり |

> ローカル（サーバーPC）からは `http://localhost:8080/`（本番）、`http://localhost/`（開発）でもアクセスできます。

---

# ユーザー向け

## アプリの使い方

ブラウザで **http://192.168.0.35:8080/** を開くだけです。  
インストールは不要です。

### PC（Windows / Mac）でアイコンを作る

#### 方法1: セットアップスクリプトを使う（Windows）

1. サーバーPCまたはGitHubから `setup_client_docker.bat` を取得
2. ダブルクリックして実行
3. サーバーPCのIPアドレスとポートを入力（例: `192.168.0.35:8080`）
4. デスクトップに「ケンモチ電機」ショートカットが作成される

#### 方法2: ブラウザからアプリとしてインストール（Windows / Mac 共通）

1. ブラウザで `http://192.168.0.35:8080/` を開く
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

### アプリ一覧（本番）

| アプリ | URL | 概要 |
|--------|-----|------|
| ポータル | http://192.168.0.35:8080/ | 全アプリへのランチャーページ |
| 入札案件管理 | http://192.168.0.35:8080/bid/ | 案件収集・進捗管理・費用分析 |
| 材料管理 | http://192.168.0.35:8080/material/ | 見積もり vs 発注の消化率追跡 |
| 作業日報 | http://192.168.0.35:8080/nippou/ | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | http://192.168.0.35:8080/eval/ | アンケート方式の評価入力 |
| 人事評価（管理） | http://192.168.0.35:8080/eval-admin/ | 結果閲覧・自己vs他己比較・PDF出力 |
| 人材管理 | http://192.168.0.35:8080/jinzai/ | 社員情報の登録・編集・Excel出力 |
| 工期管理 | http://192.168.0.35:8080/kouki/ | ガントチャート・工程進捗 |

---

---

# 開発者向け（GitHub: [mstk13](https://github.com/mstk13)）

**開発環境URL: http://192.168.0.35/**

**[📊 開発ステータス（アプリごとの進捗・課題）](docs/status.md)**

以下は管理者（mstk13）がサーバーのセットアップやコードの変更を行うための手順です。

### 開発環境のアプリ一覧

| アプリ | URL | 概要 |
|--------|-----|------|
| ポータル | http://192.168.0.35/ | 全アプリへのランチャー（開発用） |
| 開発管理 | http://192.168.0.35/dev/ | 開発タスク・進捗管理・マスター設定 |
| 入札案件管理 | http://192.168.0.35/bid/ | 案件収集・進捗管理・費用分析 |
| 材料管理 | http://192.168.0.35/material/ | 見積もり vs 発注の消化率追跡 |
| 作業日報 | http://192.168.0.35/nippou/ | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | http://192.168.0.35/eval/ | アンケート方式の評価入力 |
| 人事評価（管理） | http://192.168.0.35/eval-admin/ | 結果閲覧・自己vs他己比較・PDF出力 |
| 人材管理 | http://192.168.0.35/jinzai/ | 社員情報の登録・編集・Excel出力 |
| 工期管理 | http://192.168.0.35/kouki/ | ガントチャート・工程進捗 |

> 開発環境ではGitHub反映ボタンが有効です。アプリ上からdevブランチにpushできます。

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

## ブランチ運用ルール

```
main ← 本番環境（サーバーが自動で参照するブランチ）
 ↑
develop ← 開発用（コードの追加・修正はここで行う）
```

| ブランチ | 用途 | 誰が使う |
|---------|------|---------|
| `main` | 本番用。サーバーが毎朝自動でpullする | 管理者のみマージ |
| `develop` | 開発・テスト用。新機能やバグ修正はここで行う | 開発者全員 |

### 開発の流れ

```bash
# 1. developブランチで作業する
git checkout develop
git pull origin develop

# 2. コードを修正・テスト

# 3. developにpush
git add -A && git commit -m "変更内容"
git push origin develop

# 4. 本番に反映したい時 → GitHubでPull Requestを作成
#    develop → main のPRを作り、確認してからマージする
#    （または管理者がコマンドで直接マージ）
git checkout main
git merge develop
git push origin main
```

### テストデータの投入

developブランチには全アプリ共通のテストデータ投入スクリプトがあります。  
全アプリで同じ従業員名・現場名を使うので、実運用を模したテストができます。

```bash
# Docker環境で実行
docker compose exec bid_manager python /app/shared/seed_all.py

# データを全削除してから投入し直す場合
docker compose exec bid_manager python /app/shared/seed_all.py --reset
```

テストデータの従業員（10名）:

| コード | 名前 | 部署 | 役割 |
|--------|------|------|------|
| E001 | 剣持 太郎 | 役員 | 代表取締役 |
| E002 | 剣持 花子 | 役員 | 取締役 |
| E003 | 佐藤 健一 | 電気工事部 | 職長 |
| E004 | 田中 翔太 | 電気工事部 | 主任 |
| E005 | 鈴木 誠 | 電気工事部 | 社員 |
| E006 | 高橋 健太 | 電気工事部 | 社員 |
| E007 | 山田 美咲 | 総務部 | 事務主任 |
| E008 | 中村 裕子 | 総務部 | 事務社員 |
| E009 | 伊藤 大輔 | 電気工事部 | 見習い |
| E010 | 渡辺 拓也 | 電気工事部 | 見習い |

これらの名前が入札・材料・日報・勤怠・営業・人事評価の全アプリに横断的に使われます。

---

## コードの変更とデプロイ

```bash
# developで作業 → mainにマージ → サーバーに反映
git checkout develop
# ... 修正 ...
git add -A && git commit -m "変更内容" && git push origin develop

# 本番反映
git checkout main && git merge develop && git push origin main

# サーバーに即時反映（自動更新を待たない場合）
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

# セットアップガイド

ケンモチ電機 施工コスト最適化システムのセットアップ・運用手順です。

---

## 目次

1. [構成の選び方](#1-構成の選び方)
2. [方法A: Docker で一括セットアップ（推奨）](#2-方法a-docker-で一括セットアップ推奨)
3. [方法B: 従来方式（各PCにインストール）](#3-方法b-従来方式各pcにインストール)
4. [アプリの起動・停止・管理](#4-アプリの起動停止管理)
5. [自動アップデート](#5-自動アップデート)
6. [リリースの作成方法（管理者向け）](#6-リリースの作成方法管理者向け)
7. [トラブルシューティング](#7-トラブルシューティング)
8. [GEPS メール連携](#8-geps-メール連携)

---

## 1. 構成の選び方

| 構成 | 向いている場面 | クライアントPCに必要なもの |
|------|--------------|------------------------|
| **方法A: Docker（推奨）** | 複数PCでデータ共有して使う | ブラウザのみ（インストール不要） |
| **方法B: 従来方式** | 1台のPCだけで使う・試す | Python + パッケージ一式 |

> **複数PCで使う場合は方法Aを強く推奨します。**  
> 方法Bは各PCに Python 環境のインストールが必要で、低スペックPCではフリーズする場合があります。

---

## 2. 方法A: Docker で一括セットアップ（推奨）

サーバーPC 1台で全アプリを Docker コンテナとして実行し、他のPCはブラウザでアクセスします。

```
クライアントPC（何台でも）           サーバーPC（1台）
┌──────────────┐              ┌──────────────────────────┐
│  ブラウザのみ  │              │  Docker が全アプリを実行   │
│  インストール  │── LAN ──→  │                          │
│  一切不要     │              │  http://サーバーIP/       │
│              │              │    /bid/     入札案件管理  │
│              │              │    /material/ 材料管理    │
│              │              │    /nippou/  作業日報     │
│              │              │    /eval/    人事評価     │
│              │              │                          │
│              │              │  DB・データはすべてここに  │
└──────────────┘              └──────────────────────────┘
```

### 2-1. サーバーPCの必要スペック

| 項目 | 最低要件 |
|------|---------|
| OS | Windows 10/11 Pro（Hyper-V対応）または Linux |
| RAM | 8 GB 以上 |
| ディスク空き | 5 GB 以上 |
| ネットワーク | LAN接続（固定IPアドレス推奨） |

### 2-2. サーバーPCのセットアップ

#### Step 1: Docker をインストール

- **Windows**: [Docker Desktop](https://www.docker.com/products/docker-desktop/) をインストールし、起動しておく
- **Linux**: 下記のセットアップスクリプトが自動でインストールします

#### Step 2: リポジトリを取得

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
```

#### Step 3: セットアップスクリプトを実行

**Windows:**
```powershell
docker\setup_server.bat
```

**Linux:**
```bash
chmod +x docker/setup_server.sh
./docker/setup_server.sh
```

これで全アプリが自動的にビルド・起動されます（初回は数分かかります）。

#### Step 4: 動作確認

ブラウザで `http://localhost/` を開き、ポータルページが表示されれば成功です。

#### Step 5: サーバーPCのIPアドレスを確認

```
ipconfig    （Windows）
hostname -I （Linux）
```

このIPアドレスをクライアントPCのセットアップで使います。

### 2-3. クライアントPCのセットアップ

クライアントPCには **Python も Docker も不要** です。

#### 方法1: セットアップスクリプトを使う

`setup_client_docker.bat` をクライアントPCで実行するだけです。

1. サーバーPC または GitHub から `setup_client_docker.bat` を取得
2. ダブルクリックして実行
3. サーバーPCのIPアドレスを入力
4. デスクトップに「ケンモチ電機」ショートカットが作成される

#### 方法2: 手動でアクセス

ブラウザで `http://サーバーIP/` を開くだけです。ブックマークしておけば次回からすぐアクセスできます。

### 2-4. アプリの URL 一覧（Docker版）

| アプリ | URL | 内部ポート |
|--------|-----|-----------|
| ポータル（トップ） | `http://サーバーIP/` | 80 (Nginx) |
| 入札案件管理 | `http://サーバーIP/bid/` | 8501 |
| 材料管理 | `http://サーバーIP/material/` | 5000 |
| 作業日報 | `http://サーバーIP/nippou/` | 8502 |
| 人事評価 | `http://サーバーIP/eval/` | 8503 |
| 営業管理（オプション） | `http://サーバーIP/eigyo/` | 8504 |
| 勤怠管理（オプション） | `http://サーバーIP/nippou-kanri/` | 8510 |

### 2-5. 環境変数の設定（メール通知等を使う場合）

`.env.example` をコピーして `.env` を作成し、必要な項目を設定します。

```bash
cp .env.example .env
```

| 変数 | 用途 | 必須 |
|------|------|------|
| `GMAIL_USER` | Gmail アドレス | メール通知を使う場合 |
| `GMAIL_PASSWORD` | Gmail アプリパスワード | メール通知を使う場合 |
| `BID_EMAIL_TO` | 入札通知の送信先 | 入札通知を使う場合 |
| `NIPPOU_EMAIL_TO` | 日報通知の送信先 | 日報通知を使う場合 |
| `ANTHROPIC_API_KEY` | Claude API キー | 営業管理の自動抽出を使う場合 |

`.env` を変更したら、反映するために再起動してください:

```bash
./docker/manage.sh restart    # Linux
docker\manage.bat restart     # Windows
```

---

## 3. 方法B: 従来方式（各PCにインストール）

1台のPCだけで試す場合や、Docker が使えない環境向けです。

### 3-1. 必要なソフト

| ソフト | ダウンロード先 | 注意点 |
|--------|---------------|--------|
| **Python 3.11 以上** | https://www.python.org/downloads/ | インストール時に **「Add Python to PATH」に必ずチェック** |
| **Git**（任意） | https://git-scm.com/downloads | 自動アップデートを使う場合のみ |

> **注意**: Python パッケージのインストールに RAM 4GB 以上、ディスク空き 2GB 以上が必要です。低スペックPCではフリーズする場合があります。

### 3-2. ダウンロード

**方法1: Git Clone（自動アップデートあり）**

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
```

**方法2: GitHub Releases からダウンロード**

[Releases ページ](https://github.com/mstk13/KEM_DDENKI/releases) から最新の zip をダウンロードし展開。

### 3-3. 初回セットアップ

**Windows:**
```powershell
cd KEM_DDENKI
.\setup.bat
```

**Mac / Linux:**
```bash
cd KEM_DDENKI
chmod +x setup.sh start_all.sh
./setup.sh
```

### 3-4. 起動

**Windows:** `start.bat` をダブルクリック

**Mac / Linux:** `./start_all.sh`

### 3-5. アプリの URL 一覧（従来方式）

| アプリ | URL |
|--------|-----|
| 入札案件管理 | http://localhost:8501 |
| 材料管理 | http://localhost:5000 |
| 作業日報 | http://localhost:8502 |
| 人事評価 | http://localhost:8503 |
| 営業管理（オプション） | http://localhost:8504 |
| 勤怠管理（オプション） | http://localhost:8510 |

### 3-6. データの保存場所

全アプリのデータベースは **デフォルトでプロジェクト直下の `data/` フォルダ** に集約されます（設定不要）。

```
KEM_DDENKI/
└── data/
    ├── bid_manager.db       ← 入札案件管理
    ├── material_manager.db  ← 材料管理
    ├── sagyo_nippou.db      ← 作業日報
    ├── evaluation.db        ← 人事評価
    └── eigyo_kanri.db       ← 営業管理
```

複数PCでデータを共有する場合は、`.env` ファイルに `KEM_DATA_DIR` を設定してください:

```dotenv
KEM_DATA_DIR=\\192.168.0.27\kem_data
```

データを共有する **全てのPC** で同じパスを設定してください。

> **注意**: SQLite は同時書き込みに制限があります。少人数（5名程度まで）であれば通常は問題ありません。複数PCで使う場合は [Docker版（方法A）](#2-方法a-docker-で一括セットアップ推奨) を推奨します。

---

## 4. アプリの起動・停止・管理

### Docker版

管理スクリプト `docker/manage.sh`（Linux）または `docker\manage.bat`（Windows）を使います。

| コマンド | 動作 |
|---------|------|
| `./docker/manage.sh start` | 全アプリ起動 |
| `./docker/manage.sh stop` | 全アプリ停止 |
| `./docker/manage.sh restart` | 全アプリ再起動 |
| `./docker/manage.sh restart bid_manager` | 入札管理だけ再起動 |
| `./docker/manage.sh status` | 稼働状況の確認 |
| `./docker/manage.sh update` | 最新版に更新 |
| `./docker/manage.sh logs` | 全アプリのログ |
| `./docker/manage.sh logs bid_manager` | 入札管理のログだけ |
| `./docker/manage.sh backup` | DBバックアップ |
| `./docker/manage.sh optional` | オプションアプリも含めて起動 |

### 従来方式

- **起動**: `start.bat`（Windows）/ `./start_all.sh`（Linux/Mac）
- **停止**: `Ctrl+C` またはウィンドウを閉じる

---

## 5. 自動アップデート

### Docker版

セットアップ時に **毎朝 5:00 に自動更新** が設定されます（Linux の場合）。

- GitHub の最新コードを取得
- 変更があればアプリを自動で再ビルド・再起動
- 変更がなければ何もしない

手動で今すぐ更新したい場合:

```bash
./docker/manage.sh update
```

### 従来方式

Git Clone でインストールした場合、`start.bat` / `start_all.sh` の起動時に自動で `git pull` します。

---

## 6. リリースの作成方法（管理者向け）

GitHub にタグを push すると、自動で Release が作成されます。

```bash
git tag v2.0.0
git push origin v2.0.0
```

GitHub Actions が自動で zip ファイルを作成し、Releases ページに公開します。

---

## 7. トラブルシューティング

### Docker版

| 症状 | 対処 |
|------|------|
| Docker Desktop が起動しない | Windows の場合、Hyper-V と WSL2 が有効か確認 |
| `docker compose up` でエラー | `docker compose logs` でエラー内容を確認 |
| 特定のアプリだけ動かない | `./docker/manage.sh logs アプリ名` でログを確認 |
| 他のPCからアクセスできない | サーバーPCのファイアウォールでポート 80 を許可 |
| データが消えた | Docker ボリューム `kem_data` にデータが保存されている。`docker volume ls` で確認 |

### 従来方式

| 症状 | 対処 |
|------|------|
| `python` が見つからない | `py` に置き換えて試す。Python を再インストール（PATH にチェック） |
| `pip install` でフリーズする | RAM 不足の可能性。Docker版への移行を推奨 |
| `streamlit` が見つからない | `py -m streamlit run app.py` を使う |
| 他のPCからアクセスできない | ファイアウォールでポート 5000, 8501-8503 を許可 |

---

## 8. GEPS メール連携

入札案件管理でGEPS（政府電子調達）のメール通知を取り込む設定は [geps_setup.md](geps_setup.md) を参照してください。

---

## 9. 入札案件スクレイピング機能のセットアップ

入札情報サービス (i-ppi.jp) から入札案件を自動取得する機能です。  
Playwright（ヘッドレスブラウザ）を使ってフォーム入力→検索→結果取得を自動化します。

### 9.1 前提条件

- Python 3.12 以上
- Django SaaS が起動できる状態（`python manage.py runserver` が通ること）
- インターネット接続（i-ppi.jp へアクセスするため）

### 9.2 Playwright のインストール

```bash
# 1. venv に入る（すでに入っている場合はスキップ）
cd saas
source .venv/bin/activate      # Linux/Mac
# .venv\Scripts\activate       # Windows

# 2. pip で playwright をインストール
pip install playwright

# 3. Chromium ブラウザをダウンロード（約 150MB）
playwright install chromium

# ※ Linux サーバーの場合、システム依存パッケージも必要:
playwright install-deps chromium
```

**Windows の場合:**
```powershell
cd saas
.venv\Scripts\activate
pip install playwright
playwright install chromium
```

### 9.3 マイグレーション

ScrapeTarget モデルにフィールドが追加されているため、マイグレーションを実行してください。

```bash
cd saas
python manage.py makemigrations bids
python manage.py migrate
```

### 9.4 使い方

#### A. Web UI から実行

1. サイドバーの **入札 → 案件取得** を開く
2. 「+ 対象を追加」でスクレイピング条件を登録
   - **名称**: 任意（例: 「関東・電気工事」）
   - **工事名キーワード**: 検索キーワード（例: 「電気設備」）
   - **地域（地方）**: 北海道〜沖縄から選択
   - **都道府県**: 任意（例: 「千葉県」）
   - **工事種別**: 例: 電気
   - **過去N日以内の更新**: デフォルト 30日
3. 一覧に戻り「実行」ボタンを押すとスクレイピングが開始
4. 結果をプレビューし、「全件インポート」で入札案件一覧に登録

#### B. コマンドラインから実行

```bash
cd saas

# 有効な全対象を実行
python manage.py scrape_bids

# 特定のターゲットIDのみ実行
python manage.py scrape_bids --target 1

# 取得だけして DB に保存しない（テスト用）
python manage.py scrape_bids --dry-run

# ブラウザを表示して実行（デバッグ用）
python manage.py scrape_bids --visible
```

### 9.5 Docker 環境での注意

Docker コンテナ内で Playwright を使う場合、Dockerfile に以下を追加する必要があります:

```dockerfile
RUN pip install playwright && playwright install chromium && playwright install-deps chromium
```

### 9.6 トラブルシューティング

| 症状 | 対処 |
|------|------|
| `playwright._impl._errors.Error: Executable doesn't exist` | `playwright install chromium` を実行 |
| Linux で起動しない | `playwright install-deps chromium` でシステム依存パッケージをインストール |
| タイムアウトする | ネットワーク接続を確認。i-ppi.jp が落ちている可能性もある |
| 検索結果が 0 件 | 検索条件を広げる（キーワードを短く、地域を「なし」にする等） |
| フォーム構造が変わった | i-ppi.jp の画面改修でセレクタが変わった可能性。`scraper.py` を調整 |

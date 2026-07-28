# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

電気工事の業務フローを一気通貫でカバーする社内Webアプリ群です。

---

## セットアップ手順（他のPCで立ち上げる方法）

Docker を使えば、**サーバーPC 1台にセットアップするだけ**で、  
他のPCはブラウザでアクセスするだけで全アプリが使えます。

```
他のPC（何台でも）                サーバーPC（1台）
┌───────────────┐             ┌──────────────────────────┐
│ ブラウザだけ    │             │  Docker が全アプリを実行   │
│ インストール不要 │── LAN ──→ │                          │
│               │             │  http://サーバーIP/       │
│               │             │  DB・データはすべてここに  │
└───────────────┘             └──────────────────────────┘
```

---

### Step 0: サーバーPCの準備

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 Pro、Linux（Ubuntu推奨）、Mac |
| RAM | 8 GB 以上 |
| ディスク空き | 5 GB 以上 |
| ネットワーク | 社内LANに接続（固定IP推奨） |

---

### Step 1: Git をインストールする

コマンドプロンプトで `git --version` と打って表示されればOKです。  
表示されない場合はインストールしてください。

- **Windows**: https://gitforwindows.org/ からダウンロードしてインストール
  - インストール中の選択肢はすべてデフォルトのままで大丈夫です
- **Linux（Ubuntu）**: `sudo apt install git`
- **Mac**: `xcode-select --install`

---

### Step 2: Docker をインストールする

#### Windows の場合

1. https://www.docker.com/products/docker-desktop/ を開く
2. 「Download for Windows」をクリックしてインストーラをダウンロード
3. ダウンロードした `Docker Desktop Installer.exe` を実行
4. インストールが完了したら **PCを再起動**
5. 再起動後、Docker Desktop が自動で起動する（タスクバーにクジラのアイコンが出る）
6. 初回はアカウント作成を求められますが、「Continue without signing in」でスキップ可能

> **注意**: Windows Home では WSL2 が必要です。  
> Docker Desktop のインストーラが自動で案内してくれるので、指示に従ってください。

#### Linux（Ubuntu）の場合

下の Step 3 のスクリプトが **Docker を自動でインストール** するので、手動でのインストールは不要です。

もし手動でやる場合:
```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER
# ログアウトして再ログイン
```

#### Mac の場合

1. https://www.docker.com/products/docker-desktop/ を開く
2. 「Download for Mac」をクリックしてインストール
3. アプリケーションフォルダの Docker を起動

#### インストール確認

コマンドプロンプト（またはターミナル）で以下を実行:

```bash
docker --version
```

`Docker version 27.x.x` のように表示されればOKです。

---

### Step 3: アプリをセットアップする

```bash
# 1. リポジトリを取得
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# 2. セットアップ実行（全アプリのビルド・起動を自動で行います。初回は数分かかります）
./docker/setup_server.sh      # Linux / Mac / WSL
# docker\setup_server.bat     # Windows
```

以上で完了です。

---

### Step 4: 動作確認

ブラウザで **http://localhost/** を開き、ポータルページが表示されれば成功です。

---

### Step 5: 他のPCからアクセスする

サーバーPCのIPアドレスを確認します:

```bash
ipconfig        # Windows
hostname -I     # Linux
```

例えばIPが `192.168.0.27` なら、他のPCのブラウザで **http://192.168.0.27/** を開くだけです。  
ブックマークしておけば次回からすぐアクセスできます。

デスクトップにショートカットを作りたい場合は、`setup_client_docker.bat` を他のPCで実行してください。

---

### 管理コマンド（サーバーPCで実行）

```bash
./docker/manage.sh status             # 稼働状況を確認
./docker/manage.sh stop               # 全アプリ停止
./docker/manage.sh start              # 全アプリ起動
./docker/manage.sh restart evaluation  # 特定アプリだけ再起動
./docker/manage.sh update             # GitHubから最新版に更新
./docker/manage.sh logs bid_manager   # ログ確認
./docker/manage.sh backup             # DBバックアップ
```

> 毎朝5時にGitHubから自動更新されます。

---

## アプリ一覧

| アプリ | Docker URL | 概要 |
|--------|-----------|------|
| 入札案件管理 | `/bid/` | 案件収集・進捗管理・費用分析・競合分析 |
| 材料管理 | `/material/` | 見積もり vs 発注の消化率追跡 |
| 作業日報 | `/nippou/` | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | `/eval/` | アンケート方式の評価入力 |
| 人事評価（管理） | `/eval-admin/` | 結果閲覧・自己vs他己比較・PDF出力 |
| 営業管理 | `/eigyo/` | 訪問記録・資料自動抽出（Claude API） |
| 日報管理 | `/nippou-kanri/` | 勤怠テキスト抽出・集計 |
| ポータル | `/` | 全アプリへのランチャーページ |

### データの流れ

```
入札案件管理（案件収集・入札）
    ↓ 受注
材料管理（見積もり→発注→受領の追跡）
    ↓ 施工中
作業日報（作業員・時間・交通費の記録）
    ↓                ↓
人事評価（勤怠データ連携）  コスト分析・AI見積もり ← 将来
```

---

## Docker を使わない場合

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
./setup.sh          # 初回セットアップ（Linux/Mac/WSL）
./start_all.sh      # 全アプリ起動
# Windows: setup.bat → start.bat
```

ブラウザで `http://localhost:8080` を開くとポータルが表示されます。  
詳細は [docs/setup_guide.md](docs/setup_guide.md) を参照。

---

## 開発者向け（個別起動）

各アプリは独立しており、1つだけ起動してテスト・修正できます。

```bash
source .venv/bin/activate     # Linux/Mac
# .venv\Scripts\activate      # Windows
```

| アプリ | 起動コマンド |
|--------|------------|
| 入札案件管理 | `cd bid_manager && python database.py && streamlit run app.py --server.port 8501` |
| 材料管理 | `cd material_manager && python -c "from db import init_db; init_db()" && python app.py` |
| 作業日報 | `cd sagyo-nippou && python database.py && streamlit run app.py --server.port 8502` |
| 人事評価（入力） | `cd evaluation && streamlit run app.py --server.port 8504` |
| 人事評価（管理） | `cd evaluation && streamlit run admin_app.py --server.port 8505` |
| 営業管理 | `cd eigyo-kanri && python database.py && streamlit run app.py --server.port 8503` |
| 日報管理 | `cd nippou-kanri && python database.py && streamlit run app.py --server.port 8510` |

> 詳細は [docs/DEVELOPER.md](docs/DEVELOPER.md) を参照

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/setup_guide.md](docs/setup_guide.md) | セットアップ詳細・トラブルシューティング |
| [docs/DEVELOPER.md](docs/DEVELOPER.md) | 開発者向け: 個別開発・テスト・新アプリ追加手順 |
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ |
| [docs/process.md](docs/process.md) | 業務プロセスフロー |

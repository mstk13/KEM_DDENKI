# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

電気工事の業務フローを一気通貫でカバーする社内Webアプリ群です。

---

## はじめに — 立ち上げ方法

用途に合わせて **3つの方法** があります。

### 方法1: サーバー1台＋ブラウザだけ（推奨）

1台のPCで全アプリを動かし、他のPCはブラウザでアクセスするだけの構成です。  
**データは自動的に全PCで共有されます。**

```
他のPC（何台でも）                サーバーPC（1台）
┌───────────────┐             ┌────────────────────────┐
│ ブラウザだけ    │             │  全アプリが動いている    │
│ インストール不要 │── LAN ──→ │                        │
│               │             │  http://サーバーIP:8080 │
│               │             │  DBはすべてここに保存    │
└───────────────┘             └────────────────────────┘
```

**サーバーPCのセットアップ（初回のみ）:**

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# Linux / Mac / WSL
./setup.sh          # 仮想環境の作成・パッケージ・DB初期化を一括で行う

# Windows
setup.bat
```

**アプリの起動:**

```bash
# Linux / Mac / WSL
./start_all.sh      # 全アプリを一括起動（起動時にGitHubから自動更新）

# Windows
start.bat
```

起動後、ブラウザで `http://localhost:8080` を開くとポータルが表示されます。  
**他のPCからは `http://サーバーのIPアドレス:8080`** でアクセスできます。

> サーバーPCの要件: Python 3.11以上、RAM 8GB以上、ディスク空き 5GB以上

---

### 方法2: 複数PCでDBを共有して使う

各PCでアプリを起動しつつ、**データだけをネットワーク共有フォルダで共有**する構成です。

```
PC-A                          PC-B
┌───────────────┐             ┌───────────────┐
│ アプリを起動    │             │ アプリを起動    │
│ http://        │             │ http://        │
│ localhost:8080 │             │ localhost:8080 │
└──────┬────────┘             └──────┬────────┘
       │                             │
       └──────────┬──────────────────┘
                  ↓
       ┌─────────────────┐
       │ 共有フォルダ      │
       │ \\サーバー\kem_data │
       │ (DBファイル一式)  │
       └─────────────────┘
```

**手順:**

1. ネットワーク共有フォルダを用意する（例: `\\192.168.0.27\kem_data`）
2. 各PCで `.env` ファイルを作成し、共有フォルダのパスを指定する:

```bash
cp .env.example .env
```

`.env` を編集:
```
# Windows の共有フォルダの場合
KEM_DATA_DIR=\\192.168.0.27\kem_data

# Linux / Mac の NFS/SMB マウントの場合
KEM_DATA_DIR=/mnt/shared/kem_data
```

3. 各PCで `setup.sh`（または `setup.bat`）→ `start_all.sh`（または `start.bat`）

> **注意:** SQLiteはネットワークドライブ上での同時書き込みに弱いため、  
> 同じアプリに複数人が同時にデータを書き込むと稀にエラーになる場合があります。  
> 本格運用には方法1（サーバー集中）を推奨します。

---

### 方法3: Docker で本番運用する

Docker を使うとポート管理が不要になり、Nginxが全アプリをポート80に集約します。

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# Linux
./docker/setup_server.sh

# Windows（要 Docker Desktop）
docker\setup_server.bat
```

他のPCからは `http://サーバーIP/` でアクセス。詳細は [docs/setup_guide.md](docs/setup_guide.md) を参照。

---

## アプリ一覧

| アプリ | ポート | 概要 |
|--------|--------|------|
| **入札案件管理** | 8501 | 案件収集・進捗管理・費用分析・競合分析 |
| **材料管理** | 5000 | 見積もり vs 発注の消化率追跡 |
| **作業日報** | 8502 | 日報入力・作業員管理・月次集計 |
| **人事評価（入力）** | 8504 | アンケート方式の評価入力 |
| **人事評価（管理）** | 8505 | 結果閲覧・自己vs他己比較・PDF出力 |
| **営業管理** | 8503 | 訪問記録・資料自動抽出（Claude API） |
| **日報管理** | 8510 | 勤怠テキスト抽出・集計 |
| **ポータル** | 8080 | 全アプリへのランチャーページ |

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

## 個別にアプリを起動する（開発者向け）

各アプリは独立しており、1つだけ起動してテスト・修正できます。

```bash
# 仮想環境を有効化
source .venv/bin/activate     # Linux/Mac
# .venv\Scripts\activate      # Windows

# 例: 人事評価の入力アプリだけ起動
cd evaluation
pip install -r requirements.txt
streamlit run app.py --server.port 8504
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

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/setup_guide.md](docs/setup_guide.md) | セットアップ詳細・Docker運用・トラブルシューティング |
| [docs/DEVELOPER.md](docs/DEVELOPER.md) | 開発者向け: 個別開発・テスト・新アプリ追加手順 |
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ |
| [docs/process.md](docs/process.md) | 業務プロセスフロー |

# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

電気工事の業務フローを一気通貫でカバーする社内Webアプリ群です。

---

## セットアップ（他のPCで立ち上げる方法）

### 推奨: Docker で一発セットアップ

Python のインストールや仮想環境の構築は不要です。  
Docker さえあれば **コマンド2つ** で全アプリが起動します。

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
./docker/setup_server.sh      # Linux / Mac / WSL
# docker\setup_server.bat     # Windows（要 Docker Desktop）
```

これだけで:
- 全アプリのビルド・起動が自動で行われる
- Nginx がポート **80** で一括受付し、パスで各アプリに振り分ける
- 毎朝5時に GitHub から自動更新される（cron登録済み）
- DBは Docker ボリューム（`kem_data`）に保存される

**起動後、ブラウザで `http://localhost/` を開けばポータルが表示されます。**  
他のPCからは `http://サーバーのIPアドレス/` でアクセスできます（ブラウザだけでOK）。

```
他のPC（何台でも）                サーバーPC（1台）
┌───────────────┐             ┌──────────────────────────┐
│ ブラウザだけ    │             │  Docker が全アプリを実行   │
│ インストール不要 │── LAN ──→ │                          │
│               │             │  http://サーバーIP/       │
│               │             │    /bid/     入札案件管理  │
│               │             │    /material/ 材料管理    │
│               │             │    /nippou/  作業日報     │
│               │             │    /eval/    人事評価入力  │
│               │             │    /eval-admin/ 人事評価管理│
│               │             │                          │
│               │             │  DB・データはすべてここに  │
└───────────────┘             └──────────────────────────┘
```

#### 管理コマンド

```bash
./docker/manage.sh start              # 全アプリ起動
./docker/manage.sh stop               # 全アプリ停止
./docker/manage.sh restart evaluation  # 特定アプリだけ再起動
./docker/manage.sh status             # 稼働状況
./docker/manage.sh update             # 最新版に更新
./docker/manage.sh logs bid_manager   # ログ確認
./docker/manage.sh backup             # DBバックアップ
```

#### サーバーPCの要件

| 項目 | 要件 |
|------|------|
| OS | Windows 10/11 Pro、Linux、Mac |
| Docker | Docker Desktop（Windows/Mac）または Docker Engine（Linux） |
| RAM | 8 GB 以上 |
| ディスク空き | 5 GB 以上 |

---

### Docker を使わない場合

Python を直接使って起動することもできます。

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# 初回セットアップ（仮想環境作成・パッケージ・DB初期化を一括実行）
./setup.sh          # Linux / Mac / WSL
# setup.bat         # Windows

# 起動（起動時にGitHubから自動更新も行われる）
./start_all.sh      # Linux / Mac / WSL
# start.bat         # Windows
```

ブラウザで `http://localhost:8080` を開くとポータルが表示されます。  
他のPCからは `http://サーバーIP:8080` でアクセスできます。

#### 複数PCでDBを共有する場合

`.env` ファイルでDBの保存先をネットワーク共有フォルダに変更できます。

```bash
cp .env.example .env
```

`.env` を編集:
```
KEM_DATA_DIR=\\192.168.0.27\kem_data    # Windows 共有フォルダ
# KEM_DATA_DIR=/mnt/shared/kem_data     # Linux NFS/SMBマウント
```

> SQLite はネットワークドライブでの同時書き込みに弱いため、  
> 本格運用ではサーバー1台で動かす方式（Docker推奨）をおすすめします。

---

## アプリ一覧

| アプリ | ポート | Docker パス | 概要 |
|--------|--------|------------|------|
| 入札案件管理 | 8501 | `/bid/` | 案件収集・進捗管理・費用分析・競合分析 |
| 材料管理 | 5000 | `/material/` | 見積もり vs 発注の消化率追跡 |
| 作業日報 | 8502 | `/nippou/` | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | 8504 | `/eval/` | アンケート方式の評価入力 |
| 人事評価（管理） | 8505 | `/eval-admin/` | 結果閲覧・自己vs他己比較・PDF出力 |
| 営業管理 | 8503 | `/eigyo/` | 訪問記録・資料自動抽出（Claude API） |
| 日報管理 | 8510 | `/nippou-kanri/` | 勤怠テキスト抽出・集計 |
| ポータル | 8080 / 80 | `/` | 全アプリへのランチャーページ |

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
| [docs/setup_guide.md](docs/setup_guide.md) | セットアップ詳細・Docker運用・トラブルシューティング |
| [docs/DEVELOPER.md](docs/DEVELOPER.md) | 開発者向け: 個別開発・テスト・新アプリ追加手順 |
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ |
| [docs/process.md](docs/process.md) | 業務プロセスフロー |

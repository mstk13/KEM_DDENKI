# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

株式会社ケンモチ電機向けの社内Webアプリ群です。  
入札案件の収集から材料管理・作業日報まで、電気工事の業務フローを一気通貫でカバーします。

---

## クイックスタート

### ユーザーとして使う（アプリを使うだけの人）

サーバーPCが既にセットアップ済みなら、**ブラウザで `http://サーバーIP/` を開くだけ** です。  
インストールは不要です。

デスクトップショートカットを作りたい場合は、`setup_client_docker.bat` を実行してください。

### サーバーを新規にセットアップする

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# Windows
docker\setup_server.bat

# Linux
./docker/setup_server.sh
```

ブラウザで `http://localhost/` を開き、ポータルが表示されれば完了です。

> 詳細は **[セットアップガイド](docs/setup_guide.md)** を参照

### 開発者として参加する

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# 仮想環境を作成
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
# .venv\Scripts\activate      # Windows

# 開発したいアプリの依存パッケージをインストール
pip install -r bid_manager/requirements.txt    # 例: 入札案件管理

# DB初期化 → 起動
cd bid_manager
python database.py
streamlit run app.py --server.port 8501
```

> 詳細は **[開発者ガイド](docs/DEVELOPER.md)** を参照

---

## アプリ一覧

| # | アプリ | ディレクトリ | フレームワーク | ポート | Docker パス | 概要 |
|---|--------|-------------|---------------|--------|------------|------|
| 1 | [入札案件管理](#1-入札案件管理-bid_manager) | `bid_manager/` | Streamlit | 8501 | `/bid/` | 入札案件の収集・進捗管理・費用分析・競合分析 |
| 2 | [材料管理](#2-材料管理-material_manager) | `material_manager/` | Flask | 5000 | `/material/` | 現場ごとの見積もり vs 発注状況の比較管理 |
| 3 | [作業日報](#3-作業日報-sagyo-nippou) | `sagyo-nippou/` | Streamlit | 8502 | `/nippou/` | 現場の作業日報の入力・管理・集計・分析 |
| 4 | [人事評価](#4-人事評価-evaluation) | `evaluation/` | Streamlit | 8503 | `/eval/` | 作業日報連携の人事評価（事務方・現場方・役員） |
| 5 | 営業管理 | `eigyo-kanri/` | Streamlit | 8504 | `/eigyo/` | 営業訪問記録・Claude API 自動抽出（オプション） |
| 6 | 勤怠管理 | `nippou-kanri/` | Streamlit | 8510 | `/nippou-kanri/` | 日報テキスト解析・勤怠集計（オプション） |
| — | ポータル | `portal/` | 静的HTML | 8080 | `/` | 全アプリへのランチャーページ |
| — | Nginx | `docker/` | Nginx | 80 | — | リバースプロキシ（Docker版のみ） |
| — | コスト分析・AI見積もり | （開発予定） | — | — | — | 過去実績から見積もりを自動生成 |

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

## ドキュメント

| ドキュメント | 対象者 | 内容 |
|-------------|--------|------|
| **[docs/setup_guide.md](docs/setup_guide.md)** | ユーザー / 管理者 | セットアップ（Docker推奨 / 従来方式）・運用・管理コマンド・トラブルシューティング |
| **[docs/DEVELOPER.md](docs/DEVELOPER.md)** | 開発者 | 各アプリの個別開発・テスト方法、インフラとアプリの開発分離、新アプリ追加手順 |
| [docs/spec.md](docs/spec.md) | 開発者 | システム仕様書（DB設計・機能仕様・AI活用計画） |
| [docs/geps_setup.md](docs/geps_setup.md) | 管理者 | GEPS メール連携のセットアップ手順 |
| [docs/process.md](docs/process.md) | 全員 | 業務プロセスフロー |

---

## ポート一覧

| ポート | アプリ | 用途 |
|--------|--------|------|
| **80** | Nginx | リバースプロキシ（Docker版のみ。クライアントはこのポートだけでアクセス） |
| **5000** | 材料管理 | Flask アプリ |
| **8080** | ポータル | ランチャーページ（WSL/LAN モードのみ） |
| **8501** | 入札案件管理 | Streamlit アプリ |
| **8502** | 作業日報 | Streamlit アプリ |
| **8503** | 人事評価 | Streamlit アプリ |
| **8504** | 営業管理 | Streamlit アプリ（オプション） |
| **8510** | 勤怠管理 | Streamlit アプリ（オプション） |

> Docker 版ではクライアントからポート番号を意識する必要はありません（Nginx がポート 80 で一括受付し、パスベースで各アプリに振り分けます）。

---

## 環境構築

### A. ユーザー向け（Docker で全アプリを一括起動）

複数PCでデータを共有して使う場合の推奨構成です。

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

#### サーバーPCの要件

| 項目 | 最低要件 |
|------|---------|
| OS | Windows 10/11 Pro または Linux |
| RAM | 8 GB 以上 |
| ディスク空き | 5 GB 以上 |

#### サーバーセットアップ

```bash
# 1. リポジトリを取得
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# 2. セットアップ実行（Docker未インストールならLinuxでは自動インストール）
./docker/setup_server.sh      # Linux
docker\setup_server.bat        # Windows（要 Docker Desktop）
```

#### クライアントPCセットアップ

Python も Docker も不要です。2つの方法があります:

1. **スクリプトを使う**: `setup_client_docker.bat` を実行 → サーバーIPを入力 → デスクトップにショートカット作成
2. **手動**: ブラウザで `http://サーバーIP/` を開きブックマーク

#### 管理コマンド

```bash
./docker/manage.sh start              # 全アプリ起動
./docker/manage.sh stop               # 全アプリ停止
./docker/manage.sh restart bid_manager # 特定アプリだけ再起動
./docker/manage.sh status             # 稼働状況
./docker/manage.sh update             # 最新版に更新
./docker/manage.sh logs bid_manager   # ログ確認
./docker/manage.sh backup             # DBバックアップ
```

> 毎朝5時に自動更新されます（Linux cron）。

---

### B. 開発者向け（各アプリを個別に起動）

各アプリは独立しており、**1つのアプリだけ** を起動してテスト・修正できます。  
Docker は不要です。

#### 開発環境セットアップ

```bash
# 1. リポジトリを取得
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# 2. 仮想環境を作成・有効化
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
# .venv\Scripts\activate      # Windows

# 3. 開発対象のアプリだけインストール
pip install -r bid_manager/requirements.txt
```

#### 各アプリの起動方法

| アプリ | ポート | コマンド |
|--------|--------|---------|
| 入札案件管理 | 8501 | `cd bid_manager && python database.py && streamlit run app.py --server.port 8501` |
| 材料管理 | 5000 | `cd material_manager && python -c "from db import init_db; init_db()" && python app.py` |
| 作業日報 | 8502 | `cd sagyo-nippou && python database.py && streamlit run app.py --server.port 8502` |
| 人事評価 | 8503 | `cd evaluation && streamlit run app.py --server.port 8503` |
| 営業管理 | 8504 | `cd eigyo-kanri && python database.py && streamlit run app.py --server.port 8504` |
| 勤怠管理 | 8510 | `cd nippou-kanri && python database.py && streamlit run app.py --server.port 8510` |

#### 開発のルール

- 各アプリは **互いにPythonコードをimportしない**（データ連携はSQLiteファイル経由）
- DB パスは `KEM_DATA_DIR` 環境変数に対応させること
- `requirements.txt` にはバージョン上限を付ける（例: `streamlit>=1.30,<2.0`）
- デモデータは `seed.py` で提供する

> 各アプリの詳しい構成・テスト手順・注意点は **[開発者ガイド](docs/DEVELOPER.md)** を参照

---

## ディレクトリ構成

```
KEM_DDENKI/
├── bid_manager/        # 入札案件管理（Streamlit, port 8501）
├── material_manager/   # 材料管理（Flask, port 5000）
├── sagyo-nippou/       # 作業日報（Streamlit, port 8502）
├── evaluation/         # 人事評価（Streamlit, port 8503）
├── eigyo-kanri/        # 営業管理（Streamlit, オプション）
├── nippou-kanri/       # 勤怠管理（Streamlit, オプション）
├── portal/             # ポータルページ（静的HTML）
│
├── docker/             # Docker 設定・管理スクリプト
│   ├── Dockerfile.app  # 全アプリ共通イメージ
│   ├── nginx.conf      # リバースプロキシ設定
│   ├── manage.sh/bat   # 管理コマンド
│   ├── setup_server.*  # サーバー初回セットアップ
│   ├── update-cron.sh  # 自動更新
│   └── portal/         # Docker版ポータルページ
├── docker-compose.yml  # サービス定義
│
├── docs/               # ドキュメント
│   ├── setup_guide.md  # ユーザー向けセットアップガイド
│   ├── DEVELOPER.md    # 開発者ガイド
│   ├── spec.md         # システム仕様書
│   ├── geps_setup.md   # GEPS メール連携
│   └── process.md      # 業務プロセスフロー
│
├── .env.example        # 環境変数テンプレート
├── setup.bat / .sh     # 従来方式セットアップ
├── start.bat / .sh     # 従来方式起動
└── setup_client_docker.bat  # クライアントPC用ショートカット作成
```

---

## 1. 入札案件管理 (`bid_manager/`)

電気工事の入札案件を収集・管理・分析するWebアプリ。

### 主な機能

- **案件自動収集**: GEPS（政府電子調達）通知メール + Webスクレイピング
- **ステータス管理**: 新着 → 検討中 → 見積作成中 → 入札済 → 受注/失注
- **費用分析**: 見積金額 vs 実原価の利益率・原価率を自動計算
- **競合分析**: 落札会社名・金額を記録し、自社との差額を分析
- **入札参加資格管理**: Excel/PDFインポート、期限2ヶ月前から警告表示
- **メール通知**: 新着案件・締切間近・資格期限のアラートを自動送信

> GEPS メール連携の詳細は [docs/geps_setup.md](docs/geps_setup.md) を参照

---

## 2. 材料管理 (`material_manager/`)

工事現場ごとに、見積もりの品目と実際の発注状況を比較管理するWebアプリ。

### 主な機能

- **見積もり管理**: Excelインポートで品目別の見積もり明細を登録（版管理対応）
- **発注追跡**: 分割発注に対応、品目クリックで発注履歴をドリルダウン
- **消化率の可視化**: 見積もり vs 発注の消化率を色分け表示（超過:赤 / 完了:緑）
- **発注書PDFインポート**: PDFから発注内容を自動マッチング
- **受領書アップロード**: 現場での受領確認を記録
- **単価履歴の自動蓄積**: 将来のAI見積もり自動生成に向けたデータ蓄積

---

## 3. 作業日報 (`sagyo-nippou/`)

電気工事現場の作業日報を入力・管理・分析するWebアプリ。

### 主な機能

- **日報入力**: 現場名・作業員・作業時間・残業・宿泊・使用資材を記録
- **音声入力対応**: スマホのマイク入力で現場から直接入力可能
- **協力会社管理**: 会社名・人数・交通費・承認状況を記録
- **ダッシュボード**: KPIカード + Plotlyグラフ（日別推移・作業員別・現場別）
- **メール通知**: 日報サマリをGmailで自動送信

---

## 4. 人事評価 (`evaluation/`)

事務方・現場方・役員の3役割で人事評価を行うWebアプリ。

### 主な機能

- **作業日報連携**: 対象者の勤怠データを自動取得し、参考スコアを自動計算
- **3役割の評価基準**: 共通項目（35点）+ 役割固有項目（65点）= 100点満点
- **評価ランク自動判定**: S / A / B / C / D
- **評価履歴管理**: 過去の評価を一覧表示・詳細確認

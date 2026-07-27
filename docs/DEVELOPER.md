# 開発者ガイド

このドキュメントは、KEM_DDENKI の各アプリの開発・テスト・修正に参加する人向けのガイドです。

---

## 目次

1. [アーキテクチャ概要](#1-アーキテクチャ概要)
2. [開発の2つの領域](#2-開発の2つの領域)
3. [各アプリの個別開発ガイド](#3-各アプリの個別開発ガイド)
4. [インフラ・システム全体の開発ガイド](#4-インフラシステム全体の開発ガイド)
5. [新しいアプリを追加する方法](#5-新しいアプリを追加する方法)
6. [コーディング規約](#6-コーディング規約)

---

## 1. アーキテクチャ概要

```
KEM_DDENKI/
├── bid_manager/        ← 入札案件管理（Streamlit）   ┐
├── material_manager/   ← 材料管理（Flask）           │ 各アプリは独立
├── sagyo-nippou/       ← 作業日報（Streamlit）       │ 個別に開発・テスト可能
├── evaluation/         ← 人事評価（Streamlit）       │
├── eigyo-kanri/        ← 営業管理（Streamlit）       │
├── nippou-kanri/       ← 勤怠管理（Streamlit）       ┘
│
├── docker/             ← Docker設定・管理スクリプト   ┐
├── docker-compose.yml  ← サービス定義                │ インフラ・システム全体
├── portal/             ← ポータルページ              │ （管理者が担当）
├── docs/               ← ドキュメント                ┘
│
├── setup.bat / setup.sh        ← 従来方式セットアップ
├── start.bat / start_all.sh    ← 従来方式起動
└── .env.example                ← 環境変数テンプレート
```

### アプリ間の依存関係

```
bid_manager          独立（依存なし）
material_manager     独立（依存なし）
sagyo-nippou         独立（依存なし）★ 他アプリのデータ元
evaluation       →   sagyo-nippou の DB を読み取り専用で参照
eigyo-kanri          独立（依存なし）
nippou-kanri     →   sagyo-nippou の DB を読み取り専用で参照
```

各アプリ間に **Python コードの import は一切ない**。データ連携は SQLite ファイルの読み取りのみ。

---

## 2. 開発の2つの領域

### アプリ開発（各アプリの担当者）

- 対象: `bid_manager/`, `material_manager/` 等の各ディレクトリ内
- 範囲: UI、ビジネスロジック、DB スキーマ、テスト
- 他のアプリやインフラに影響しない変更
- **各アプリの担当者が独立して作業可能**

### インフラ・システム開発（管理者）

- 対象: `docker/`, `docker-compose.yml`, `portal/`, `docs/`, 起動スクリプト
- 範囲: Docker設定、Nginx、ポータル、デプロイ、DB共有設定
- 全アプリに影響する変更
- **管理者（メンテナー）が担当**

---

## 3. 各アプリの個別開発ガイド

### 共通: ローカルでの個別起動方法

各アプリは **単体で** 起動・テストできます。Docker は不要です。

```bash
# 1. 仮想環境を作成（初回のみ）
python -m venv .venv
source .venv/bin/activate     # Linux/Mac
# .venv\Scripts\activate      # Windows

# 2. 対象アプリの依存パッケージをインストール
pip install -r <アプリ名>/requirements.txt

# 3. DB を初期化（初回のみ）
cd <アプリ名>
python database.py            # または: python -c "from db import init_db; init_db()"

# 4. アプリを起動
streamlit run app.py          # Streamlit アプリの場合
python app.py                 # Flask アプリ（material_manager）の場合
```

### 共通: Docker で個別に再起動

本番環境（Docker）で特定のアプリだけ再起動するには:

```bash
# 例: bid_manager だけ再ビルド・再起動
docker compose up -d --build bid_manager

# ログを確認
docker compose logs -f bid_manager
```

---

### 3-1. 入札案件管理 (bid_manager)

| 項目 | 内容 |
|------|------|
| フレームワーク | Streamlit |
| ポート | 8501 |
| DB | `bid_manager.db`（SQLite） |
| Docker パス | `/bid/` |

#### ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | メインUI（6画面: 案件一覧、新規追加、詳細、分析、資格管理、設定） |
| `database.py` | DBスキーマ定義・CRUD操作・マイグレーション |
| `scraper.py` | Webスクレイピング（requests + BeautifulSoup） |
| `email_importer.py` | GEPS メール通知の Gmail IMAP 取り込み |
| `notifier.py` | Gmail SMTP でのメール通知 |
| `importer.py` | 入札参加資格の Excel/PDF インポート |
| `pw_login.py` | Playwright Cookie 管理（Cloudflare 対応） |
| `scheduler.py` | 定期実行エントリポイント |
| `config.py` | キーワード、地域、カテゴリ、セレクタ設定 |
| `seed.py` | デモデータ投入 |

#### ローカル起動

```bash
cd bid_manager
pip install -r requirements.txt
python database.py
streamlit run app.py --server.port 8501
```

#### テスト方法

1. `python seed.py` でデモデータを投入
2. ブラウザで `http://localhost:8501` を開く
3. 案件一覧 → 詳細画面 → ステータス変更 → 分析画面を順に確認
4. スクレイピングテスト: `python -c "from scraper import scrape_all; scrape_all()"`

#### 環境変数（`.env` で設定）

| 変数 | 用途 |
|------|------|
| `GMAIL_USER` | メール通知の送信元 |
| `GMAIL_PASSWORD` | Gmail アプリパスワード |
| `BID_EMAIL_TO` | 通知先メールアドレス |
| `BID_USE_PLAYWRIGHT` | JS描画サイトのスクレイピング（`true`/`false`） |

---

### 3-2. 材料管理 (material_manager)

| 項目 | 内容 |
|------|------|
| フレームワーク | Flask + Jinja2 テンプレート |
| ポート | 5000 |
| DB | `material_manager.db`（SQLite） |
| Docker パス | `/material/` |

#### ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | Flask ルーティング・ビジネスロジック |
| `db.py` | DBスキーマ・接続管理（Flask g ベース） |
| `cost_analyzer.py` | 品目別コスト分析・仕入先比較 |
| `pdf_generator.py` | 発注書PDF生成（reportlab） |
| `pdf_parser.py` | 発注書PDFの読み取り・自動マッチング |
| `templates/` | Jinja2 HTML テンプレート（14ファイル） |

#### ローカル起動

```bash
cd material_manager
pip install -r requirements.txt
python -c "from db import init_db; init_db()"
python app.py
```

#### テスト方法

1. ブラウザで `http://localhost:5000` を開く
2. 現場登録 → 見積もり Excel インポート → 発注登録 → 消化率確認
3. PDF インポート: 発注書PDFをアップロードして自動マッチングを確認

#### 注意点

- Flask アプリのため、テンプレート HTML の変更も必要になることがある
- `templates/base.html` が共通レイアウト。新画面追加時はここを継承
- Nginx 経由のパスプレフィックスは `ProxyFix` ミドルウェアで処理（`app.py` 16行目）

---

### 3-3. 作業日報 (sagyo-nippou)

| 項目 | 内容 |
|------|------|
| フレームワーク | Streamlit |
| ポート | 8502 |
| DB | `sagyo_nippou.db`（SQLite） |
| Docker パス | `/nippou/` |

#### ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | メインUI（6画面: 日報入力、一覧、現場詳細、ダッシュボード、作業員管理、設定） |
| `database.py` | DBスキーマ・CRUD・マイグレーション |
| `config.py` | 作業種別、天候、ステータス等の定数 |
| `notifier.py` | Gmail SMTP 通知 |
| `seed.py` | デモデータ投入 |

#### ローカル起動

```bash
cd sagyo-nippou
pip install -r requirements.txt
python database.py
streamlit run app.py --server.port 8502
```

#### テスト方法

1. `python seed.py` でデモデータを投入
2. 日報入力画面で作業員・時間・作業内容を入力して保存
3. ダッシュボードで集計グラフを確認
4. 音声入力（ブラウザのマイクアクセスが必要）

#### 重要: 他アプリへの影響

**evaluation と nippou-kanri がこのアプリの DB を読み取ります。**  
DB スキーマを変更する場合は、以下のファイルへの影響を確認してください:

- `evaluation/app.py` — 勤怠データの読み取りクエリ
- `nippou-kanri/importer.py` — 日報データの同期クエリ

---

### 3-4. 人事評価 (evaluation)

| 項目 | 内容 |
|------|------|
| フレームワーク | Streamlit |
| ポート | 8503 |
| DB | `evaluation.db`（SQLite） |
| Docker パス | `/eval/` |
| 依存 | `sagyo_nippou.db` を読み取り専用で参照 |

#### ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | メインUI + DB操作（単一ファイル構成） |
| `eval_items.json` | 評価項目のデフォルト定義 |

#### ローカル起動

```bash
cd evaluation
pip install -r requirements.txt
streamlit run app.py --server.port 8503
```

> sagyo-nippou の DB がない場合も動作しますが、勤怠データの自動参照は機能しません。  
> 完全にテストするには、先に sagyo-nippou を起動してデモデータを入れてください。

#### テスト方法

1. 評価対象者を選択 → 役割（事務方/現場方/役員）を設定
2. 各項目を採点 → 合計スコア・ランク（S〜D）を確認
3. 評価履歴一覧で過去の評価を比較

---

### 3-5. 営業管理 (eigyo-kanri) — オプション

| 項目 | 内容 |
|------|------|
| フレームワーク | Streamlit |
| ポート | 8504 |
| DB | `eigyo_kanri.db`（SQLite） |
| Docker パス | `/eigyo/` |
| 必須環境変数 | `ANTHROPIC_API_KEY`（自動抽出機能を使う場合） |

#### ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | メインUI（4画面: 業種ドリルダウン、登録、ダッシュボード、設定） |
| `database.py` | DBスキーマ・CRUD |
| `extractor.py` | Claude API で PDF/画像/名刺からデータ抽出 |
| `importer.py` | フォルダ監視・インポート CLI |
| `storage.py` | ファイル整理（業種/会社/日付） |
| `config.py` | 設定・ステータス・業種定義 |
| `seed.py` | デモデータ投入 |

#### ローカル起動

```bash
cd eigyo-kanri
pip install -r requirements.txt
python database.py
streamlit run app.py
```

#### テスト方法

1. 手動で訪問記録を追加（API キー不要）
2. 自動抽出テスト: `.env` に `ANTHROPIC_API_KEY` を設定し、PDF/画像をアップロード
3. ダッシュボードで KPI・グラフを確認

---

### 3-6. 勤怠管理 (nippou-kanri) — オプション

| 項目 | 内容 |
|------|------|
| フレームワーク | Streamlit |
| ポート | 8510 |
| DB | `nippou.db`（SQLite） |
| Docker パス | `/nippou-kanri/` |
| 依存 | `sagyo_nippou.db` を読み取り専用で参照 |

#### ファイル構成

| ファイル | 役割 |
|---------|------|
| `app.py` | メインUI（6画面: テキスト抽出、一覧、個人記録、勤怠集計、社員マスタ、設定） |
| `database.py` | DBスキーマ・勤怠計算ロジック |
| `extractor.py` | 日本語テキストからの日報自動解析（NLP） |
| `importer.py` | sagyo-nippou DB との同期 CLI |
| `config.py` | 勤務時間・休憩・丸め設定 |
| `seed.py` | デモデータ投入 |

#### ローカル起動

```bash
cd nippou-kanri
pip install -r requirements.txt
python database.py
streamlit run app.py
```

#### テスト方法

1. テキスト入力画面に日報テキストを貼り付け → 自動解析結果を確認
2. sagyo-nippou 同期: `python importer.py`（sagyo-nippou の DB が必要）
3. 勤怠集計画面で早朝・通常・残業の計算結果を確認

---

## 4. インフラ・システム全体の開発ガイド

この領域は管理者（メンテナー）が担当します。

### 対象ファイル

| ファイル | 役割 | 変更時の影響 |
|---------|------|------------|
| `docker-compose.yml` | サービス定義 | 全アプリの起動方法に影響 |
| `docker/Dockerfile.app` | アプリ共通イメージ | 全アプリの実行環境に影響 |
| `docker/nginx.conf` | リバースプロキシ | 全アプリのURL・アクセスに影響 |
| `docker/entrypoint.sh` | コンテナ起動処理 | DB初期化・アプリ起動に影響 |
| `docker/manage.sh`, `manage.bat` | 管理コマンド | 運用操作に影響 |
| `docker/portal/index.html` | ポータルページ | ユーザーが最初に見る画面 |
| `docker/setup_server.sh`, `.bat` | サーバー初期セットアップ | 新規導入時に影響 |
| `docker/update-cron.sh` | 自動更新 | デプロイに影響 |
| `setup_client_docker.bat` | クライアントセットアップ | クライアントPC導入に影響 |

### 新しいアプリを Docker に追加する手順

1. `docker-compose.yml` に新しいサービスを追加
2. `docker/nginx.conf` に新しい `location` ブロックを追加
3. `docker/portal/index.html` にカードを追加
4. テスト: `docker compose up -d --build <新サービス名>`

### インフラ変更時のテスト手順

```bash
# 1. 全サービスをリビルド
docker compose up -d --build

# 2. 各アプリのURLにアクセスして動作確認
curl -s http://localhost/bid/ | head -5
curl -s http://localhost/material/ | head -5
curl -s http://localhost/nippou/ | head -5
curl -s http://localhost/eval/ | head -5

# 3. ログにエラーがないか確認
docker compose logs --tail=20

# 4. 個別再起動が動作するか確認
docker compose restart bid_manager
docker compose ps
```

---

## 5. 新しいアプリを追加する方法

### Step 1: アプリディレクトリを作成

```
new-app/
├── app.py              # メインアプリ
├── database.py         # DB初期化（init_db() を定義）
├── config.py           # 設定・定数
├── requirements.txt    # 依存パッケージ
└── seed.py             # デモデータ（任意）
```

### Step 2: KEM_DATA_DIR に対応する

`config.py` で共有DBフォルダに対応:

```python
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
_data_dir = os.environ.get("KEM_DATA_DIR")
DB_PATH = Path(_data_dir) / "new_app.db" if _data_dir else BASE_DIR / "database.db"
```

### Step 3: docker-compose.yml にサービスを追加

```yaml
  new_app:
    <<: *app-base
    environment:
      <<: *common-env
    command:
      - /entrypoint.sh
      - new-app
      - streamlit
      - run
      - app.py
      - --server.port=8505
      - --server.headless=true
      - --server.address=0.0.0.0
      - --server.baseUrlPath=/new-app
```

### Step 4: nginx.conf にルーティングを追加

```nginx
location /new-app/ {
    proxy_pass http://new_app:8505/new-app/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade    $http_upgrade;
    proxy_set_header Connection $connection_upgrade;
    proxy_set_header Host       $host;
}
```

### Step 5: テスト

```bash
docker compose up -d --build new_app
# ブラウザで http://localhost/new-app/ を確認
```

---

## 6. コーディング規約

### 各アプリ共通

- **Python 3.11+** を対象
- DB 接続時は `PRAGMA journal_mode=WAL;` を設定（同時アクセス対策）
- DB 接続時は `PRAGMA foreign_keys = ON;` を設定
- `KEM_DATA_DIR` 環境変数に対応すること（共有DBフォルダ）
- 他のアプリのコードを import しない（データ連携は SQLite ファイル経由）
- `requirements.txt` にはバージョン上限を付ける（例: `streamlit>=1.30,<2.0`）

### Streamlit アプリ

- `--server.baseUrlPath` に対応すること（Docker のリバースプロキシで必要）
- `seed.py` でデモデータを提供すること（テスト用）

### Flask アプリ

- `ProxyFix` ミドルウェアを使用すること（リバースプロキシ対応）
- テンプレート内のリンクは `url_for()` を使うこと

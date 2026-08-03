# KEM_DDENKI — ケンモチ電機 業務管理システム

電気工事の業務フローを一気通貫でカバーする統合Webアプリケーション。  
日報・原価・材料・入札・工期・人材・営業・取引先・開発管理の **15モジュール** を1つのプラットフォームで提供します。

---

## システム構成図

```
┌─────────────────────────────────────────────────────────────┐
│                        ユーザー                              │
│    PC (Chrome/Edge)    スマホ (Safari/Chrome)    Discord     │
└───────────┬──────────────────┬─────────────────────┬────────┘
            │                  │                     │
            ▼                  ▼                     ▼
┌─────────────────────────────────────────────────────────────┐
│                    Nginx (リバースプロキシ)                    │
│                  http://192.168.0.35:8080                    │
└───────────────────────────┬─────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────┐
│                Django 5.2 LTS + Gunicorn                     │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │
│  │ 日報管理  │ │ 原価管理  │ │ 材料管理  │ │ 入札管理  │       │
│  │ reports  │ │ costs    │ │materials │ │ bids     │       │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤       │
│  │ 工期管理  │ │ 人材管理  │ │ 営業管理  │ │ 取引先   │       │
│  │schedules │ │ workers  │ │ sales    │ │ masters  │       │
│  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤       │
│  │ 開発管理  │ │ 現場管理  │ │ 通知     │ │ 権限管理  │       │
│  │ devkanri │ │ sites    │ │notific.  │ │permiss.  │       │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │
│                                                              │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │
│  │ accounts │ │ tenants  │ │  core    │  ← 基盤レイヤー      │
│  └──────────┘ └──────────┘ └──────────┘                    │
└──────┬──────────────┬──────────────┬────────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌──────────┐   ┌──────────┐   ┌──────────┐
│PostgreSQL│   │  Redis   │   │  Nginx   │
│    16    │   │    7     │   │ (静的)    │
└──────────┘   └──────────┘   └──────────┘
```

**技術スタック:** Django 5.2 LTS / PostgreSQL 16 / Redis 7 / Nginx / Docker

---

## 機能一覧

| モジュール | URL | 主な機能 |
|-----------|-----|---------|
| ダッシュボード | `/` | KPI概要・アラート・直近の日報・現場一覧 |
| 現場管理 | `/sites/` | 現場CRUD・ステータス管理・原価サマリ |
| 日報管理 | `/reports/` | 日報入力（開始終了時間・残業自動計算）・KY記入チェック・月別集計 |
| 原価管理 | `/costs/` | 予算vs実績ダッシュボード・消化率グラフ・75/80/90/100%アラート |
| 材料管理 | `/materials/` | 材料マスタ・見積比較・発注・納品検収・在庫 |
| 入札管理 | `/bids/` | 案件管理・競合情報・落札→現場自動登録・受注率ダッシュボード |
| 営業管理 | `/sales/` | 営業来訪記録・業界別ブラウズ・ステータス管理 |
| 工期管理 | `/schedules/` | ガントチャート・配置カレンダー・マイルストーン・工程テンプレート |
| 人材管理 | `/workers/` | 作業員・資格(5段階アラート)・スキルマップ・評価・健康診断・勤怠集計 |
| 開発管理 | `/dev/` | カンバンボード・Discord webhook通知・GitHub PR/Issue連携 |
| 取引先管理 | `/masters/` | 得意先・仕入先CRUD・5段階評価・名刺管理 |
| 通知 | `/notifications/` | 全モジュール共通の通知センター・アラートルール管理 |
| 権限管理 | `/settings/permissions/` | ロール×モジュール権限マトリクス・ユーザーロール付与 |

---

# ユーザー向け

## アクセス方法

### 社内ネットワーク（Wi-Fi / LAN）

| 環境 | URL |
|------|-----|
| **本番** | [http://192.168.0.35:8080/](http://192.168.0.35:8080/) |
| **開発** | [http://192.168.0.35:8081/](http://192.168.0.35:8081/) |

### 社外ネットワーク（Tailscale VPN）

| 環境 | URL |
|------|-----|
| **本番** | [http://100.120.92.15:8080/](http://100.120.92.15:8080/) |
| **開発** | [http://100.120.92.15:8081/](http://100.120.92.15:8081/) |

> Tailscale 未導入の端末からは社外アクセスできません。セットアップ手順は [docs/tailscale_setup.md](docs/tailscale_setup.md) を参照。

---

## PC（Windows / Mac）

1. ブラウザ（Chrome / Edge 推奨）で [http://192.168.0.35:8080/](http://192.168.0.35:8080/) を開く
2. ログイン画面でメールアドレスとパスワードを入力
3. ダッシュボードが表示されたら利用開始

### デスクトップアプリとして使う（任意）

1. Chrome で上記URLを開く
2. アドレスバー右の「インストール」アイコンをクリック
3. 「インストール」を選択 → デスクトップにアイコンが追加される

---

## iPhone（iOS）

1. **Safari** で [http://192.168.0.35:8080/](http://192.168.0.35:8080/) を開く
2. ログインする
3. 画面下の共有ボタン（□↑）をタップ
4. 「**ホーム画面に追加**」をタップ
5. 名前を確認して「追加」

> ホーム画面に「ケンモチ電機」アイコンが追加され、タップするだけでアプリが開きます。

---

## Android

1. **Chrome** で [http://192.168.0.35:8080/](http://192.168.0.35:8080/) を開く
2. ログインする
3. メニュー（⋮）→「**ホーム画面に追加**」または「**アプリをインストール**」
4. 「追加」をタップ

> ホーム画面にアイコンが追加され、通常のアプリと同じように起動できます。

---

# 開発者向け

## 開発用リンク

| リソース | URL |
|---------|-----|
| **GitHub リポジトリ** | [https://github.com/mstk13/KEM_DDENKI](https://github.com/mstk13/KEM_DDENKI) |
| **開発環境アプリ** | [http://192.168.0.35:8081/](http://192.168.0.35:8081/) |
| **開発環境 Django Admin** | [http://192.168.0.35:8081/admin/](http://192.168.0.35:8081/admin/) |
| **ローカル開発サーバー** | [http://localhost:8000/](http://localhost:8000/) |
| **ローカル Django Admin** | [http://localhost:8000/admin/](http://localhost:8000/admin/) |
| **設計資料** | [docs/design/](https://github.com/mstk13/KEM_DDENKI/tree/main/docs/design) |
| **設計判断の根拠書** | [docs/design/設計判断の根拠書.md](https://github.com/mstk13/KEM_DDENKI/blob/main/docs/design/設計判断の根拠書.md) |
| **DB設計書** | [docs/design/DB設計書.md](https://github.com/mstk13/KEM_DDENKI/blob/main/docs/design/DB設計書.md) |
| **CI/CD (GitHub Actions)** | [Actions](https://github.com/mstk13/KEM_DDENKI/actions) |
| **Issues** | [Issues](https://github.com/mstk13/KEM_DDENKI/issues) |
| **Pull Requests** | [Pull Requests](https://github.com/mstk13/KEM_DDENKI/pulls) |

### 開発環境の全画面URL

| アプリ | ローカル | 開発サーバー |
|--------|---------|------------|
| ダッシュボード | [localhost:8000/](http://localhost:8000/) | [192.168.0.35:8081/](http://192.168.0.35:8081/) |
| 現場管理 | [localhost:8000/sites/](http://localhost:8000/sites/) | [192.168.0.35:8081/sites/](http://192.168.0.35:8081/sites/) |
| 日報管理 | [localhost:8000/reports/](http://localhost:8000/reports/) | [192.168.0.35:8081/reports/](http://192.168.0.35:8081/reports/) |
| 原価管理 | [localhost:8000/costs/](http://localhost:8000/costs/) | [192.168.0.35:8081/costs/](http://192.168.0.35:8081/costs/) |
| 材料管理 | [localhost:8000/materials/](http://localhost:8000/materials/) | [192.168.0.35:8081/materials/](http://192.168.0.35:8081/materials/) |
| 入札管理 | [localhost:8000/bids/](http://localhost:8000/bids/) | [192.168.0.35:8081/bids/](http://192.168.0.35:8081/bids/) |
| 営業管理 | [localhost:8000/sales/](http://localhost:8000/sales/) | [192.168.0.35:8081/sales/](http://192.168.0.35:8081/sales/) |
| 工期管理 | [localhost:8000/schedules/](http://localhost:8000/schedules/) | [192.168.0.35:8081/schedules/](http://192.168.0.35:8081/schedules/) |
| 人材管理 | [localhost:8000/workers/](http://localhost:8000/workers/) | [192.168.0.35:8081/workers/](http://192.168.0.35:8081/workers/) |
| 開発管理 | [localhost:8000/dev/](http://localhost:8000/dev/) | [192.168.0.35:8081/dev/](http://192.168.0.35:8081/dev/) |
| 取引先管理 | [localhost:8000/masters/](http://localhost:8000/masters/) | [192.168.0.35:8081/masters/](http://192.168.0.35:8081/masters/) |
| 通知 | [localhost:8000/notifications/](http://localhost:8000/notifications/) | [192.168.0.35:8081/notifications/](http://192.168.0.35:8081/notifications/) |
| 権限管理 | [localhost:8000/settings/permissions/](http://localhost:8000/settings/permissions/) | [192.168.0.35:8081/settings/permissions/](http://192.168.0.35:8081/settings/permissions/) |
| Django Admin | [localhost:8000/admin/](http://localhost:8000/admin/) | [192.168.0.35:8081/admin/](http://192.168.0.35:8081/admin/) |

## クイックスタート

### 前提条件

- [Git](https://git-scm.com/)
- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows / Mac）または Docker Engine + Docker Compose（Linux）
- Python 3.12+（Docker外で開発する場合）

### 1. クローン & 起動

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI/saas

# 環境変数を設定
cp .env.example .env

# Docker で起動（PostgreSQL + Redis + Django）
docker compose up -d

# マイグレーション実行
docker compose exec web python manage.py migrate

# 管理者アカウント作成
docker compose exec web python manage.py createsuperuser

# ブラウザで開く → http://localhost:8000
```

### 2. Docker外で開発する場合

```bash
cd KEM_DDENKI/saas

# PostgreSQL + Redis だけ Docker で起動
docker compose up -d db redis

# Python 仮想環境
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# マイグレーション
python manage.py migrate

# 開発サーバー起動
python manage.py runserver
# → http://localhost:8000
```

### 3. 本番デプロイ

```bash
cd KEM_DDENKI/saas

# .env の DJANGO_DEBUG=False, DJANGO_SECRET_KEY を設定

# 本番起動（Gunicorn + Nginx）
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# ポート: NGINX_PORT=8081（並行稼働時）→ 8080（切替後）
```

---

## 開発コマンド一覧

```bash
cd KEM_DDENKI/saas

# テスト実行（SQLiteモード、高速）
USE_SQLITE=true DJANGO_SETTINGS_MODULE=config.settings python -m pytest tests/ -v

# マイグレーション作成
python manage.py makemigrations

# Django Admin（ブラウザ）
# http://localhost:8000/admin/

# データ移行（旧Streamlit版 → Django版）
LEGACY_DB_URL="postgresql://kem:kem@localhost:5433/kem_main" \
  python scripts/migrate_legacy_data.py --dry-run  # 確認
  python scripts/migrate_legacy_data.py             # 実行
```

---

## プロジェクト構成

```
KEM_DDENKI/
├── README.md
├── .github/workflows/          CI/CD（テスト自動実行・リリース）
├── docs/
│   ├── design/                 設計資料（7点）
│   │   ├── 要件定義書.md         全モジュールの機能仕様
│   │   ├── DB設計書.md           テーブル定義・ER図
│   │   ├── 技術選定書.md         Django / Next.js段階移行方針
│   │   ├── 画面設計書.md         ワイヤーフレーム・画面遷移
│   │   ├── 設計判断の根拠書.md   全ての「なぜ」を解説
│   │   ├── TM向けQ&A集.md       想定質問20問と回答
│   │   └── 技術用語集.md         50以上の用語解説
│   ├── git_workflow.md         Git運用ルール
│   ├── geps_setup.md           GEPSメール連携
│   └── tailscale_setup.md      外部アクセス（VPN）
│
└── saas/                       Django SaaS版（本体）
    ├── config/                 Django設定（settings / urls / wsgi）
    ├── apps/                   15アプリ
    │   │
    │   │── 基盤レイヤー
    │   ├── core/               テナント基盤（TenantModel, ミドルウェア）
    │   ├── tenants/            マルチテナント（Company, CompanyApp）
    │   ├── accounts/           ユーザー・部署・認証
    │   ├── permissions/        ロール権限（Role × Module の R/W/A マトリクス）
    │   ├── notifications/      通知基盤（5種アラート: 原価/資格/工期/入札/KY）
    │   │
    │   │── 業務アプリ
    │   ├── sites/              現場管理
    │   ├── reports/            日報（開始終了時間・残業自動計算・KY管理）
    │   ├── costs/              原価（予算vs実績・Chart.jsグラフ・閾値アラート）
    │   ├── materials/          材料（見積比較・発注・納品検収・在庫）
    │   ├── bids/               入札（案件・競合・書類・落札→現場自動登録）
    │   ├── sales/              営業（来訪記録・業界別ブラウズ）
    │   ├── schedules/          工期（ガントチャート・配置カレンダー・テンプレート）
    │   ├── workers/            人材（資格・スキル・評価・健診・勤怠）
    │   ├── masters/            取引先（得意先/仕入先CRUD・評価・名刺）
    │   └── devkanri/           開発（カンバン・Discord webhook・GitHub連携）
    │
    ├── templates/              HTMLテンプレート（79ファイル）
    │   ├── base.html           共通レイアウト（サイドバー + 通知バッジ）
    │   └── [各アプリ]/
    │
    ├── static/                 CSS / JavaScript
    ├── scripts/                データ移行スクリプト
    ├── tests/                  テスト（72件）
    │
    ├── docker-compose.yml      開発用（db + redis + web）
    ├── docker-compose.prod.yml 本番用（+ nginx）
    ├── docker/nginx.conf       Nginx設定
    ├── Dockerfile
    ├── pyproject.toml          Python依存関係
    └── .env.example            環境変数サンプル
```

---

## 設計資料

> **初めて参加する開発者へ**: まず [設計判断の根拠書](docs/design/設計判断の根拠書.md) を読んでください。「何を作るか」だけでなく「なぜそう作るか」がわかります。

| 資料 | 内容 |
|------|------|
| [要件定義書](docs/design/要件定義書.md) | 全モジュールの機能仕様（ヒアリングベース） |
| [DB設計書](docs/design/DB設計書.md) | テーブル定義・ER図・インデックス設計 |
| [技術選定書](docs/design/技術選定書.md) | Django → Next.js 段階移行方針 |
| [画面設計書](docs/design/画面設計書.md) | 全31画面のワイヤーフレーム・画面遷移 |
| **[設計判断の根拠書](docs/design/設計判断の根拠書.md)** | **全ての設計で「なぜそうしたのか」を解説** |
| [TM向けQ&A集](docs/design/TM向けQ&A集.md) | 想定質問20問と回答 |
| [技術用語集](docs/design/技術用語集.md) | 50以上の技術用語を業務用語に対応づけて解説 |

---

## 設計原則

| 原則 | 説明 |
|------|------|
| **services.py にロジック集約** | ビューは薄く保ち、将来の Django REST Framework → Next.js 移行に備える |
| **マルチテナント** | TenantModel ベースで会社単位のデータ分離。全テーブルに `company_id` |
| **監査証跡** | django-simple-history で全モデルの変更履歴を自動記録 |
| **ロールベース権限** | 社長/役員/現場担当/事務/協力会社/開発者の6ロール × モジュール別 R/W/A |
| **テスト駆動** | 72件のテストでテナント分離・自動仕訳・権限を検証 |

---

## 数値サマリ

| 項目 | 数 |
|------|-----|
| Django アプリ | 15 |
| ビュー関数 | 約120 |
| URL パターン | 約100 |
| HTML テンプレート | 79 |
| テスト | 72 |
| services.py（ロジック層） | 12 |
| マイグレーション | 25 |
| 設計資料 | 7 |

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/design/](docs/design/) | 設計資料一式（7点） |
| [docs/git_workflow.md](docs/git_workflow.md) | Git運用ルール・ブランチ戦略 |
| [docs/tailscale_setup.md](docs/tailscale_setup.md) | 社外アクセス（Tailscale VPN）セットアップ |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPSメール連携セットアップ |

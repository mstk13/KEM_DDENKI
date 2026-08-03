# KEM_DDENKI — ケンモチ電機 業務管理システム

電気工事の業務フローを一気通貫でカバーする統合Webアプリケーション。

**技術スタック:** Django 5.2 LTS / PostgreSQL 16 / Redis / Nginx

---

## クイックスタート

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI/saas

# 環境変数を設定
cp .env.example .env

# Docker で起動
docker compose up -d

# ブラウザで開く
open http://localhost:8000
```

---

## アプリ一覧

| アプリ | URL | 概要 |
|--------|-----|------|
| ダッシュボード | `/` | KPI・アラート一覧 |
| 現場管理 | `/sites/` | 現場のCRUD・ステータス管理 |
| 日報管理 | `/reports/` | 日報入力・KY記入チェック・月別集計 |
| 原価管理 | `/costs/` | 予算vs実績・消化率グラフ・アラート |
| 材料管理 | `/materials/` | 見積比較・発注・納品検収・在庫 |
| 入札管理 | `/bids/` | 案件管理・ダッシュボード・落札→現場自動登録 |
| 営業管理 | `/sales/` | 営業来訪記録・業界別ブラウズ |
| 工期管理 | `/schedules/` | ガントチャート・配置カレンダー・テンプレート |
| 人材管理 | `/workers/` | 作業員・資格・スキルマップ・評価・健康診断 |
| 開発管理 | `/dev/` | カンバン・Discord/GitHub連携 |
| 取引先管理 | `/masters/` | 工種・得意先・仕入先・評価・名刺 |
| 通知 | `/notifications/` | 全モジュール共通の通知センター |
| 権限管理 | `/settings/permissions/` | ロール×モジュール権限マトリクス |

---

## 開発者向け

### 設計資料

| 資料 | 内容 |
|------|------|
| [要件定義書](docs/design/要件定義書.md) | 全モジュールの機能仕様 |
| [DB設計書](docs/design/DB設計書.md) | テーブル定義・ER図 |
| [技術選定書](docs/design/技術選定書.md) | Django / Next.js段階移行方針 |
| [画面設計書](docs/design/画面設計書.md) | ワイヤーフレーム・画面遷移 |
| **[設計判断の根拠書](docs/design/設計判断の根拠書.md)** | **全ての「なぜ」を解説** |
| [TM向けQ&A集](docs/design/TM向けQ&A集.md) | 想定質問20問と回答 |
| [技術用語集](docs/design/技術用語集.md) | 技術用語の解説 |

### プロジェクト構成

```
saas/
├── config/             # Django設定
├── apps/
│   ├── core/           # テナント基盤
│   ├── tenants/        # マルチテナント
│   ├── accounts/       # ユーザー・認証
│   ├── permissions/    # ロールベース権限
│   ├── notifications/  # 通知基盤
│   ├── reports/        # 日報管理
│   ├── costs/          # 原価管理
│   ├── materials/      # 材料管理
│   ├── bids/           # 入札管理
│   ├── sales/          # 営業管理
│   ├── schedules/      # 工期管理
│   ├── workers/        # 人材管理
│   ├── masters/        # 取引先管理
│   ├── devkanri/       # 開発管理
│   └── sites/          # 現場管理
├── templates/          # Django テンプレート
├── static/             # CSS/JS
├── tests/              # テスト（72件）
├── scripts/            # データ移行等
├── docker-compose.yml
└── Dockerfile
```

### 開発コマンド

```bash
cd saas/

# 開発サーバー
docker compose up

# テスト実行
USE_SQLITE=true DJANGO_SETTINGS_MODULE=config.settings python -m pytest tests/ -v

# マイグレーション作成
python manage.py makemigrations
python manage.py migrate

# 管理者アカウント作成
python manage.py createsuperuser
```

### 本番デプロイ

```bash
cd saas/

# 本番起動（gunicorn + nginx）
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

### 設計原則

- **services.py にロジック集約** — ビューは薄く、将来の DRF API 移行に備える
- **マルチテナント** — TenantModel ベースで会社単位のデータ分離
- **監査証跡** — django-simple-history で全モデルの変更履歴を自動記録
- **テスト駆動** — 72件のテストで品質を維持

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/design/](docs/design/) | 設計資料一式 |

---

GitHub: [mstk13/KEM_DDENKI](https://github.com/mstk13/KEM_DDENKI)

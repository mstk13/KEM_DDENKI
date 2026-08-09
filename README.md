<p align="center">
  <img src="saas/static/img/icon-192.png" width="104" alt="ケンモチ電機 業務管理システム">
</p>

<h1 align="center">KEM_DDENKI — ケンモチ電機 業務管理システム</h1>

電気工事の業務フローを一気通貫でカバーする統合Webアプリケーション。  
日報・原価・材料・入札・工期・人材・営業・取引先・開発管理の **15モジュール** を1つのプラットフォームで提供します。

**まず読むページ**

| 立場 | ページ |
|------|--------|
| 現場・事務で**使う**人 | この下の [アクセス方法](#アクセス方法) |
| **開発する**人 | [開発者ガイド](docs/developer_guide.md) |
| サーバーを**管理する**人 | [サーバー運用ガイド](docs/server_operations.md) |

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
│              Tailscale serve (HTTPS終端・VPN内限定)            │
│      本番 …:8000  https://desktop-rmsk0vg.tail8efe0d.ts.net  │
│      開発 …:8001  https://desktop-rmsk0vg…ts.net:8443        │
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

### 開くURL

**PC でもスマホでも、開くURLは同じ1つです。**

| | URL |
|---|-----|
| 🖥️ **PC**（Windows / Mac）<br>📱 **スマホ**（iPhone / Android） | **https://desktop-rmsk0vg.tail8efe0d.ts.net/** |

端末によって違うのは URL ではなく、**最初の準備**と**アイコンの置き方**だけです。下の自分の端末の手順に進んでください。

> [!TIP]
> **上のURLが「アクセスできません」になる場合は、こちらを試してください。**
>
> ```
> http://100.76.219.49:8000/
> ```
>
> 同じアプリに、名前ではなくIPアドレスで直接つなぎます。
> ブラウザの「セキュア DNS」が有効だと名前だけ引けないことがあるためです
> （原因と恒久的な直し方は [つながらないとき](#つながらないとき) を参照）。

> [!IMPORTANT]
> このURLは社内ネットワーク（Tailscale VPN）の中からしか開けません。
> 会社のWi-Fiにつないでいても、**その端末に Tailscale が入っていないと開けません**。
> 逆に Tailscale さえ入っていれば、自宅でも現場でも同じURLで使えます。
> 端末の追加は管理者に依頼してください（手順: [docs/tailscale_setup.md](docs/tailscale_setup.md)）。

### ログイン

| 入力欄 | 入れるもの |
|--------|-----------|
| 社員番号 | 自分の社員番号（例: `E001`） |
| 管理者パスワード | **社長のみ** 表示される。一般社員は表示されません |

社員番号を入れると氏名が表示されます。表示されない場合は、その社員番号がまだ登録されていません。

---

## 🖥️ PC（Windows / Mac）の場合

1. **Chrome** または **Edge** で https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開く
2. 社員番号を入れてログイン
3. ダッシュボードが出れば利用開始

### デスクトップにアイコンを置く（任意・おすすめ）

1. Chrome / Edge で上記URLを開く
2. アドレスバー右端の **インストール**（⊕ または 🖥️ のアイコン）をクリック
3. 「インストール」を選ぶ

デスクトップとスタートメニューに **ヘルメットのアイコン** が追加され、ブラウザのタブではなく独立したウィンドウで開くようになります。

---

## 📱 iPhone（iOS）の場合

**事前準備**: App Store から **Tailscale** を入れ、管理者に招待してもらってサインインしておく。

1. **Safari** で https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開く
   （Safari 以外だとホーム画面に追加できません）
2. 社員番号を入れてログイン
3. 画面下の共有ボタン **□↑** をタップ
4. 「**ホーム画面に追加**」をタップ
5. 名前が「ケンモチ電機」になっているのを確認して「追加」

ホーム画面に**ヘルメットのアイコン**が追加され、タップすると普通のアプリと同じ全画面で開きます。

---

## 📱 Android の場合

**事前準備**: Google Play から **Tailscale** を入れ、管理者に招待してもらってサインインしておく。

1. **Chrome** で https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開く
2. 社員番号を入れてログイン
3. 右上のメニュー **⋮** →「**アプリをインストール**」または「**ホーム画面に追加**」
4. 「インストール」をタップ

ホーム画面に**ヘルメットのアイコン**が追加されます。

---

## つながらないとき

| 症状 | 原因と対処 |
|------|-----------|
| **`http://100.76.219.49:8000/` なら開けるのに、名前のURLだと開けない** | ブラウザの**セキュア DNS** が原因です。下の「セキュア DNS を切る」を実行してください |
| 「このサイトにアクセスできません」<br>`DNS_PROBE_FINISHED_NXDOMAIN` | 名前を解決できていません。同上 |
| ページが開かない・タイムアウトする | Tailscale がオフになっています。Tailscale アプリを開いて接続状態にしてください |
| 「この接続ではプライバシーが保護されません」 | URL を打ち間違えています。`https://` から始まっているか確認してください |
| URLの末尾に `）` などが混ざっている | 貼り付け時に余計な文字が入っています。アドレスバーを見直してください |
| 「この社員番号は登録されていません」 | まだ作業員として登録されていません。管理者に依頼してください |
| ログイン後に真っ白 / 画面が崩れる | ブラウザの再読み込み（PC は Ctrl+F5）を試してください |
| 夜間や休日につながらない | サーバーPCの電源が落ちている可能性があります。管理者に連絡してください |

### セキュア DNS を切る

アプリのURL（`…ts.net`）は Tailscale の中にしか存在しない名前で、**外部のDNSサーバーには登録されていません**。
ブラウザの「セキュア DNS」が有効だと、ブラウザはパソコンの名前解決を飛び越えて外部のDNSに直接
問い合わせに行くため、この名前が見つからずアクセスに失敗します。

一度切れば、その端末では以後ずっと名前でアクセスできます。

| ブラウザ | 手順 |
|---------|------|
| Chrome | アドレスバーに `chrome://settings/security` → 「**セキュア DNS を使用する**」を**オフ** |
| Edge | アドレスバーに `edge://settings/privacy` → 「**セキュア DNS を使用して…**」を**オフ** |
| Safari (iPhone/Mac) | 既定では影響しません。設定変更は不要です |

切りたくない場合は、IP指定のURL `http://100.76.219.49:8000/` を使ってください。
どちらも同じアプリで、通信は Tailscale により暗号化されています。

---

# 開発者向け

> 編集からリリースまでの流れ（どこを編集し、どう確認し、どう本番に出すか）は
> **[開発者ガイド](docs/developer_guide.md)** に1枚でまとめてあります。まずそちらを読んでください。

## 開発用リンク

| リソース | URL |
|---------|-----|
| **GitHub リポジトリ** | https://github.com/mstk13/KEM_DDENKI |
| **開発環境アプリ**（`developer` ブランチが自動反映） | https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/ |
| **開発環境 Django Admin** | https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/admin/ |
| **本番アプリ**（`main` ブランチが自動反映） | https://desktop-rmsk0vg.tail8efe0d.ts.net/ |
| **手元の開発サーバー** | http://localhost:8000/ |
| **開発者ガイド** | [docs/developer_guide.md](docs/developer_guide.md) |
| **サーバー運用ガイド** | [docs/server_operations.md](docs/server_operations.md) |
| **設計資料** | [docs/design/](docs/design/) |
| **CI (GitHub Actions)** | [Actions](https://github.com/mstk13/KEM_DDENKI/actions) |
| **Issues** | [Issues](https://github.com/mstk13/KEM_DDENKI/issues) |
| **Pull Requests** | [Pull Requests](https://github.com/mstk13/KEM_DDENKI/pulls) |

どちらの環境も Tailscale VPN の中からのみ到達できます。

### 各モジュールのURL

下の [機能一覧](#機能一覧) のパスを、環境のURLの後ろに付けてください。

```
開発環境の日報:   https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/reports/
本番の日報:       https://desktop-rmsk0vg.tail8efe0d.ts.net/reports/
手元の日報:       http://localhost:8000/reports/
```

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

**通常は手作業不要です。** `main` にマージすれば、サーバーPCが自動で取り込みます（次項）。

サーバーを新しく立てる場合の手順は [docs/server_operations.md](docs/server_operations.md) を参照してください。

### 4. push したら自動でサーバーに反映される仕組み

サーバーPCが2分おきに GitHub を確認し、更新があれば自分で取り込んで再起動します。
開発者側の操作は **push するだけ** です。

```
developer に push  →  （最大2分）→  開発環境 https://…ts.net:8443/ に反映
main   にマージ    →  （最大2分）→  本番     https://…ts.net/       に反映
```

GitHub からサーバーへ届く必要がないため（サーバー→GitHub の一方向のみ）、
社内PCが NAT の内側にあってもそのまま動きます。Webhook の設定も外部公開も不要です。

- 仕組みと運用: [docs/server_operations.md](docs/server_operations.md)
- スクリプト: [tools/autodeploy/autodeploy.sh](tools/autodeploy/autodeploy.sh)

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
| **[docs/developer_guide.md](docs/developer_guide.md)** | **開発者向け1枚まとめ（編集→確認→承認→本番反映）** |
| **[docs/server_operations.md](docs/server_operations.md)** | **サーバーPCの運用（自動起動・自動デプロイ・バックアップ）** |
| [docs/design/](docs/design/) | 設計資料一式（7点） |
| [docs/git_workflow.md](docs/git_workflow.md) | Git運用ルール・ブランチ戦略 |
| [docs/branch_protection_setup.md](docs/branch_protection_setup.md) | main ブランチ保護（PM承認の強制）— リポジトリ管理者向け |
| [docs/tailscale_setup.md](docs/tailscale_setup.md) | 社外アクセス（Tailscale VPN）セットアップ |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPSメール連携セットアップ |

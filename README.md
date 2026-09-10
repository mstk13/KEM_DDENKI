<p align="center">
  <img src="saas/static/img/icon-192.png" width="104" alt="ケンモチ電機 業務管理システム">
</p>

<h1 align="center">KEM_DDENKI — ケンモチ電機 業務管理システム</h1>

電気工事の業務フローを一気通貫でカバーする統合Webアプリケーション。  
日報・原価・材料・入札・積算・工期・人材・営業・取引先・開発管理の **17モジュール** を1つのプラットフォームで提供します。

**まず読むページ**

| 立場 | ページ |
|------|--------|
| 現場・事務で**使う**人 | この下の [アクセス方法](#アクセス方法) |
| **開発する**人 | [開発者マップ](index.html)（全体像を図で1枚） → [開発者ガイド](docs/developer_guide.md)（手順） |
| サーバーを**管理する**人 | [サーバー運用ガイド](docs/server_operations.md) |

> **開発者マップ** は `index.html` をブラウザで開いてください。GitHub 上ではHTMLのソースが表示されるだけなので、
> `python -m http.server` でリポジトリ直下を配信して `http://localhost:8000/index.html` を開くのが確実です。

---

## システム構成図

```
┌──────────────────────────────────────────────────────────────────┐
│                          ユーザー                                 │
│    PC (Chrome/Edge)    スマホ (Safari/Chrome)    Discord          │
└──────────┬──────────────────┬─────────────────────┬──────────────┘
           │                  │                     │
           ▼                  ▼                     ▼
┌──────────────────────────────────────────────────────────────────┐
│               Tailscale serve (HTTPS終端・VPN内限定)               │
│      本番 …:8000  https://desktop-rmsk0vg.tail8efe0d.ts.net      │
│      開発 …:8001  https://desktop-rmsk0vg…ts.net:8443            │
└──────────────────────────┬───────────────────────────────────────┘
                           │
┌──────────────────────────▼───────────────────────────────────────┐
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  web コンテナ (Django 5.2 LTS + Gunicorn)                    │ │
│  │                                                              │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐       │ │
│  │  │ 日報管理  │ │ 原価管理  │ │ 材料管理  │ │ 入札管理  │       │ │
│  │  │ reports  │ │ costs    │ │materials │ │ bids     │       │ │
│  │  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤       │ │
│  │  │ 積算     │ │ 現場管理  │ │ 営業管理  │ │ 取引先   │       │ │
│  │  │estimat.  │ │ sites    │ │ sales    │ │ masters  │       │ │
│  │  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤       │ │
│  │  │ 工期管理  │ │ 人材管理  │ │ 通知     │ │ 権限管理  │       │ │
│  │  │schedules │ │ workers  │ │notific.  │ │permiss.  │       │ │
│  │  ├──────────┤ ├──────────┤ ├──────────┤ ├──────────┤       │ │
│  │  │ 勤怠管理  │ │ 人材評価  │ │ 開発管理  │ │ AI支援   │       │ │
│  │  │attendance│ │evaluation│ │ devkanri │ │ ai       │       │ │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘       │ │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐                    │ │
│  │  │ accounts │ │ tenants  │ │  core    │  ← 基盤レイヤー      │ │
│  │  └──────────┘ └──────────┘ └──────────┘                    │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─────────────────────────────────────────────────────────────┐ │
│  │  cron コンテナ (定期タスク)                                    │ │
│  │  毎朝7時: i-ppi自動スクレイピング (2日に1回)                     │ │
│  │  毎朝8時: 書類・資格・健診アラート送信                            │ │
│  └─────────────────────────────────────────────────────────────┘ │
│                           Docker Compose                          │
└──────┬──────────────┬──────────────┬─────────────────────────────┘
       │              │              │
       ▼              ▼              ▼
┌──────────┐   ┌──────────┐   ┌──────────────────────────────┐
│PostgreSQL│   │  Redis   │   │ 外部サービス                   │
│    16    │   │    7     │   │  Claude API (PDF解析・分析)    │
└──────────┘   └──────────┘   │  i-ppi.jp (入札情報取得)      │
                              └──────────────────────────────┘
```

## 技術スタック

| レイヤー | 技術 | 用途 |
|---------|------|------|
| **Web フレームワーク** | Django 5.2 LTS / Python 3.12 | テンプレートベースのフルスタック |
| **データベース** | PostgreSQL 16 | メインDB（全モデル simple-history 付き） |
| **キャッシュ** | Redis 7 | セッション・キャッシュ |
| **AP サーバー** | Gunicorn (4 workers, 2 threads) | 本番用 WSGI |
| **ブラウザ自動操作** | Playwright + Chromium | i-ppi.jp 入札情報スクレイピング |
| **AI — LLM** | Claude API (Haiku / Sonnet) | PDF解析・コスト分析・工程提案 |
| **AI — ML** | LightGBM / scikit-learn | コスト予測モデル |
| **AI — Embedding** | bge-m3 (1,024次元) | 積算品目の名寄せ（類似度マッチング） |
| **ネットワーク** | Tailscale Serve | HTTPS終端・VPN内限定アクセス |
| **コンテナ** | Docker Compose | db / redis / web / cron の4サービス |
| **CI/CD** | GitHub Actions + 自動デプロイ | テスト・リント・2分おき自動反映 |
| **PWA** | manifest.json + Service Worker | スマホ・PCのホーム画面から起動 |

---

## 機能一覧

| モジュール | URL | 主な機能 |
|-----------|-----|---------|
| ダッシュボード | `/` | KPI概要・アラート・直近の日報・現場一覧 |
| 現場管理 | `/sites/` | 現場CRUD・ステータス管理・原価サマリ |
| 日報管理 | `/reports/` | 日報入力（開始終了時間・残業自動計算）・KY記入チェック・月別集計 |
| 原価管理 | `/costs/` | 予算vs実績ダッシュボード・消化率グラフ・75/80/90/100%アラート |
| 材料管理 | `/materials/` | 材料マスタ・見積比較・発注・納品検収・在庫 |
| 入札管理 | `/bids/` | i-ppi自動スクレイピング・公告PDF解析・資格適格判定・競合情報・落札→現場自動登録 |
| 積算 | `/estimation/` | 品目マスタ・Embedding名寄せ・労務単価取込・歩掛/積算基準・内訳書Excel出力・差分分析 |
| 営業管理 | `/sales/` | 営業来訪記録・業界別ブラウズ・ステータス管理 |
| 工期管理 | `/schedules/` | ガントチャート・配置カレンダー・マイルストーン・工程テンプレート |
| 人材管理 | `/workers/` | 作業員・資格(5段階アラート)・スキルマップ・健康診断 |
| 勤怠管理 | `/attendance/` | 出社予定（月グリッド・日別シート・まとめて記入）・勤怠設定 |
| 人材評価 | `/evaluation/` | 評価基準・評価入力・評価者割当・従業員別サマリ |
| AI支援 | `/ai/` | コスト予測(LightGBM)・最適化(Claude)・工程提案・呼び出しログ・コスト管理・フィードバック |
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
# .env を編集: DJANGO_SECRET_KEY, DB_PASSWORD, ANTHROPIC_API_KEY 等を設定

# Docker で起動（PostgreSQL + Redis + Django + cron）
docker compose up -d

# マイグレーション実行
docker compose exec web python manage.py migrate

# 管理者アカウント作成
docker compose exec web python manage.py createsuperuser

# Playwright（入札スクレイパー用）のブラウザインストール
docker compose exec web python -m playwright install --with-deps chromium

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

# テスト実行（SQLiteモード、高速）※ dev依存を入れた仮想環境が前提
# 事前に collectstatic を流さないと「Missing staticfiles manifest entry」で落ちます
python manage.py collectstatic --noinput
USE_SQLITE=true DJANGO_SETTINGS_MODULE=config.settings python -m pytest tests/ -v

# Docker で回す場合（web コンテナに pytest は入っていません）
# → docs/developer_guide.md の「テスト」を参照

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
├── index.html                  開発者マップ（全体像を図10枚で / ブラウザで開く）
├── .github/workflows/          CI/CD（テスト自動実行・リリース）
├── tools/autodeploy/           自動デプロイスクリプトの正本
├── docs/
│   ├── design/                 設計資料（8点）
│   │   ├── 要件定義書.md         全モジュールの機能仕様
│   │   ├── DB設計書.md           テーブル定義・ER図
│   │   ├── 技術選定書.md         Django / Next.js段階移行方針
│   │   ├── 画面設計書.md         ワイヤーフレーム・画面遷移
│   │   ├── 設計判断の根拠書.md   全ての「なぜ」を解説
│   │   ├── TM向けQ&A集.md       想定質問20問と回答
│   │   └── 技術用語集.md         50以上の用語解説
│   ├── saas/adr/               ADR（設計判断記録）8件
│   │   ├── ADR-0005 … 0012     ML予測・Claude統合・積算・入札詳細・AI3層分離 等
│   ├── developer_guide.md      編集→確認→承認→本番反映の1枚まとめ
│   ├── server_operations.md    サーバーPCの運用（自動起動・デプロイ・バックアップ）
│   ├── git_workflow.md         Git運用ルール
│   ├── branch_protection_setup.md  main保護（PM承認の強制）
│   ├── geps_setup.md           GEPSメール連携
│   └── tailscale_setup.md      外部アクセス（VPN）
│
└── saas/                       Django SaaS版（本体）
    ├── config/                 Django設定（settings / urls / wsgi）
    ├── apps/                   19アプリ
    │   │
    │   │── 基盤レイヤー
    │   ├── core/               テナント基盤（TenantModel, ミドルウェア）
    │   ├── tenants/            マルチテナント（Company, CompanyApp）
    │   ├── accounts/           ユーザー・部署・社員番号ログイン
    │   ├── permissions/        ロール権限（Role × Module の R/W/A マトリクス）
    │   ├── masters/            全社マスタ（工種/原価区分/得意先/仕入先/名刺）
    │   │
    │   │── 業務の背骨
    │   ├── bids/               入札（i-ppiスクレイピング・公告PDF解析・資格適格判定・落札→現場自動登録）
    │   ├── estimation/         積算（品目・Embedding名寄せ・労務単価・歩掛・内訳書・差分分析）
    │   ├── sites/              現場管理（現場・工程・見積ファイル取込）
    │   ├── reports/            日報（開始終了時間・残業自動計算・KY管理）
    │   ├── costs/              原価（予算vs実績・Chart.jsグラフ・閾値アラート）
    │   │
    │   │── 現場にぶら下がるもの
    │   ├── materials/          材料（見積比較・発注・納品検収・在庫・調達実績）
    │   ├── schedules/          工期（ガントチャート・配置カレンダー・テンプレート）
    │   ├── workers/            人材（作業員・資格・スキル・健診）
    │   ├── attendance/         勤怠（出社予定・勤怠設定。実績は reports 側）
    │   ├── evaluation/         人材評価（評価基準・評価入力・評価者割当）
    │   │
    │   │── 横断・支援
    │   ├── notifications/      通知基盤（原価/資格/工期/入札/証明書/健診アラート）
    │   ├── ai/                 AI（Claude によるコスト分析・工程提案 / LightGBM 予測）
    │   ├── sales/              営業（来訪記録・業界別ブラウズ）
    │   └── devkanri/           開発（カンバン・Discord webhook・GitHub連携）
    │
    ├── templates/              HTMLテンプレート（158ファイル）
    │   ├── base.html           共通レイアウト（サイドバー + 通知バッジ）
    │   └── [各アプリ]/
    │
    ├── static/                 CSS / JavaScript
    ├── scripts/                データ移行スクリプト
    ├── tests/                  テスト（441件）
    ├── CLAUDE.md               実装時の開発規律（絶対ルール9項目）
    │
    ├── docker-compose.yml      db + redis + web + cron（+ Cloudflare Tunnel オプション）
    ├── Dockerfile              Python 3.12 + Playwright Chromium
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
| **[AI設計](docs/design/AI設計.md)** | **AI/MLの全体像 — 3層アーキテクチャ・利用箇所マップ・コスト管理（ADR横断の要約）** |

---

## 設計原則

| 原則 | 説明 |
|------|------|
| **services.py にロジック集約** | ビューは薄く保ち、将来の Django REST Framework → Next.js 移行に備える |
| **マルチテナント** | TenantModel ベースで会社単位のデータ分離。全テーブルに `company_id` |
| **監査証跡** | django-simple-history で全モデルの変更履歴を自動記録 |
| **ロールベース権限** | 社長/役員/現場担当/事務/協力会社/開発者の6ロール × モジュール別 R/W/A |
| **テスト駆動** | 441件のテストでテナント分離・自動仕訳・権限・パーサーを検証 |
| **金額は Decimal のみ** | float 禁止。丸め誤差で原価計算が狂うことを構造的に防ぐ |
| **expand/contract マイグレーション** | 破壊的変更を単一リリースで行わない |
| **AI 3層分離** | Embedding(高速) → ローカルLLM(中速) → Claude API(高精度) でコストと速度を最適化 |

---

## 業務フロー概要

```
入札案件の発見 → 見積・積算 → 入札 → 落札 → 現場管理 → 原価管理 → 完了
      │              │          │        │         │          │
      ▼              ▼          ▼        ▼         ▼          ▼
 ┌─────────┐  ┌─────────┐  ┌──────┐ ┌──────┐ ┌────────┐ ┌──────┐
 │i-ppi    │  │積算     │  │入札  │ │現場  │ │日報    │ │原価  │
 │自動取得  │→│品目名寄せ│→│案件  │→│自動  │→│残業    │→│予実  │
 │公告PDF  │  │歩掛計算  │  │管理  │ │登録  │ │自動計算│ │管理  │
 │資格照合  │  │内訳書   │  │      │ │      │ │KY管理  │ │アラート│
 └─────────┘  └─────────┘  └──────┘ └──────┘ └────────┘ └──────┘
       ↑                                          │
  cron が2日に1回                        承認→原価自動仕訳
  自動実行
```

各モジュールは独立して使えますが、上の流れで連携すると手作業が大幅に減ります。
落札した案件は自動で現場として登録され、日報の承認は原価トランザクションを自動生成します。

---

## 自動化・定期タスク

| タスク | スケジュール | 内容 |
|--------|------------|------|
| 入札案件スクレイピング | 2日に1回 朝7時 | i-ppi.jp + 個別サイトから新着案件を取得 |
| 書類アラート送信 | 毎日 朝8時 | 資格期限・健診期限・証明書未提出を通知 |
| 自動デプロイ | 2分おき | GitHub の変更を検知して本番/開発に反映 |
| 日次バックアップ | 毎日 12:30 | PostgreSQL のフルバックアップ |

定期タスクは Docker の `cron` コンテナで実行されます（`docker compose logs cron` で確認可能）。

---

## 数値サマリ

| 項目 | 数 |
|------|-----|
| Django アプリ | 19 |
| モデル | 83 |
| ビュー関数 | 244 |
| URL パターン | 243 |
| HTML テンプレート | 158 |
| テスト | 441 |
| services.py（ロジック層） | 12 + パッケージ2 |
| マイグレーション | 74 |
| ADR（設計判断記録） | 8 |
| Python 行数（migrations 除く） | 36,440 |
| 設計資料 | 8 |

> 上の数値は `0d4bd1d`（`developer`、2026-08-14）時点の実測値です。アプリやモデルを足したら
> [開発者マップ](index.html) の「30秒で掴む」と合わせて更新してください。

---

## ADR（Architecture Decision Records）

設計上の判断とその根拠を記録したドキュメント。新機能の追加やアーキテクチャ変更時に参照してください。

| ADR | タイトル | 概要 |
|-----|---------|------|
| [ADR-0005](docs/saas/adr/ADR-0005-ml-cost-prediction.md) | LightGBM コスト予測 | 軽量・説明可能な ML モデルで原価予測 |
| [ADR-0006](docs/saas/adr/ADR-0006-claude-api-integration.md) | Claude API 統合 | Haiku(抽出) / Sonnet(分析) の使い分け・コスト追跡 |
| [ADR-0007](docs/saas/adr/ADR-0007-genba-memo-2026-08.md) | 現場ヒアリング統合 | 現場作業の手入力を Process モデルに反映 |
| [ADR-0008](docs/saas/adr/ADR-0008-estimation-app.md) | 積算アプリ設計 | 品目名寄せ・労務単価・歩掛の段階的構築 |
| [ADR-0009](docs/saas/adr/ADR-0009-bid-detail-and-category-filter.md) | 入札詳細・カテゴリフィルタ | 詳細ページ巡回と土木/舗装の除外ロジック |
| [ADR-0010](docs/saas/adr/ADR-0010-ai-inference-tiering.md) | AI 推論3層分離 | Embedding → ローカルLLM → Claude API のコスト最適化 |
| [ADR-0011](docs/saas/adr/ADR-0011-bid-qualification-and-announcement.md) | 入札資格・公告解析 | PDF から参加資格を抽出し、自社資格と自動照合 |
| [ADR-0012](docs/saas/adr/ADR-0012-garbled-announcement-llm-fallback.md) | 文字化けPDF → LLM | ToUnicode 欠損PDFを Claude Sonnet で解読 |

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| **[index.html](index.html)** | **開発者マップ — 全体像・モジュール地図・業務フロー・落とし穴を図10枚で** |
| **[docs/developer_guide.md](docs/developer_guide.md)** | **開発者向け1枚まとめ（編集→確認→承認→本番反映）** |
| **[docs/server_operations.md](docs/server_operations.md)** | **サーバーPCの運用（自動起動・自動デプロイ・バックアップ）** |
| [docs/design/](docs/design/) | 設計資料一式（7点） |
| **[docs/design/AI設計.md](docs/design/AI設計.md)** | **AI/ML全体像（3層アーキテクチャ・利用箇所・コスト管理）** |
| [docs/saas/adr/](docs/saas/adr/) | ADR（設計判断記録）8件 |
| [docs/git_workflow.md](docs/git_workflow.md) | Git運用ルール・ブランチ戦略 |
| [docs/branch_protection_setup.md](docs/branch_protection_setup.md) | main ブランチ保護（PM承認の強制）— リポジトリ管理者向け |
| [docs/tailscale_setup.md](docs/tailscale_setup.md) | 社外アクセス（Tailscale VPN）セットアップ |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPSメール連携セットアップ |
| [saas/CLAUDE.md](saas/CLAUDE.md) | 実装時の開発規律（絶対ルール9項目）|

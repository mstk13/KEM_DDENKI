# 入札案件管理システム

株式会社ケンモチ電機向け、電気工事の入札案件を収集・管理・分析する社内Webアプリ。
仕様書: [`../docs/spec.md`](../docs/spec.md)

## 機能

- **案件収集**（`scraper.py`）: 登録した対象サイトを巡回し、電気工事関連キーワードにマッチする案件を自動収集（重複スキップ）
- **GEPSメール取込**（`email_importer.py`）: 政府電子調達の通知メールから Gmail IMAP 経由で案件を取り込み
- **Cloudflare対応**（`pw_login.py`）: 防衛省等の Cloudflare 保護サイトに Cookie ベースで自動アクセス
- **案件管理**（`app.py`）: 一覧（フィルタ・ソート・検索・手動追加）／詳細（ステータス・費用・競合）
- **入札参加資格管理**: Excel/PDFインポート、有効期限の更新アラート（画面＋メール）
- **分析**（ダッシュボード）: 受注率・原価率・受注金額などの KPI と Plotly グラフ
- **メール通知**（`notifier.py`）: 新着案件・締め切り間近アラート・資格期限アラートを Gmail で送信
- **定期実行**（`scheduler.py`）: cron / タスクスケジューラから毎朝呼び出す

## セットアップ

```bash
cd bid_manager
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Playwright を使う場合（Cloudflare サイト巡回）
playwright install chromium

cp .env.example .env        # メール送信・GEPS取込を使う場合は編集
python database.py          # DB初期化
python seed.py              # （任意）デモデータ投入ですぐ試せる
streamlit run app.py        # アプリ起動 -> http://localhost:8501
```

> メール通知やスクレイピングを使わず、UI・分析だけ試すなら `seed.py` のデモデータだけで動きます。

### 環境変数（`.env`）

```dotenv
GMAIL_USER=your-email@gmail.com          # Gmail アドレス
GMAIL_PASSWORD=your-app-password         # Gmail アプリパスワード（2段階認証必須）
BID_EMAIL_TO=user1@example.com,user2@example.com  # 通知先（カンマ区切り）
# BID_USE_PLAYWRIGHT=1                   # JS描画サイトのスクレイピングに Playwright を使う
# BID_DB_PATH=/path/to/database.db       # DB ファイルの場所（デフォルト: カレントディレクトリ）
```

## 画面一覧（Streamlit 6画面）

| 画面 | 内容 |
|------|------|
| 案件一覧 | フィルタ・ソート・キーワード検索 + 手動追加フォーム |
| 案件詳細 | ステータス変更・費用入力（利益/原価率自動計算）・競合情報 |
| ダッシュボード | KPIカード + Plotly グラフ（月別推移・エリア別・種別・原価率分布） |
| 対象サイト管理 | スクレイピング対象URLの追加・削除・有効/無効切替・即時実行 |
| 単価マスタ | 工事種別ごとの単価登録（将来のAI見積自動提案用） |
| 入札資格管理 | Excel/PDFインポート・期限アラート・更新済マーク |

## 定期実行

```bash
# cron（毎朝6時）
0 6 * * * cd /path/to/bid_manager && /path/to/.venv/bin/python scheduler.py >> scrape.log 2>&1
```

`scheduler.py` は以下の順序で実行する:

1. 通常スクレイピング（requests/BS4で対象サイト巡回）
2. GEPS メール取込（過去1日分の通知メール）
3. Playwright 巡回（`--with-playwright` 指定時のみ、Cloudflare サイト）
4. メール通知（新着案件 or 資格期限アラートがあれば送信）

```bash
python scheduler.py                     # 通常実行
python scheduler.py --no-mail           # メール通知なし
python scheduler.py --with-playwright   # Cloudflare サイトも巡回
```

### GEPSメール取込の単独実行

```bash
python email_importer.py                # 未読の GEPS 通知を取り込み
python email_importer.py --days 7       # 過去7日分を取り込み
python email_importer.py --dry-run      # DB保存せずプレビューのみ
```

### Playwright Cookie管理

Cloudflare 保護サイトには初回のみ手動でチャレンジを通過する必要がある:

```bash
python pw_login.py                      # ブラウザが開く → Cloudflare 通過 → Cookie 保存
python pw_login.py --check              # Cookie が有効か確認
python pw_login.py --scrape             # 保存済み Cookie で案件収集
```

ターゲットサイトは `pw_targets.json` で管理。未作成ならデフォルト（防衛省 航空自衛隊・海上自衛隊 横須賀）が使われる。

## ファイル構成

| ファイル | 役割 |
|----------|------|
| `app.py` | Streamlit メインアプリ（6画面） |
| `database.py` | SQLite スキーマと CRUD（利益・原価率・差額を自動計算） |
| `scraper.py` | スクレイピング（requests/BeautifulSoup、任意で Playwright） |
| `email_importer.py` | GEPS 通知メールからの案件取込（Gmail IMAP） |
| `importer.py` | 入札参加資格の Excel/PDF インポート |
| `pw_login.py` | Playwright Cookie管理 + Cloudflare サイト巡回 |
| `notifier.py` | Gmail SMTP によるメール通知（新着案件 + 資格期限アラート） |
| `scheduler.py` | 定期実行（スクレイピング + メール取込 + 通知）エントリポイント |
| `config.py` | キーワード・エリア・ステータス・各種設定 |
| `seed.py` | デモデータ投入 |

## スクレイピングのカスタマイズ

実サイトは構造がまちまちなため、既定では「ページ内リンクのテキストをキーワードで
絞り込む」汎用抽出を行います。サイト個別に精度を上げる場合は `config.py` の
`SITE_SELECTORS` にドメイン別の CSS セレクタを指定してください。

```python
SITE_SELECTORS = {
    "example.go.jp": {"item": "table.bid tr", "title": "td.name a", "link": "td.name a"},
}
```

## データ設計（AI活用を見据えて）

仕様書 10章に基づき、金額は数値型（INTEGER）、日付は DATE 型で保存します。
将来の見積自動提案に向け、単価マスタ（`unit_prices`）と入札参加資格（`qualifications`）も初期から用意しています。
非構造化データ（PDF等）は `data/projects/<id>/` 配下で案件IDごとに管理する想定です。

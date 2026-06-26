# 入札案件管理システム

株式会社ケンモチ電機向け、電気工事の入札案件を収集・管理・分析する社内Webアプリ。
仕様書: [`../docs/spec.md`](../docs/spec.md)

## 機能

- **案件収集**（`scraper.py`）: 登録した対象サイトを巡回し、電気工事関連キーワードに
  マッチする案件を自動収集（重複スキップ）
- **案件管理**（`app.py`）: 一覧（フィルタ・ソート・検索）／詳細（ステータス・費用・競合）
- **分析**（ダッシュボード）: 受注率・原価率・受注金額などの KPI と Plotly グラフ
- **メール通知**（`notifier.py`）: 新着案件と締め切り間近アラートを Gmail で送信
- **定期実行**（`scheduler.py`）: cron / GitHub Actions から毎朝呼び出す

## セットアップ

```bash
cd bid_manager
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env        # メール送信を使う場合は編集
python database.py          # DB初期化
python seed.py              # （任意）デモデータ投入ですぐ試せる
streamlit run app.py        # アプリ起動 -> http://localhost:8501
```

> メール通知やスクレイピングを使わず、UI・分析だけ試すなら `seed.py` のデモデータだけで動きます。

## 定期実行（毎朝6時）

```bash
# crontab -e
0 6 * * * cd /path/to/bid_manager && /path/to/.venv/bin/python scheduler.py >> scrape.log 2>&1
```

メールを送らず収集だけ: `python scheduler.py --no-mail`

## ファイル構成

| ファイル | 役割 |
|----------|------|
| `app.py` | Streamlit メインアプリ（5画面） |
| `database.py` | SQLite スキーマと CRUD（利益・原価率・差額を自動計算） |
| `scraper.py` | スクレイピング（requests/BeautifulSoup、任意で Playwright） |
| `notifier.py` | Gmail SMTP によるメール通知 |
| `scheduler.py` | 定期実行（収集＋通知）エントリポイント |
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

JavaScript で描画されるサイトは `.env` で `BID_USE_PLAYWRIGHT=1` を設定し、
`playwright install chromium` を実行してください。

## データ設計（AI活用を見据えて）

仕様書 10章に基づき、金額は数値型（INTEGER）、日付は DATE 型で保存します。
将来の見積自動提案に向け、単価マスタ（`unit_prices`）も初期から用意しています。
非構造化データ（PDF等）は `data/projects/<id>/` 配下で案件IDごとに管理する想定です。

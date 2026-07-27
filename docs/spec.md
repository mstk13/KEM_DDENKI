# 入札案件管理システム 仕様書
**対象：株式会社ケンモチ電機**
**作成日：2026年6月19日**

---

## 1. システム概要

電気工事会社向けの入札案件収集・管理・原価分析を一元化するWebアプリケーション。
指定URLから毎日自動で案件を収集し、ブラウザ上で案件の進捗管理・費用管理・競合分析を行う。

---

## 2. 技術スタック

| 項目 | 技術 |
|------|------|
| 言語 | Python 3.11以上 |
| フロントエンド | Streamlit |
| バックエンド | Python（Streamlitに内包） |
| データベース | SQLite（フェーズ1〜2）→ PostgreSQL（ミニPC導入後） |
| スクレイピング | Playwright + BeautifulSoup4 |
| スケジュール実行 | Windowsタスクスケジューラ（母親PC）→ cron（ミニPC導入後） |
| メール通知 | smtplib（Gmail SMTP） |
| グラフ描画 | Plotly |
| バックアップ | Google Drive（毎日自動） |

---

## 2.1 データベース運用方針

### フェーズ1〜2：SQLite + 自動バックアップ
- 全アプリのDBはプロジェクト直下の `data/` フォルダに集約保存
- 複数PCで共有する場合は `.env` の `KEM_DATA_DIR` で共有フォルダを指定
- 毎日深夜にGoogle Driveへ自動バックアップ
- バックアップスクリプト例：
```python
import shutil, datetime

def backup_to_drive():
    date_str = datetime.date.today().strftime("%Y%m%d")
    shutil.copy("data/bid_manager.db", f"backup/bid_manager_{date_str}.db")
    # Google Drive APIでアップロード
```

### フェーズ3以降：PostgreSQLへ移行
- ミニPCにPostgreSQLをインストール
- 複数端末（母親PC・スマホ）から同時アクセス可能に
- SQLiteからPostgreSQLへのデータ移行スクリプトも作成予定

---

## 3. ディレクトリ構成

```
project/
├── app.py                  # Streamlitメインアプリ（6画面）
├── scraper.py              # スクレイピング（requests/BS4、任意で Playwright）
├── database.py             # SQLite スキーマと CRUD
├── notifier.py             # メール通知（新着案件 + 資格期限アラート）
├── scheduler.py            # 定期実行（スクレイピング + メール取込 + 通知）
├── email_importer.py       # GEPS 通知メールからの案件取込（IMAP）
├── importer.py             # 入札参加資格の Excel/PDF インポート
├── pw_login.py             # Playwright Cookie管理（Cloudflare保護サイト対応）
├── config.py               # 設定（キーワード・エリア・ステータス等）
├── seed.py                 # デモデータ投入
├── ../data/bid_manager.db  # SQLiteデータベース（data/フォルダに集約）
├── requirements.txt        # 依存パッケージ
├── browser_data/           # Playwright の Cookie 永続化フォルダ
├── pw_targets.json         # Playwright 対象サイト定義（任意）
└── .env                    # 環境変数（APIキー・パスワードなど）
```

---

## 4. データベース設計

### 4.1 案件テーブル（`projects`）

| カラム名 | 型 | 説明 |
|----------|-----|------|
| id | INTEGER PRIMARY KEY | 案件ID |
| title | TEXT | 案件名 |
| client | TEXT | 発注機関名 |
| region | TEXT | エリア（例：東京都、神奈川県） |
| category | TEXT | 工事種別（例：電気工事、電気設備） |
| deadline | DATE | 入札締め切り日 |
| budget | INTEGER | 予定価格（円）※記載がある場合 |
| source_url | TEXT | 元ページURL |
| status | TEXT | ステータス（後述） |
| created_at | DATETIME | 登録日時 |
| updated_at | DATETIME | 更新日時 |

**ステータス一覧：**
- `新着` → `検討中` → `見積作成中` → `入札済` → `受注` / `失注` / `見送り`

---

### 4.2 費用テーブル（`costs`）

| カラム名 | 型 | 説明 |
|----------|-----|------|
| id | INTEGER PRIMARY KEY | ID |
| project_id | INTEGER | 案件ID（外部キー） |
| estimate_amount | INTEGER | 提出した見積金額（円） |
| actual_cost | INTEGER | 実際の工事原価（円） |
| profit | INTEGER | 利益（自動計算：見積 - 原価） |
| profit_rate | REAL | 原価率（自動計算：%） |
| memo | TEXT | 備考 |
| updated_at | DATETIME | 更新日時 |

---

### 4.3 競合テーブル（`competitors`）

| カラム名 | 型 | 説明 |
|----------|-----|------|
| id | INTEGER PRIMARY KEY | ID |
| project_id | INTEGER | 案件ID（外部キー） |
| competitor_name | TEXT | 落札した会社名 |
| competitor_amount | INTEGER | 落札金額（円） |
| diff_amount | INTEGER | 自社との差額（自動計算） |
| source | TEXT | 情報源（例：官報、自治体サイト） |
| memo | TEXT | 備考 |

---

### 4.4 対象サイトテーブル（`scrape_targets`）

| カラム名 | 型 | 説明 |
|----------|-----|------|
| id | INTEGER PRIMARY KEY | ID |
| name | TEXT | サイト名（例：東京都電子調達） |
| url | TEXT | スクレイピング対象URL |
| region | TEXT | エリア |
| is_active | BOOLEAN | 有効/無効 |
| last_scraped_at | DATETIME | 最終取得日時 |

---

### 4.5 入札参加資格テーブル（`qualifications`）

| カラム名 | 型 | 説明 |
|----------|-----|------|
| id | INTEGER PRIMARY KEY | ID |
| issuer | TEXT | 発注先（例：国土交通省、財務省(関東財務局)） |
| category | TEXT | 認定種目（例：電気工事、電気通信） |
| grade | TEXT | 等級（A, B, C, D） |
| keisin_score | INTEGER | 経審点数 |
| total_score | INTEGER | 総合点数 |
| vendor_number | TEXT | 業者番号 |
| valid_from | DATE | 有効期間開始日 |
| valid_until | DATE | 有効期間終了日 |
| application_type | TEXT | 申請区分（一元定期、随時申請） |
| application_method | TEXT | 申請方法（インターネット、郵送） |
| renewed | INTEGER | 更新済みフラグ（0=未更新, 1=更新済） |
| memo | TEXT | 備考 |
| imported_at | DATETIME | インポート日時 |
| updated_at | DATETIME | 更新日時 |

**データ投入方法：** Excel（.xlsx）またはPDF（.pdf）をStreamlit UIからアップロードしてインポート。
**更新アラート：** 有効期限の1ヶ月前（黄色警告）と当月（赤色警告）に画面とメールで通知。更新済みにチェックすればアラートは消える。

---

## 5. 機能仕様

### 5.1 フェーズ1：案件収集・一覧表示

#### スクレイピング（`scraper.py`）
- `scrape_targets`テーブルに登録されたURLを順番に取得
- 電気工事関連キーワードでフィルタリング
  - 対象キーワード：`電気工事` `電気設備` `照明` `配線` `受変電` `幹線` `動力` `弱電`
- 新規案件のみDBに保存（重複チェックあり）
- 毎朝6時に自動実行（cron設定）
- 取得方式は2系統：
  - 既定: requests + BeautifulSoup（軽量・静的HTML向け）
  - `BID_USE_PLAYWRIGHT=1`: Playwright（JavaScript描画サイト向け）
- サイト個別の精度向上は `config.SITE_SELECTORS` で CSS セレクタを指定

#### GEPSメール取込（`email_importer.py`）
- GEPS（政府電子調達）の通知メールを Gmail IMAP で取得し、案件としてDBに登録
- 送信元・件名に「調達」「GEPS」「p-portal」「入札」を含むメールを検索
- メール本文から調達案件名・調達機関・所在地・締切日・URLをパースして抽出
- 使い方：
  - `python email_importer.py` — 未読のGEPS通知を取り込み
  - `python email_importer.py --days 7` — 過去7日分を取り込み
  - `python email_importer.py --dry-run` — DB保存せずプレビューのみ
- 前提: Gmail で IMAP 有効化済み、`.env` に `GMAIL_USER` / `GMAIL_PASSWORD`（アプリパスワード）設定済み

#### Playwright Cookie管理（`pw_login.py`）
- Cloudflare 保護サイト（防衛省等）への Cookie ベースのアクセスを管理
- 初回はブラウザを開いて手動で Cloudflare チャレンジを通過 → Cookie が `browser_data/` に永続化
- 2回目以降は保存済み Cookie で自動アクセス
- 使い方：
  - `python pw_login.py` — Cookie 保存（初回/更新時）
  - `python pw_login.py --check` — Cookie の有効性確認
  - `python pw_login.py --scrape` — 保存済み Cookie で案件収集
- ターゲットサイトは `pw_targets.json` で管理（デフォルト: 防衛省 航空自衛隊・海上自衛隊 横須賀）

#### 案件一覧画面（Streamlit）
- 案件をテーブル形式で表示
- **手動追加フォーム**: 案件名・発注機関・エリア・工事種別・締切日・予定価格・URLを入力して手動登録
- フィルタ機能
  - ステータス
  - エリア
  - 締め切り日（〇日以内）
  - キーワード検索
- ソート機能（締め切り日順、登録日順）
- 各案件をクリックで詳細画面へ

---

### 5.2 フェーズ2：案件詳細・ステータス・費用管理

#### 案件詳細画面
- 案件の基本情報表示
- ステータス変更ボタン（ドロップダウン）
- 費用入力フォーム
  - 見積金額
  - 実際の工事原価
  - 利益・原価率（自動計算・表示）
- 失注時の競合情報入力フォーム
  - 落札会社名
  - 落札金額
  - 自社との差額（自動計算）
- メモ欄（自由記述）

---

### 5.3 フェーズ3：分析・可視化

#### ダッシュボード画面
- **KPIカード表示**
  - 今月の入札件数
  - 受注件数・受注率
  - 平均原価率
  - 今月の受注金額合計

- **グラフ（Plotly）**
  - 月別受注率の推移（折れ線グラフ）
  - エリア別・案件種別の受注率（棒グラフ）
  - 原価率の分布（ヒストグラム）
  - 競合との価格差分析（散布図）

---

### 5.4 メール通知（`notifier.py`）

- 毎朝スクレイピング後に自動送信
- 送信内容
  - 新着案件の件数
  - 案件一覧（案件名・発注機関・締め切り・予定価格・URL）
  - 締め切りが3日以内の案件のアラート
  - **入札参加資格の更新アラート**（今月中に期限切れ / 来月に期限切れ）
- 送信先：設定ファイルで複数アドレス指定可能
- 新着案件がなくても資格期限アラートがあればメール送信する

---

### 5.5 入札参加資格管理

#### 資格管理画面（Streamlit）
- Excel（.xlsx）または PDF（.pdf）をアップロードしてインポート（`importer.py`）
- インポート時にプレビュー表示 → 確認後にDB保存
- 既存データを全置き換え or 追記を選択可能
- 登録済み資格の一覧表示（発注先・更新状態でフィルタ）
- 「更新済み」マーク機能（チェックするとアラートが消える）

#### 更新アラート
- **当月中に有効期限が切れる資格**: 赤い警告（画面 + メール通知）
- **来月中に有効期限が切れる資格**: 黄色い注意（画面 + メール通知）
- サイドバーにもアラートバッジ（期限60日以内の未更新件数）を表示

#### ファイルインポート（`importer.py`）
- **Excel**: openpyxl でパース。B列=発注先, C=認定種目, D=等級, E=経審, F=総合, G=業者番号, H=認定開始, K=申請区分, L=申請方法
  - 発注先が空の行は直前の発注先を引き継ぐ（〃マーク対応）
  - ヘッダー行（1-5行目）から有効期限テキストを自動抽出
  - シート名に「官公庁」「資格」を含むシートを優先
- **PDF**: pdfplumber でテーブル抽出。列順は Excel と同様と仮定

---

## 6. 設定ファイル（`config.py`）

```python
# スクレイピング対象キーワード
KEYWORDS = ["電気工事", "電気設備", "照明", "配線", "受変電", "幹線", "動力", "弱電"]

# 対象エリア
REGIONS = ["東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県"]

# メール設定
EMAIL_FROM = "your-email@gmail.com"
EMAIL_TO = ["mother@example.com"]
EMAIL_SUBJECT = "【入札案件】本日の新着案件通知"

# スクレイピング間隔（秒）
SCRAPE_INTERVAL = 2
```

---

## 7. 環境変数（`.env`）

```dotenv
GMAIL_USER=your-email@gmail.com          # GEPS 通知の受信先 Gmail アドレス
GMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx       # Gmail アプリパスワード（2段階認証 → アプリパスワード発行）
BID_EMAIL_TO=manager@example.com         # 新着案件の通知メール送信先（カンマ区切り）
```

### GEPS 連携

案件の自動収集は GEPS（政府電子調達）の調達情報通知メールを利用する。
サイトスクレイピングと違い、サイト構造の変更に影響されず、全省庁の案件を網羅できる。

**セットアップ手順は [`docs/geps_setup.md`](geps_setup.md) を参照。**

```
GEPS で通知条件設定 → Gmail にメールが届く → email_importer.py が自動取り込み → アプリに表示
```

---

## 8. 開発フェーズとスケジュール

| フェーズ | 内容 | 優先度 | 状態 |
|----------|------|--------|------|
| Phase 1 | DB設計・スクレイピング・案件一覧表示 | 高 | ✅ 完了 |
| Phase 2 | ステータス管理・費用入力・競合情報入力 | 高 | ✅ 完了 |
| Phase 3 | ダッシュボード・グラフ分析 | 中 | ✅ 完了 |
| Phase 4 | メール通知・cron設定 | 中 | ✅ 完了 |
| Phase 5 | 対象サイト管理画面（URLをUI上で追加・削除） | 低 | ✅ 完了 |
| Phase 6 | 単価マスタ管理画面 | 中 | ✅ 完了 |
| Phase 7 | 入札参加資格管理（Excel/PDFインポート・更新アラート） | 高 | ✅ 完了 |
| Phase 8 | GEPS メール取込・Playwright Cloudflare 対応 | 中 | ✅ 完了 |
| Phase 9 | 案件の手動追加フォーム | 中 | ✅ 完了 |

---

## 9. 定期実行の詳細（`scheduler.py`）

毎朝 cron / Windows タスクスケジューラから呼び出す。以下の順序で実行する:

1. **通常スクレイピング** — `scraper.py` で `scrape_targets` の有効サイトを巡回（requests/BS4）
2. **GEPSメール取込** — `email_importer.py` で過去1日分の通知メールから案件を取得
3. **Playwright巡回（オプション）** — `--with-playwright` 指定時に `pw_login.py` で Cloudflare サイトも収集
4. **メール通知** — 新着案件 or 資格期限アラートがあればメール送信

```bash
# cron 例（毎朝6時）
0 6 * * * cd /path/to/bid_manager && /path/to/.venv/bin/python scheduler.py >> scrape.log 2>&1

# オプション
python scheduler.py                     # 通常実行（スクレイピング + メール取込 + 通知）
python scheduler.py --no-mail           # メール通知なし
python scheduler.py --with-playwright   # Cloudflare サイトも巡回
```

---

## 10. AI活用を見据えたデータ設計

### 10.1 基本方針

データを「構造化データ」と「非構造化データ」に分けて管理する。
将来のAI自動化に備え、今から正しい形式でデータを蓄積しておくことが重要。

---

### 10.2 構造化データ（SQLite）

機械が読みやすい数値・日付・テキストのデータ。今すぐSQLiteで管理する。

| テーブル | 用途 | AI活用イメージ |
|----------|------|---------------|
| projects | 案件情報 | 受注確率予測の学習データ |
| costs | 費用・原価 | 見積金額の自動提案 |
| competitors | 競合情報 | 落札金額の予測 |
| unit_prices | 単価マスタ | 見積書の自動生成 |

**重要ルール：**
- 金額は必ず数値型（INTEGER）で保存（「約100万円」はNG、`1000000`で保存）
- 日付は必ずDATE型で保存
- メモ欄には「なぜこの金額にしたか」「どこで負けたか」を積極的に記述する

---

### 10.3 単価マスタテーブル（`unit_prices`）※新規追加

AI見積もり自動化の精度を上げるために今から作成しておく。

| カラム名 | 型 | 説明 |
|----------|-----|------|
| id | INTEGER PRIMARY KEY | ID |
| category | TEXT | 工事種別（例：電気工事・照明設備） |
| item_name | TEXT | 項目名（例：VVFケーブル2.0mm） |
| unit | TEXT | 単位（例：m・本・式） |
| unit_price | INTEGER | 単価（円） |
| memo | TEXT | 備考 |
| updated_at | DATETIME | 更新日時 |

---

### 10.4 非構造化データ（ファイルストレージ）

PDFや書類などAIが参照するための生データ。案件IDでフォルダ管理する。

```
/data
  /projects
    /project_001
      - 仕様書.pdf
      - 見積書.pdf
      - 完了報告書.pdf
    /project_002
      - 仕様書.pdf
      - 見積書.pdf
  /templates
    - 見積書テンプレート.xlsx
    - 入札書類テンプレート.docx
```

---

### 10.5 将来のAI活用ロードマップ

| フェーズ | やりたいこと | 必要なデータ |
|----------|-------------|-------------|
| AI-1 | 見積金額の自動提案 | 過去の案件・原価・落札金額履歴 |
| AI-2 | 受注確率の予測 | 競合情報・エリア・金額・受注履歴 |
| AI-3 | 見積書の自動生成 | 過去の見積書・単価マスタ・仕様書PDF |
| AI-4 | 入札書類の自動作成 | 過去の提出書類・案件情報 |
| AI-5 | 過去書類のAI検索 | 全書類をベクトルDB（ChromaDB）に変換 |

---

### 10.6 ベクトルDB（AI検索用・将来対応）

過去の書類をAIが検索・参照できる形に変換するための仕組み。
Phase 3以降に導入予定。

- **ツール：** ChromaDB または Qdrant（どちらも無料・ローカル動作可能）
- **用途：** 「この案件に似た過去案件を探す」「この仕様書に合う見積もりを自動提案する」

---

## 10.7 RAG（Retrieval-Augmented Generation）実装計画

### RAGとは
AIモデル自体を再訓練するのではなく、蓄積したデータをAIに「参照」させて回答させる仕組み。
データが100件程度貯まったタイミングで実装を開始する。

---

### RAG実装フェーズ

| フェーズ | 内容 | 必要なデータ量 | 使用ツール |
|----------|------|---------------|-----------|
| RAG-1 | 類似案件の検索・提案 | 50件以上 | ChromaDB + Claude API |
| RAG-2 | 見積金額の自動提案 | 100件以上 | ChromaDB + Claude API |
| RAG-3 | 受注確率の予測 | 200件以上 | ChromaDB + Claude API |
| RAG-4 | 見積書・書類の自動生成 | 300件以上 | ChromaDB + Claude API |

---

### RAG-1 実装イメージ（類似案件の検索）

```python
# ユーザーが新着案件を見たときに類似過去案件を自動提案
def suggest_similar_projects(new_project):
    # 1. 新着案件のテキストをベクトル化
    # 2. ChromaDBで類似案件を検索
    # 3. Claude APIに過去案件データを渡して分析

    prompt = f"""
    新着案件：{new_project}
    類似過去案件：{similar_projects}

    以下を提案してください：
    1. 適切な見積金額の範囲
    2. 受注できた理由・失注した理由
    3. 競合との差別化ポイント
    """

    response = claude_api.call(prompt)
    return response
```

---

### RAGに必要なデータの流れ

```
SQLite（構造化データ）
  └── 案件情報・費用・競合データ
          ↓ 定期的に変換
ChromaDB（ベクトルDB）
  └── 過去案件の埋め込みベクトル
          ↓ 類似検索
Claude API（RAG）
  └── 参照データをもとに回答生成
          ↓
Streamlit UI
  └── 見積提案・受注予測・書類生成
```

---

### 今からやっておくべきこと（RAG準備）

1. **メモ欄を必ず埋める**：「なぜこの金額にしたか」「どこで負けたか」を記述する
2. **金額は必ず数値型で保存**：テキストで入力しない
3. **案件種別を統一する**：「電気工事」「電気設備」など表記を揃える
4. **書類はフォルダに保存**：案件IDでフォルダ管理を徹底する

---

## 11. 今後追加予定の機能（バックログ）

- 見積書の自動生成（PDF出力）
- 公的機関への提出書類テンプレート管理
- 入札結果の自動取得（落札情報ページのスクレイピング）
- スマホ対応（Streamlitはレスポンシブ対応済み）
- Discord通知連携（新着案件・締め切りアラート）
- ChromaDBによる過去書類のAI検索
- 見積金額の自動提案（AI-1）
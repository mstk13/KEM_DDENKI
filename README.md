# KEM_DENKI — 入札案件管理システム

株式会社ケンモチ電機向け、電気工事の入札案件を収集・管理・分析する社内Webアプリです。

---

## 別のPCでセットアップする手順

### 必要なもの

- **Python 3.11 以上**（https://www.python.org/downloads/ からインストール）
- **Git**（https://git-scm.com/downloads からインストール）

### 手順（Windows / Mac / Linux 共通）

```bash
# 1. リポジトリをダウンロード
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI/bid_manager

# 2. Python 仮想環境を作成して依存パッケージをインストール
python -m venv .venv

# Windows の場合:
.venv\Scripts\activate
# Mac / Linux の場合:
source .venv/bin/activate

pip install -r requirements.txt

# 3. データベースを初期化
python database.py

# 4. 環境変数を設定（GEPS メール取込 & 通知を使う場合）
cp .env.example .env
# .env をテキストエディタで開いて Gmail 情報を入力（後述）

# 5. アプリを起動
streamlit run app.py
```

ブラウザで **http://localhost:8501** が自動で開きます。

> **Python も Git もわからない場合**: このリポジトリの ZIP をダウンロード（GitHub の「Code」→「Download ZIP」）して展開し、手順2から始めてください。

---

## 初回セットアップ（1回だけやること）

### 1. 入札参加資格を登録する

アプリの「入札資格管理」画面で、お持ちの資格一覧 Excel をアップロードしてください。

- **一度登録すれば、有効期限が近づくまで何もしなくて OK**
- 期限の2ヶ月前から画面に警告が出ます
- 更新手続きが完了したら「更新済み」にチェックすれば警告が消えます

### 2. GEPS メール連携を設定する（案件の自動収集）

GEPS（政府電子調達）の通知メールを使って案件を自動収集します。

詳しい手順は **[docs/geps_setup.md](docs/geps_setup.md)** を参照してください。

概要:
1. Gmail で2段階認証ON → アプリパスワード発行 → IMAP有効化
2. GEPS（https://www.geps.go.jp/）で調達情報通知を設定（電気工事・関東エリア）
3. `.env` ファイルに Gmail 情報を入力
4. 動作確認: `python email_importer.py --dry-run --days 7`

---

## 日常の運用

### 毎朝（自動）

`scheduler.py` を毎朝自動実行すると:
1. GEPS メールから新着案件を取り込み
2. 新着案件や締切間近の案件をメールで通知
3. 入札資格の期限アラートもメールに含まれる

```bash
# Windows タスクスケジューラ に登録する場合:
#   プログラム: C:\...\KEM_DDENKI\bid_manager\.venv\Scripts\python.exe
#   引数:       scheduler.py
#   開始:       C:\...\KEM_DDENKI\bid_manager
#   トリガー:   毎日 6:00

# Linux / Mac の cron に登録する場合:
# crontab -e で以下を追加
0 6 * * * cd /path/to/KEM_DDENKI/bid_manager && /path/to/.venv/bin/python scheduler.py >> scrape.log 2>&1
```

### 案件を確認するとき

1. `streamlit run app.py` でアプリを起動（または常時起動しておく）
2. **案件一覧**: 新着案件を確認。未入力項目があれば警告が出る
3. **案件詳細**: 元ページURLを開いて確認し、発注機関・エリア・工事種別・締切日・予定価格を入力
4. ステータスを「新着」→「検討中」→「見積作成中」→「入札済」→「受注」or「失注」に更新

### 案件を手動で追加するとき

案件一覧画面の「案件を手動で追加」フォームから登録できます。

### 見積・原価を管理するとき

案件詳細画面で:
- **見積金額** と **実際の工事原価** を入力 → 利益と原価率が自動計算
- 失注した場合、**競合の落札会社名・金額** を入力 → 自社との差額が自動計算

---

## 画面一覧

| 画面 | 内容 |
|------|------|
| 案件一覧 | フィルタ・ソート・キーワード検索 + 手動追加 |
| 案件詳細 | 基本情報の編集・ステータス・費用・競合情報 |
| ダッシュボード | 受注率・原価率・受注金額の KPI とグラフ |
| 対象サイト管理 | スクレイピング対象URLの管理 |
| 単価マスタ | 工事種別ごとの単価登録 |
| 入札資格管理 | Excel/PDF インポート・期限アラート |

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様・AI活用計画） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ手順 |
| [bid_manager/README.md](bid_manager/README.md) | 開発者向けの詳細情報 |

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `python` コマンドが見つからない | Python をインストールして、パスを通す |
| `streamlit run app.py` でエラー | `.venv` を activate しているか確認 |
| アプリが開かない | http://localhost:8501 をブラウザで直接開く |
| GEPS メールが取り込めない | `.env` の Gmail 情報を確認。`python email_importer.py --dry-run` でテスト |
| 画面が英語になる | ブラウザの言語設定を日本語にする |

# GEPS 調達情報通知 セットアップガイド

GEPS（政府電子調達システム）の調達情報通知を Gmail で受け取り、
本システムが自動で案件を取り込む仕組みを設定する手順書です。

---

## 全体の流れ

```
GEPS で通知条件を設定（電気工事のキーワードで）
    ↓
条件に合う案件が出ると Gmail にメールが届く
    ↓
email_importer.py が毎朝メールを読んで案件を DB に保存
    ↓
Streamlit アプリで案件一覧に表示される
    ↓
notifier.py が新着案件の通知メールを送る（任意）
```

---

## STEP 1: Gmail の準備

### 1-1. 2段階認証を有効にする

1. https://myaccount.google.com/security にアクセス
2. 「2段階認証プロセス」→ 有効にする
3. 電話番号で認証コードを受け取る設定をする

### 1-2. アプリパスワードを発行する

1. https://myaccount.google.com/apppasswords にアクセス
2. アプリ名に「入札管理」と入力して「作成」
3. 表示される **16文字のパスワード**（例: `abcd efgh ijkl mnop`）をメモする
   - これが `.env` の `GMAIL_PASSWORD` に入る値
   - 通常のGmailパスワードとは別物

### 1-3. IMAP を有効にする

1. Gmail を開く → 右上の歯車 → 「すべての設定を表示」
2. 「メール転送と POP/IMAP」タブ
3. 「IMAP アクセス」→ **IMAP を有効にする** を選択
4. 「変更を保存」

---

## STEP 2: GEPS で調達情報通知を設定する

### 2-1. GEPS にアクセス

1. https://www.geps.go.jp/ にアクセス
2. 「調達情報の検索」→「調達情報の通知登録」へ進む
   - ※ 利用者登録が必要な場合は先に登録する（無料）

### 2-2. 通知条件を設定する

以下の条件でメール通知を設定する:

| 設定項目 | 値 |
|----------|-----|
| 通知先メールアドレス | STEP 1 で準備した Gmail アドレス |
| 業種 | **電気** を含む項目を選択 |
| 地域 | 関東（東京都・神奈川県・埼玉県・千葉県・茨城県・栃木県・群馬県） |
| キーワード（あれば） | `電気工事` `電気設備` `照明` `受変電` `配線` `幹線` `動力` `弱電` |

> **ポイント**: 条件を広めに設定しておく方が取りこぼしが少ない。
> 不要な案件は Streamlit の画面上で「見送り」にすればよい。

### 2-3. 通知の確認

設定後、条件に合う案件が公告されると GEPS からメールが届く。
まずは手動でメールが届くことを確認する。

---

## STEP 3: 本システムの設定

### 3-1. `.env` ファイルを作成する

```bash
cd bid_manager
cp .env.example .env
```

`.env` を編集:

```dotenv
GMAIL_USER=your-email@gmail.com
GMAIL_PASSWORD=abcd-efgh-ijkl-mnop
BID_EMAIL_TO=your-email@gmail.com
```

### 3-2. 動作確認（手動取り込み）

```bash
# まず DB を初期化（初回のみ）
python database.py

# GEPS メールのプレビュー（DB には保存しない）
python email_importer.py --dry-run --days 7

# 実際に取り込み
python email_importer.py --days 7

# アプリで確認
streamlit run app.py
```

### 3-3. 定期実行の設定

#### Linux / WSL（cron）

```bash
crontab -e
```

以下を追加（毎朝6時に実行）:

```
0 6 * * * cd /path/to/bid_manager && /path/to/.venv/bin/python scheduler.py >> /path/to/scrape.log 2>&1
```

#### Windows（タスクスケジューラ）

1. 「タスクスケジューラ」を開く
2. 「基本タスクの作成」→ 名前: `入札案件取り込み`
3. トリガー: 毎日 6:00
4. 操作: プログラムの開始
   - プログラム: `C:\path\to\.venv\Scripts\python.exe`
   - 引数: `scheduler.py`
   - 開始ディレクトリ: `C:\path\to\bid_manager`

---

## STEP 4: 運用開始後の確認

### 毎朝の自動処理

`scheduler.py` が毎朝以下を実行する:

1. GEPS メールから新着案件を取り込み
2. 新着案件 + 資格期限アラートをメールで通知

### ログの確認

```bash
# 直近のログを確認
tail -50 scrape.log
```

正常時のログ例:

```
[scraper] [防衛省 航空自衛隊 調達情報] found=0 saved=0 OK
[email] GEPS メールから 3 件を新規保存

合計 新着 3 件
メール通知を送信しました -> manager@example.com
```

### メールが届かない場合

1. Gmail の IMAP が有効か確認
2. アプリパスワードが正しいか確認
3. GEPS の通知設定でメールアドレスが正しいか確認
4. 手動テスト: `python email_importer.py --dry-run --days 7`

---

## トラブルシューティング

| 症状 | 原因と対処 |
|------|-----------|
| `GMAIL_USER / GMAIL_PASSWORD が .env に設定されていません` | `.env` ファイルが存在しない or 値が空 |
| `imaplib.IMAP4.error: LOGIN failed` | アプリパスワードが間違っている / 2段階認証が無効 |
| メールは届いているが案件が取り込まれない | メール本文の形式が想定と異なる → `--dry-run` でパース結果を確認 |
| 重複案件が登録される | 案件名が微妙に異なる場合は別案件として登録される（仕様） |

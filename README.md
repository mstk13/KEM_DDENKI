# KEM_DENKI — 入札案件管理システム

株式会社ケンモチ電機向け、電気工事の入札案件を収集・管理・分析する社内Webアプリです。

---

## 別のPCでセットアップする手順

### 必要なもの

- **Python 3.11 以上**（https://www.python.org/downloads/ からインストール）
  - インストール時に「**Add Python to PATH**」に必ずチェックを入れる
- **Git**（https://git-scm.com/downloads からインストール）
  - Git がなくても ZIP ダウンロードで代用可能（後述）

---

### 手順（Windows）

**PowerShell** を開いて（スタートメニューで「PowerShell」と検索）以下を実行:

```powershell
# 1. リポジトリをダウンロード
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI\bid_manager

# 2. 必要なパッケージをインストール（1〜2分かかります）
python -m python -m pip install -r requirements.txt

# 3. データベースを初期化（初回のみ）
python database.py

# 4. アプリを起動
python -m python -m streamlit run app.py
```

ブラウザで **http://localhost:8501** が自動で開きます。

> **`python` や `pip` が見つからないと言われたら:**
> `py -m python -m pip install -r requirements.txt` と `py -m python -m streamlit run app.py` を試してください。

> **Git がない場合:**
> GitHub（https://github.com/mstk13/KEM_DDENKI）で「Code」→「Download ZIP」をクリックしてダウンロード → 展開 → `bid_manager` フォルダで手順2から。

---

### 手順（Mac / Linux）

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI/bid_manager
pip3 install -r requirements.txt
python3 database.py
python -m streamlit run app.py
```

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

### 3. `.env` ファイルを作成する

`bid_manager` フォルダに `.env` という名前のテキストファイルを作り、以下を入力:

```
GMAIL_USER=あなたのGmail@gmail.com
GMAIL_PASSWORD=xxxx-xxxx-xxxx-xxxx
BID_EMAIL_TO=通知を送りたいアドレス@example.com
```

> **GMAIL_PASSWORD** は Gmail のパスワードではなく「アプリパスワード」です。
> Google アカウント → セキュリティ → 2段階認証 → アプリパスワード で発行。

---

## 日常の運用

### アプリの起動方法

PowerShell で:
```powershell
cd C:\...\KEM_DDENKI\bid_manager
python -m streamlit run app.py
```
（`C:\...` の部分はダウンロードした場所に読み替え）

### 毎朝の自動実行（任意）

`scheduler.py` を毎朝自動実行すると:
1. GEPS メールから新着案件を取り込み
2. 新着案件や締切間近の案件をメールで通知
3. 入札資格の期限アラートもメールに含まれる

**Windows タスクスケジューラに登録する方法:**
1. スタートメニューで「タスク スケジューラ」を検索して開く
2. 「基本タスクの作成」をクリック
3. 名前: `入札案件 自動取込`
4. トリガー: 毎日 / 6:00
5. 操作: プログラムの開始
   - プログラム: `python`（または `py`）
   - 引数: `scheduler.py`
   - 開始: `C:\...\KEM_DDENKI\bid_manager`

### 案件を確認するとき

1. アプリを起動
2. **案件一覧**: 新着案件を確認。未入力項目があれば警告が出る
3. **案件詳細**: 元ページURLを開いて確認し、発注機関・エリア・工事種別・締切日・予定価格を入力
4. ステータスを「新着」→「検討中」→「見積作成中」→「入札済」→「受注」or「失注」に更新

### 案件を手動で追加するとき

案件一覧画面の「➕ 案件を手動で追加」フォームから登録できます。
防衛省などのサイトをブラウザで見ながら、気になる案件を入力してください。

### 見積・原価を管理するとき

案件詳細画面で:
- **見積金額** と **実際の工事原価** を入力 → 利益と原価率が自動計算
- 失注した場合、**競合の落札会社名・金額** を入力 → 自社との差額が自動計算

---

## 防衛省などの Cloudflare 保護サイト

防衛省（mod.go.jp）のサイトは自動アクセスがブロックされるため、以下の方法で対応:

```powershell
# 初回: ブラウザが開く → チェックマークをクリックして通過 → Cookie が保存される
python pw_login.py

# 以後: 保存した Cookie で自動取得
python pw_login.py --scrape
```

Cookie の有効期限が切れたら再度 `python pw_login.py` を実行してください。

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

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `python` が見つからない | `py` を使う。それもダメなら Python を再インストール（PATH にチェック） |
| `pip install` でエラー | `py -m python -m pip install -r requirements.txt` を試す |
| `streamlit` が見つからない | `py -m python -m streamlit run app.py` を使う |
| アプリが開かない | http://localhost:8501 をブラウザで直接開く |
| GEPS メールが取り込めない | `.env` の Gmail 情報を確認。`python email_importer.py --dry-run` でテスト |
| 資格データが消えた | Excel を再アップロードすれば復元される（`data/qualifications.json` からも自動復元） |

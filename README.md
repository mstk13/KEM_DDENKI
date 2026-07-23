# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

株式会社ケンモチ電機向けの社内Webアプリ群です。  
入札案件の収集から材料管理・作業日報まで、電気工事の業務フローを一気通貫でカバーします。

---

## アプリを開く（起動後にクリック）

> `start.bat`（Windows）または `./start_all.sh`（Mac/Linux）で起動した後、以下のリンクからアクセスできます。

| アプリ | URL |
|--------|-----|
| **入札案件管理** | [http://localhost:8501](http://localhost:8501) |
| **材料管理** | [http://localhost:5000](http://localhost:5000) |
| **作業日報** | [http://localhost:8502](http://localhost:8502) |
| **人事評価** | [http://localhost:8503](http://localhost:8503) |

---

## アプリケーション一覧

| # | アプリ | ディレクトリ | フレームワーク | ポート | 概要 |
|---|--------|-------------|---------------|--------|------|
| 1 | [入札案件管理](#1-入札案件管理-bid_manager) | `bid_manager/` | Streamlit | 8501 | 入札案件の収集・進捗管理・費用分析・競合分析 |
| 2 | [材料管理](#2-材料管理-material_manager) | `material_manager/` | Flask | 5000 | 現場ごとの見積もり vs 発注状況の比較管理 |
| 3 | [作業日報](#3-作業日報-作業日報) | `sagyo-nippou/` | Streamlit | 8502 | 現場の作業日報の入力・管理・集計・分析 |
| 4 | [人事評価](#4-人事評価-evaluation) | `evaluation/` | Streamlit | 8503 | 作業日報連携の人事評価（事務方・現場方・役員） |
| 5 | [ポータル](#5-ポータル-portal) | `portal/` | 静的HTML | — | 全アプリへのランチャーページ |
| — | コスト分析・AI見積もり | （開発予定） | — | — | 過去実績から見積もりを自動生成（データ蓄積フェーズ） |

### データの流れ

```
入札案件管理（案件収集・入札）
    ↓ 受注
材料管理（見積もり→発注→受領の追跡）
    ↓ 施工中
作業日報（作業員・時間・交通費の記録）
    ↓                ↓
人事評価（勤怠データ連携）  コスト分析・AI見積もり ← 将来
```

---

## 1. 入札案件管理 (`bid_manager/`)

電気工事の入札案件を収集・管理・分析するWebアプリ。

### 主な機能

- **案件自動収集**: GEPS（政府電子調達）通知メール + Webスクレイピング
- **ステータス管理**: 新着 → 検討中 → 見積作成中 → 入札済 → 受注/失注
- **費用分析**: 見積金額 vs 実原価の利益率・原価率を自動計算
- **競合分析**: 落札会社名・金額を記録し、自社との差額を分析
- **入札参加資格管理**: Excel/PDFインポート、期限2ヶ月前から警告表示
- **メール通知**: 新着案件・締切間近・資格期限のアラートを自動送信
- **防衛省対応**: Cloudflare保護サイトのCookie認証によるスクレイピング

### 画面構成（6画面）

| 画面 | 内容 |
|------|------|
| 案件一覧 | フィルタ・ソート・キーワード検索 + 手動追加 |
| 案件詳細 | 基本情報の編集・ステータス・費用・競合情報 |
| ダッシュボード | 受注率・原価率・受注金額の KPI とグラフ |
| 対象サイト管理 | スクレイピング対象URLの管理 |
| 単価マスタ | 工事種別ごとの単価登録 |
| 入札資格管理 | Excel/PDF インポート・期限アラート |

### セットアップ

```bash
cd bid_manager
pip install -r requirements.txt
python database.py          # DB初期化（初回のみ）
streamlit run app.py        # → http://localhost:8501
```

> GEPS メール連携の詳細は [docs/geps_setup.md](docs/geps_setup.md) を参照。

---

## 2. 材料管理 (`material_manager/`)

工事現場ごとに、見積もりの品目と実際の発注状況を比較管理するWebアプリ。

### 主な機能

- **見積もり管理**: Excelインポートで品目別の見積もり明細を登録（版管理対応）
- **発注追跡**: 分割発注に対応、品目クリックで発注履歴をドリルダウン
- **消化率の可視化**: 見積もり vs 発注の消化率を色分け表示（超過:赤 / 完了:緑）
- **発注書PDFインポート**: PDFから発注内容を自動マッチング
- **受領書アップロード**: 現場での受領確認を記録
- **単価履歴の自動蓄積**: 将来のAI見積もり自動生成に向けたデータ蓄積

### データ構造

| テーブル | 用途 |
|----------|------|
| `project` | 入札〜施工〜完了の全ライフサイクル |
| `item_master` | 全現場共通の品目マスタ |
| `supplier` | 仕入先マスタ |
| `estimate_header` / `estimate_line` | 見積もり（版管理+品目別明細） |
| `order` | 発注レコード（分割対応） |
| `price_history` | 単価履歴（AI学習データ） |

### セットアップ

```bash
cd material_manager
pip install -r requirements.txt
python -c "from db import init_db; init_db()"
python app.py               # → http://localhost:5000
```

---

## 3. 作業日報 (`sagyo-nippou/`)

電気工事現場の作業日報を入力・管理・分析するWebアプリ。  
紙の日報フォームに準拠し、スマホでの音声入力にも対応。

### 主な機能

- **日報入力**: 現場名・作業員・作業時間・残業・宿泊・使用資材を記録（作業時間は自動計算）
- **音声入力対応**: スマホのマイク入力で現場から直接入力可能
- **作業員名の漢字変換**: ひらがな/カタカナ入力を作業員名簿から漢字に自動変換
- **協力会社管理**: 会社名・人数・交通費・承認状況を記録
- **ダッシュボード**: KPIカード + Plotlyグラフ（日別推移・作業員別・現場別）
- **メール通知**: 日報サマリをGmailで自動送信

### 画面構成（6画面）

| 画面 | 内容 |
|------|------|
| 日報入力 | 作業日・作業員・現場・天気・作業時間・進捗・使用資材を入力 |
| 日報一覧 | 期間/作業員/現場/状態/キーワードで絞り込み・総時間集計 |
| 日報詳細 | 内容表示・ステータス/進捗/内容の編集・削除 |
| ダッシュボード | KPIカード + Plotly グラフ |
| 作業員管理 | 作業員の追加・有効/無効切替 |
| 現場管理 | 現場の追加・ステータス変更 |

### セットアップ

```bash
cd sagyo-nippou
pip install -r requirements.txt
python database.py          # DB初期化
python seed.py              # （任意）デモデータ投入
streamlit run app.py --server.port 8502  # → http://localhost:8502
```

---

## 4. 人事評価 (`evaluation/`)

事務方・現場方・役員の3役割で人事評価を行うWebアプリ。  
作業日報アプリの勤怠データを自動参照し、評価の参考値を提示します。

### 主な機能

- **作業日報連携**: 対象者の出勤日数・作業時間・残業時間を自動取得し、「勤怠・規律」の参考スコアを自動計算
- **3役割の評価基準**: 共通項目（35点）+ 役割固有項目（65点）= 100点満点
- **現場方の択一評価**: 9（後輩指導/シニア）と10（学ぶ姿勢/ジュニア）は対象者のレベルに応じてどちらか一方のみ採点
- **評価ランク自動判定**: S（90〜100）/ A（75〜89）/ B（60〜74）/ C（40〜59）/ D（0〜39）
- **評価履歴管理**: 過去の評価を一覧表示・詳細確認

### 画面構成（3画面）

| 画面 | 内容 |
|------|------|
| 評価入力 | 対象者選択 → 勤怠データ自動表示 → 各項目を採点 → 保存 |
| 評価一覧 | 過去の評価を一覧表示・詳細確認・削除 |
| 評価基準 | 全項目・配点・ランク表を閲覧 |

### セットアップ

```bash
cd evaluation
pip install -r requirements.txt
streamlit run app.py --server.port 8503  # → http://localhost:8503
```

---

## 5. ポータル (`portal/`)

全アプリへのランチャーとなるHTMLページ。  
`portal/index.html` をブラウザで開くだけで使えます。

- 各アプリへのリンクボタン
- システム全体の最終目標（施工コストの最適化）の説明
- データベース統合構造の図解
- 各アプリの起動手順

---

## セットアップと起動

### 必要環境

- **Python 3.11 以上** — https://www.python.org/downloads/
  - インストール時に「**Add Python to PATH**」に必ずチェック
- **Git** — https://git-scm.com/downloads（自動アップデートに必要）

### 初回セットアップ

**Windows（PowerShell）:**
```powershell
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
setup.bat
```

**Mac / Linux:**
```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
chmod +x setup.sh start_all.sh
./setup.sh
```

セットアップスクリプトが以下を自動で行います:
1. Python 仮想環境（`.venv`）の作成
2. 全アプリの依存パッケージを一括インストール
3. 各アプリのデータベースを初期化

### アプリの起動

**Windows:** `start.bat` をダブルクリック  
**Mac / Linux:** `./start_all.sh`

### 自動アップデート

起動スクリプト（`start.bat` / `start_all.sh`）は起動のたびに以下を自動で行います:

1. GitHub から最新版があるか確認（`git fetch`）
2. 更新があれば自動ダウンロード（`git pull`）
3. 新しい依存パッケージがあれば自動インストール
4. DBスキーマの更新（既存データは維持）
5. 全アプリを起動してポータルページを表示

> ローカルで `.env` 等を変更していても `git stash` で退避してから更新するため、設定は保持されます。

---

## ディレクトリ構成

```
KEM_DDENKI/
├── bid_manager/        # 入札案件管理（Streamlit, port 8501）
├── material_manager/   # 材料管理（Flask, port 5000）
├── sagyo-nippou/    # 作業日報（Streamlit, port 8502）
├── evaluation/         # 人事評価（Streamlit, port 8503）
├── portal/             # ポータルページ（静的HTML）
├── docs/               # ドキュメント
│   ├── spec.md         #   システム仕様書
│   ├── geps_setup.md   #   GEPSメール連携セットアップ手順
│   └── setup_guide.md  #   ローカルPCセットアップガイド
├── setup.bat           # 初回セットアップ（Windows）
├── setup.sh            # 初回セットアップ（Mac/Linux）
├── start.bat           # 起動+自動アップデート（Windows）
└── start_all.sh        # 起動+自動アップデート（Mac/Linux）
```

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/process.md](docs/process.md) | 運用手順書（起動・停止・LAN共有・メンテナンスPC設定） |
| [docs/setup_guide.md](docs/setup_guide.md) | ローカルPCセットアップガイド（初回〜毎日の起動まで） |
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様・AI活用計画） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ手順 |
| [bid_manager/README.md](bid_manager/README.md) | 入札案件管理の詳細ドキュメント |
| [material_manager/README.md](material_manager/README.md) | 材料管理の詳細ドキュメント |
| [sagyo-nippou/README.md](sagyo-nippou/README.md) | 作業日報の詳細ドキュメント |

---

## トラブルシューティング

| 症状 | 対処 |
|------|------|
| `python` が見つからない | `py` を使う。それもダメなら Python を再インストール（PATH にチェック） |
| `pip install` でエラー | `py -m pip install -r requirements.txt` を試す |
| `streamlit` が見つからない | `py -m streamlit run app.py` を使う |
| アプリが開かない | 各ポートの URL をブラウザで直接開く |
| GEPS メールが取り込めない | `.env` の Gmail 情報を確認。`python email_importer.py --dry-run` でテスト |

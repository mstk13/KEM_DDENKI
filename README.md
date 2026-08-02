# KEM_DDENKI — ケンモチ電機 施工コスト最適化システム

電気工事の業務フローを一気通貫でカバーする社内Webアプリ群です。

---

## アクセスURL 早見表

### 社内ネットワーク（LAN）

| 環境 | URL | 対象 |
|------|-----|------|
| **本番** | [http://192.168.0.35:8080/](http://192.168.0.35:8080/) | 全社員 |
| **開発** | [http://192.168.0.35:8081/](http://192.168.0.35:8081/) | 開発者のみ |

### 社外ネットワーク（Tailscale VPN）

| 環境 | URL | 対象 |
|------|-----|------|
| **本番** | [http://100.120.92.15:8080/](http://100.120.92.15:8080/) | 全社員 |
| **開発** | [http://100.120.92.15:8081/](http://100.120.92.15:8081/) | 開発者のみ |

> Tailscale 未導入の端末からは社外アクセスできません。セットアップ手順は [docs/tailscale_setup.md](docs/tailscale_setup.md) を参照。

---

# スマホからのアクセス（iPhone / Android）

ブラウザで下記URLを開くだけで利用できます。インストール不要です。

**本番:** [http://192.168.0.35:8080/](http://192.168.0.35:8080/)（社内Wi-Fi接続時）

### アプリ一覧

| アプリ | URL | 概要 |
|--------|-----|------|
| ポータル | [http://192.168.0.35:8080/](http://192.168.0.35:8080/) | 全アプリへのランチャー |
| 入札案件管理 | [http://192.168.0.35:8080/bid/](http://192.168.0.35:8080/bid/) | 案件収集・進捗管理・費用分析 |
| 材料管理 | [http://192.168.0.35:8080/material/](http://192.168.0.35:8080/material/) | 見積もり vs 発注の消化率追跡 |
| 作業日報 | [http://192.168.0.35:8080/nippou/](http://192.168.0.35:8080/nippou/) | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | [http://192.168.0.35:8080/eval/](http://192.168.0.35:8080/eval/) | アンケート方式の評価入力 |
| 人事評価（管理） | [http://192.168.0.35:8080/eval-admin/](http://192.168.0.35:8080/eval-admin/) | 結果閲覧・自己vs他己比較・PDF出力 |
| 人材管理 | [http://192.168.0.35:8080/jinzai/](http://192.168.0.35:8080/jinzai/) | 社員情報の登録・編集・Excel出力 |
| 工期管理 | [http://192.168.0.35:8080/kouki/](http://192.168.0.35:8080/kouki/) | ガントチャート・工程進捗 |

### ホーム画面にアイコンを追加する

#### iPhone（Safari）

1. Safari で [http://192.168.0.35:8080/](http://192.168.0.35:8080/) を開く
2. 画面下の共有ボタン（□↑）をタップ
3. 「ホーム画面に追加」をタップ
4. 名前を確認して「追加」

#### Android（Chrome）

1. Chrome で [http://192.168.0.35:8080/](http://192.168.0.35:8080/) を開く
2. メニュー（⋮）→「ホーム画面に追加」または「アプリをインストール」
3. 「追加」をタップ

> ホーム画面に「ケンモチ電機」アイコンが追加され、タップするだけでポータルが開きます。

---

# PCからのアクセス（Windows / Mac）

ブラウザで下記URLを開くだけで利用できます。インストール不要です。

**本番:** [http://192.168.0.35:8080/](http://192.168.0.35:8080/)

### アプリ一覧

スマホと同じURL・同じアプリにアクセスできます。上の[アプリ一覧](#アプリ一覧)を参照してください。

### デスクトップにアイコンを作る

#### 方法1: セットアップスクリプトを使う（Windows）

1. サーバーPCまたはGitHubから `setup_client_docker.bat` を取得
2. ダブルクリックして実行
3. サーバーPCのIPアドレスとポートを入力（例: `192.168.0.35:8080`）
4. デスクトップに「ケンモチ電機」ショートカットが作成される

#### 方法2: ブラウザからアプリとしてインストール（Windows / Mac 共通）

1. ブラウザで [http://192.168.0.35:8080/](http://192.168.0.35:8080/) を開く
2. **Chrome** の場合: アドレスバー右の「インストール」アイコンをクリック
3. **Edge** の場合: メニュー（…）→「アプリ」→「このサイトをアプリとしてインストール」
4. デスクトップに「ケンモチ電機」アイコンが作成される

> インストールしたアプリは通常のアプリと同じようにタスクバーやスタートメニューに表示されます。

---

# 開発者向け

GitHub: [mstk13/KEM_DDENKI](https://github.com/mstk13/KEM_DDENKI)

**[開発ステータス（アプリごとの進捗・課題）](docs/status.md)**

---

## 開発環境URL

開発環境は **`developer` ブランチ** のコードが動作しています。

| アプリ | URL | 概要 |
|--------|-----|------|
| ポータル | [http://192.168.0.35:8081/](http://192.168.0.35:8081/) | 全アプリへのランチャー（開発用） |
| 開発管理 | [http://192.168.0.35:8081/dev/](http://192.168.0.35:8081/dev/) | 開発タスク・進捗管理 |
| 入札案件管理 | [http://192.168.0.35:8081/bid/](http://192.168.0.35:8081/bid/) | 案件収集・進捗管理・費用分析 |
| 材料管理 | [http://192.168.0.35:8081/material/](http://192.168.0.35:8081/material/) | 見積もり vs 発注の消化率追跡 |
| 作業日報 | [http://192.168.0.35:8081/nippou/](http://192.168.0.35:8081/nippou/) | 日報入力・作業員管理・月次集計 |
| 人事評価（入力） | [http://192.168.0.35:8081/eval/](http://192.168.0.35:8081/eval/) | アンケート方式の評価入力 |
| 人事評価（管理） | [http://192.168.0.35:8081/eval-admin/](http://192.168.0.35:8081/eval-admin/) | 結果閲覧・自己vs他己比較・PDF出力 |
| 人材管理 | [http://192.168.0.35:8081/jinzai/](http://192.168.0.35:8081/jinzai/) | 社員情報の登録・編集・Excel出力 |
| 工期管理 | [http://192.168.0.35:8081/kouki/](http://192.168.0.35:8081/kouki/) | ガントチャート・工程進捗 |

> 開発環境ではGitHub反映ボタンが有効です。アプリ上から developer ブランチにpushできます。

---

## ブランチ運用ルール

```
main       ← 本番環境（サーバーが毎朝自動でpull）
 ↑
developer  ← 開発用（コードの追加・修正はここで行う）
```

| ブランチ | 用途 | 誰が使う |
|---------|------|---------|
| `main` | 本番用。サーバーが毎朝自動でpullする | 管理者のみマージ |
| `developer` | 開発・テスト用。新機能やバグ修正はここで行う | 開発者全員 |

> **`main` を直接編集しない。** `main` への反映は必ず PR 経由で行う。

---

## GitHub での開発の流れ

### 1日の作業フロー

```
朝     work_start.bat     ← 他の開発者の変更を取り込む
          ↓
日中   ファイルを編集
          ↓
夕方   work_finish.bat    ← developer に反映（本番には影響なし）
          ↓
頃合いを見て release.bat  ← 本番(main)に反映
```

### 簡単な方法（.bat をダブルクリック）

| 場面 | 実行するファイル | 何をするか |
|------|-----------------|-----------|
| 作業を始めるとき | `work_start.bat` | developer を最新にする |
| 編集が終わったとき | `work_finish.bat` | developer に反映する |
| 本番に反映するとき | `release.bat` | developer → main（管理者用） |

### コマンドで行う方法

```bash
# 1. developer ブランチで作業する
git checkout developer
git pull origin developer

# 2. コードを修正・テスト

# 3. developer にpush
git add -A && git commit -m "feat(evaluation): 評価項目に自由記述欄を追加"
git push origin developer

# 4. 本番に反映したい時 → GitHub で Pull Request を作成
#    developer → main の PR を作り、確認してからマージする
```

### コミットメッセージの書き方

`種類(場所): 内容` の形式で書く。

| 例 | 使う場面 |
|----|---------|
| `feat(evaluation): 評価項目に自由記述欄を追加` | 機能追加 |
| `fix(sagyo-nippou): 日付が1日ずれる不具合を修正` | バグ修正 |
| `docs: READMEに起動手順を追記` | ドキュメント |
| `refactor: 共通処理を関数にまとめた` | 整理（動作は変えない） |
| `chore: 不要なログファイルを削除` | 雑務 |

### 注意事項

- **`developer` は消さない・作り直さない** — 他の開発者と共有する常設ブランチ
- **`git push --force` は絶対にやらない** — 相手の作業が消えます
- **作業前と作業後を必ずセットで** — push しないまま別のPCで作業すると二重作業になる
- 詳しいルールは [docs/git_workflow.md](docs/git_workflow.md) を参照

---

## サーバーセットアップ

### Step 1: Git + Docker をインストール

- **Git**: [https://gitforwindows.org/](https://gitforwindows.org/)（Windows）/ `sudo apt install git`（Linux）
- **Docker**: [https://www.docker.com/products/docker-desktop/](https://www.docker.com/products/docker-desktop/)（Windows / Mac）/ セットアップスクリプトが自動インストール（Linux）

### Step 2: クローン & セットアップ

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
./docker/setup_server.sh      # Linux / Mac / WSL
# docker\setup_server.bat     # Windows
```

初回は数分かかります。完了後 [http://localhost/](http://localhost/) でポータルが開けば成功です。

### Step 3: 他のPCからのアクセス確認

```bash
ipconfig        # Windows
hostname -I     # Linux
```

他のPCのブラウザで `http://サーバーIP/` を開いて表示されればOK。

> **WSL の場合**: Windows PowerShell（管理者）でポートフォワーディングが必要:
> ```powershell
> $wslIP = (wsl hostname -I).Trim().Split(' ')[0]
> netsh interface portproxy add v4tov4 listenport=80 listenaddress=0.0.0.0 connectport=80 connectaddress=$wslIP
> New-NetFirewallRule -DisplayName "KEM_DDENKI" -Direction Inbound -LocalPort 80 -Protocol TCP -Action Allow
> ```

---

## 管理コマンド

```bash
./docker/manage.sh status              # 稼働状況
./docker/manage.sh stop                # 全アプリ停止
./docker/manage.sh start               # 全アプリ起動
./docker/manage.sh restart evaluation   # 特定アプリだけ再起動
./docker/manage.sh update              # GitHubから最新版に更新
./docker/manage.sh logs bid_manager    # ログ確認
./docker/manage.sh backup              # DBバックアップ
```

> 毎朝5時にGitHubから自動更新されます（cron）。

---

## テストデータの投入

```bash
# Docker環境で実行
docker compose exec bid_manager python /app/shared/seed_all.py

# データを全削除してから投入し直す場合
docker compose exec bid_manager python /app/shared/seed_all.py --reset
```

テストデータの従業員（10名）:

| コード | 名前 | 部署 | 役割 |
|--------|------|------|------|
| E001 | 剣持 太郎 | 役員 | 代表取締役 |
| E002 | 剣持 花子 | 役員 | 取締役 |
| E003 | 佐藤 健一 | 電気工事部 | 職長 |
| E004 | 田中 翔太 | 電気工事部 | 主任 |
| E005 | 鈴木 誠 | 電気工事部 | 社員 |
| E006 | 高橋 健太 | 電気工事部 | 社員 |
| E007 | 山田 美咲 | 総務部 | 事務主任 |
| E008 | 中村 裕子 | 総務部 | 事務社員 |
| E009 | 伊藤 大輔 | 電気工事部 | 見習い |
| E010 | 渡辺 拓也 | 電気工事部 | 見習い |

---

## Docker を使わない起動（開発・テスト用）

```bash
./setup.sh          # 初回セットアップ
./start_all.sh      # 全アプリ起動（http://localhost:8080）
```

個別起動:

| アプリ | コマンド |
|--------|---------|
| 入札案件管理 | `cd bid_manager && python database.py && streamlit run app.py --server.port 8501` |
| 材料管理 | `cd material_manager && python -c "from db import init_db; init_db()" && python app.py` |
| 作業日報 | `cd sagyo-nippou && python database.py && streamlit run app.py --server.port 8502` |
| 人事評価（入力） | `cd evaluation && streamlit run app.py --server.port 8504` |
| 人事評価（管理） | `cd evaluation && streamlit run admin_app.py --server.port 8505` |
| 営業管理 | `cd eigyo-kanri && python database.py && streamlit run app.py --server.port 8503` |
| 日報管理 | `cd nippou-kanri && python database.py && streamlit run app.py --server.port 8510` |

---

## ドキュメント

| ドキュメント | 内容 |
|-------------|------|
| [docs/setup_guide.md](docs/setup_guide.md) | セットアップ詳細・トラブルシューティング |
| [docs/DEVELOPER.md](docs/DEVELOPER.md) | 個別開発・テスト・新アプリ追加手順 |
| [docs/git_workflow.md](docs/git_workflow.md) | Git運用ルール・作業手順の詳細 |
| [docs/spec.md](docs/spec.md) | システム仕様書（DB設計・機能仕様） |
| [docs/geps_setup.md](docs/geps_setup.md) | GEPS メール連携のセットアップ |
| [docs/process.md](docs/process.md) | 業務プロセスフロー |
| [docs/tailscale_setup.md](docs/tailscale_setup.md) | 外部アクセス（Tailscale）セットアップ手順 |

---

## データの流れ

```
入札案件管理（案件収集・入札）
    ↓ 受注
材料管理（見積もり→発注→受領の追跡）
    ↓ 施工中
作業日報（作業員・時間・交通費の記録）
    ↓                ↓
人事評価（勤怠データ連携）  コスト分析・AI見積もり ← 将来
```

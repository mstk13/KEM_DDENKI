# KEM_DDENKI 運用手順書

> **セットアップ・データ共有・LAN共有の手順は [セットアップガイド（setup_guide.md）](setup_guide.md) に統一されています。**  
> このドキュメントは WSL サーバー構成での詳細な運用手順（メンテナンスPC管理・Git運用等）を記載しています。

---

## 目次

1. [全体構成](#1-全体構成)
2. [サーバーPCのセットアップ（初回のみ）](#2-サーバーpcのセットアップ初回のみ)
3. [アプリの起動方法（毎日の操作）](#3-アプリの起動方法毎日の操作)
4. [アプリの停止方法](#4-アプリの停止方法)
5. [他のPCからアクセスする方法](#5-他のpcからアクセスする方法)
6. [メンテナンス用PCのセットアップ](#6-メンテナンス用pcのセットアップ)
7. [メンテナンス作業の手順](#7-メンテナンス作業の手順)
8. [トラブルシューティング](#8-トラブルシューティング)

---

## 1. 全体構成

```
サーバーPC（1台）                    他のPC（何台でも）
┌────────────────────────┐          ┌──────────────────┐
│  WSL (Ubuntu) 上で起動   │          │  ブラウザだけでOK   │
│                        │          │  インストール不要    │
│  入札案件管理 :8501     │◄────────►│                  │
│  材料管理     :5000     │   LAN    │  http://サーバーIP  │
│  作業日報     :8502     │          │   :8501 等で接続   │
│  人事評価     :8503     │          │                  │
│                        │          └──────────────────┘
│  SQLite DB（全データ）   │
└────────────────────────┘          メンテナンスPC（任意）
                                    ┌──────────────────┐
                                    │  Git + WSL/Python  │
                                    │  コード編集・push   │
                                    └──────────────────┘
```

- サーバーPCが全アプリとデータベースを持つ
- 他のPCはブラウザでアクセスするだけ（ソフトのインストール不要）
- 全員が同じデータを共有する（入力したデータは即座にDBに保存）

### アプリ一覧

| アプリ | ポート | URL（サーバーPC） | URL（他のPC） |
|--------|--------|-------------------|--------------|
| 入札案件管理 | 8501 | http://localhost:8501 | http://192.168.0.27:8501 |
| 材料管理 | 5000 | http://localhost:5000 | http://192.168.0.27:5000 |
| 作業日報 | 8502 | http://localhost:8502 | http://192.168.0.27:8502 |
| 人事評価 | 8503 | http://localhost:8503 | http://192.168.0.27:8503 |

> IPアドレス（192.168.0.27）はネットワーク環境によって変わる場合があります。
> 確認方法は後述の[他のPCからアクセスする方法](#5-他のpcからアクセスする方法)を参照。

---

## 2. サーバーPCのセットアップ（初回のみ）

### 2-1. 必要なソフトの確認

WSL（Windows Subsystem for Linux）のターミナルを開いて以下を確認:

```bash
python3 --version    # Python 3.11以上
git --version        # Git
```

### 2-2. リポジトリのクローンと環境構築

```bash
cd ~
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
python3 -m venv .venv
source .venv/bin/activate
pip install -r bid_manager/requirements.txt \
            -r material_manager/requirements.txt \
            -r sagyo-nippou/requirements.txt \
            -r evaluation/requirements.txt
```

### 2-3. データベースの初期化

```bash
cd ~/KEM_DDENKI

# 入札案件管理
cd bid_manager && mkdir -p data && python3 database.py && cd ..

# 材料管理
cd material_manager && python3 -c "from db import init_db; init_db()" && cd ..

# 作業日報
cd sagyo-nippou && python3 database.py && cd ..
```

（人事評価のDBはアプリ初回起動時に自動作成されます）

### 2-4. Streamlit設定（LAN公開用）

```bash
for dir in bid_manager sagyo-nippou evaluation; do
  mkdir -p ~/KEM_DDENKI/$dir/.streamlit
  cat > ~/KEM_DDENKI/$dir/.streamlit/config.toml << 'EOF'
[server]
headless = true
address = "0.0.0.0"
enableCORS = false
enableXsrfProtection = false
EOF
done
```

### 2-5. Windowsファイアウォールの設定

Windows側で以下の手順を実行（1回だけ）:

1. スタートメニューで「**Windows セキュリティ**」を検索して開く
2. 「**ファイアウォールとネットワーク保護**」をクリック
3. 「**詳細設定**」をクリック（管理者権限の確認 →「はい」）
4. 左側の「**受信の規則**」をクリック
5. 右側の「**新しい規則...**」をクリック
6. 設定内容:
   - 規則の種類: **ポート** → 次へ
   - プロトコル: **TCP**、特定のローカルポート: **5000,8501,8502,8503** → 次へ
   - 操作: **接続を許可する** → 次へ
   - プロファイル: **ドメイン、プライベート、パブリック** 全てチェック → 次へ
   - 名前: **KEM_DDENKI_Apps** → 完了

---

## 3. アプリの起動方法（毎日の操作）

### 手順

1. WSLのターミナルを開く（スタートメニューで「Ubuntu」を検索）
2. 以下のコマンドを実行:

```bash
cd ~/KEM_DDENKI
source .venv/bin/activate

# 材料管理
cd material_manager
python3 -c "from db import init_db; init_db()" 2>/dev/null
python3 -c "from app import app; app.run(debug=False, host='0.0.0.0', port=5000, use_reloader=False)" &
cd ..

# 入札案件管理
cd bid_manager && streamlit run app.py --server.port 8501 &>/dev/null & cd ..

# 作業日報
cd sagyo-nippou && streamlit run app.py --server.port 8502 &>/dev/null & cd ..

# 人事評価
cd evaluation && streamlit run app.py --server.port 8503 &>/dev/null & cd ..

echo "=== 起動完了 ==="
echo "http://localhost:5000  材料管理"
echo "http://localhost:8501  入札案件管理"
echo "http://localhost:8502  作業日報"
echo "http://localhost:8503  人事評価"
```

3. ブラウザで http://localhost:8501 等を開いて確認

### ワンコマンドで起動する場合

上記を毎回打つのが面倒な場合、以下の起動スクリプトを使えます:

```bash
cd ~/KEM_DDENKI && bash start_wsl.sh
```

> `start_wsl.sh` はリポジトリに含まれています。

---

## 4. アプリの停止方法

### 方法1: WSLターミナルで停止

```bash
kill $(lsof -ti:5000) $(lsof -ti:8501) $(lsof -ti:8502) $(lsof -ti:8503) 2>/dev/null
echo "全アプリ停止しました"
```

### 方法2: WSLターミナルを閉じる

ターミナルウィンドウを閉じれば全アプリが停止します。

---

## 5. 他のPCからアクセスする方法

### 条件

- サーバーPCと同じネットワーク（Wi-Fi or 有線LAN）に接続していること
- ソフトのインストールは不要（ブラウザだけでOK）

### 手順

1. サーバーPCでアプリを起動する（上記の手順3を実行済み）
2. 他のPCのブラウザで以下のURLにアクセス:

| アプリ | URL |
|--------|-----|
| 入札案件管理 | http://192.168.0.27:8501 |
| 材料管理 | http://192.168.0.27:5000 |
| 作業日報 | http://192.168.0.27:8502 |
| 人事評価 | http://192.168.0.27:8503 |

### サーバーPCのIPアドレスが変わった場合

WSLターミナルで以下を実行して確認:

```bash
cmd.exe /c "ipconfig" 2>&1 | iconv -f SHIFT_JIS -t UTF-8 | grep "IPv4"
```

一番上に表示される `192.168.x.x` がサーバーのIPアドレスです。

### アクセスできない場合のチェックリスト

- [ ] サーバーPCでアプリが起動しているか
- [ ] 同じネットワークに接続しているか
- [ ] ファイアウォール設定が完了しているか（手順2-5）
- [ ] IPアドレスが正しいか

---

## 6. メンテナンス用PCのセットアップ

メンテナンスPCでは、コードの修正やGitHubへのプッシュができるようになります。
アプリのサーバーはサーバーPC1台で動かしたまま、開発作業だけメンテナンスPCからも行えます。

### 6-1. 必要なソフトのインストール

#### Git

https://git-scm.com/downloads からダウンロードしてインストール。
設定はすべてデフォルトでOK。

#### Python 3.12

https://www.python.org/downloads/ からダウンロード。
インストール時に「**Add Python to PATH**」に必ずチェック。

#### テキストエディタ（推奨）

- VS Code: https://code.visualstudio.com/

### 6-2. リポジトリのクローン

PowerShellを開いて:

```powershell
cd ~
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
```

> リポジトリがprivateの場合、GitHubの認証が必要です。
> GitHub Personal Access Token を発行してください:
> GitHub → Settings → Developer settings → Personal access tokens → Generate new token

### 6-3. Python環境の構築（メンテナンスPCでもテストしたい場合）

WSLが使える場合（推奨）:

```bash
cd ~/KEM_DDENKI
python3 -m venv .venv
source .venv/bin/activate
pip install -r bid_manager/requirements.txt \
            -r material_manager/requirements.txt \
            -r sagyo-nippou/requirements.txt \
            -r evaluation/requirements.txt
```

---

## 7. メンテナンス作業の手順

### コードを修正してGitHubに反映する

```bash
cd ~/KEM_DDENKI

# 1. 最新のコードを取得
git pull origin main

# 2. ファイルを編集（エディタで修正）

# 3. 変更を確認
git status
git diff

# 4. コミットしてプッシュ
git add 修正したファイル名
git commit -m "修正内容の説明"
git push origin main
```

### サーバーPCに変更を反映する

サーバーPCのWSLターミナルで:

```bash
cd ~/KEM_DDENKI
git pull origin main
```

アプリの再起動が必要な場合:

```bash
# 停止
kill $(lsof -ti:5000) $(lsof -ti:8501) $(lsof -ti:8502) $(lsof -ti:8503) 2>/dev/null

# 起動（手順3を再実行）
bash start_wsl.sh
```

### 人事評価の評価項目を変更する場合

ブラウザ上で編集可能です:

1. http://localhost:8503 を開く
2. サイドバーで「評価基準の編集」を選択
3. 項目を変更・追加・削除して「変更を保存」
4. ページ下部の「GitHubに反映する」ボタンをクリック

---

## 8. トラブルシューティング

| 症状 | 原因 | 対処 |
|------|------|------|
| アプリが表示されない | アプリが起動していない | 手順3でアプリを起動する |
| 他のPCからアクセスできない | ファイアウォール未設定 | 手順2-5を実施する |
| 他のPCからアクセスできない | IPアドレスが違う | 手順5でIPアドレスを再確認 |
| ポートが使用中と出る | 前回のプロセスが残っている | 手順4で停止してから再起動 |
| `git push` が拒否される | リポジトリがprivate | GitHubトークンで認証する |
| pandas DLLエラー（Windows） | 会社のセキュリティポリシー | WSL上でアプリを動かす |
| DB初期化エラー | dataフォルダがない | `mkdir -p data` を実行 |

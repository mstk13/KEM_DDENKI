# ローカルPCセットアップガイド

ケンモチ電機 施工コスト最適化システムを、お使いのPCで動かすための手順書です。

---

## 必要なソフト（2つだけ）

| ソフト | ダウンロード先 | 注意点 |
|--------|---------------|--------|
| **Python 3.11 以上** | https://www.python.org/downloads/ | インストール時に **「Add Python to PATH」に必ずチェック** を入れる |
| **Git** | https://git-scm.com/downloads | インストーラの設定はすべてデフォルトでOK |

> どちらも無料です。すでにインストール済みなら飛ばしてください。

### インストールできたか確認する方法

PowerShell（またはターミナル）を開いて以下を入力:

```
python --version
git --version
```

バージョン番号が表示されればOKです。  
`python` が見つからない場合は `py --version` も試してください。

---

## 初回セットアップ（1回だけ）

### Windows の場合

1. **PowerShell を開く**（スタートメニューで「PowerShell」と検索）
2. 以下のコマンドを **1行ずつ** コピーして貼り付け、Enter:

```powershell
git clone https://github.com/mstk13/KEM_DDENKI.git
```
```powershell
cd KEM_DDENKI
```
```powershell
.\setup.bat
```

3. 「セットアップ完了！」と表示されたら完了です

### Mac / Linux の場合

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
chmod +x setup.sh start_all.sh
./setup.sh
```

### セットアップが自動でやること

- Python 仮想環境の作成（`.venv` フォルダ）
- 全アプリの必要パッケージをまとめてインストール
- 各アプリのデータベースを初期化

> この手順は **各PCで1回だけ** 行えばOKです。

---

## アプリの起動方法（毎日の操作）

### Windows

`KEM_DDENKI` フォルダにある **`start.bat` をダブルクリック** するだけ！

または PowerShell で:
```powershell
cd C:\Users\ユーザー名\KEM_DDENKI
.\start.bat
```

### Mac / Linux

```bash
cd ~/KEM_DDENKI
./start_all.sh
```

### 起動すると…

1. 自動で最新版に更新されます（GitHub から新しいコードがあれば自動ダウンロード）
2. 3つのアプリがバックグラウンドで起動します
3. ポータルページ（全アプリへのリンク画面）がブラウザで自動的に開きます

| アプリ | URL | 説明 |
|--------|-----|------|
| ポータル | ブラウザで自動表示 | 全アプリへのリンク画面 |
| 入札案件管理 | http://localhost:8501 | 入札案件の収集・管理・分析 |
| 材料管理 | http://localhost:5000 | 見積もり vs 発注の比較管理 |
| 作業日報 | http://localhost:8502 | 作業日報の入力・集計 |

### アプリの停止方法

- **Windows**: 黒いウィンドウ（コマンドプロンプト）を閉じる、またはウィンドウ内で `Ctrl+C`
- **Mac / Linux**: ターミナルで `Ctrl+C`

---

## 自動アップデートについて

**何もしなくてOKです。** 起動するたびに自動で以下が行われます:

1. GitHub に新しいバージョンがあるか確認
2. あれば自動でダウンロード・更新
3. 新しいパッケージがあれば自動インストール
4. データベースの構造変更があれば自動適用（既存データはそのまま）

> 管理者（開発者）が GitHub に変更をプッシュすれば、各PCは次回起動時に自動で最新版になります。

---

## よくある質問

### Q. `python` が見つからないと言われる

**A.** `py` に置き換えて試してください。それでもダメなら Python を再インストールし、「Add Python to PATH」にチェックを入れてください。

### Q. `pip install` でエラーが出る

**A.** 以下を試してください:
```powershell
py -m pip install -r bid_manager\requirements.txt
```

### Q. アプリのページが開かない

**A.** ブラウザで以下のURLを直接入力してください:
- http://localhost:8501（入札案件管理）
- http://localhost:5000（材料管理）
- http://localhost:8502（作業日報）

### Q. 2台目のPCにセットアップしたい

**A.** 「初回セットアップ」の手順をそのPCで実行するだけです。データはPC間で共有されません（各PCにローカル保存）。

### Q. データを別のPCに移したい

**A.** 以下のファイルをコピーしてください:
- `bid_manager/data/` フォルダ内のファイル
- `material_manager/construction.db`
- `作業日報/` 内の `.db` ファイル

### Q. インターネットに繋がっていないときは？

**A.** 自動アップデートがスキップされるだけで、アプリは問題なく起動・使用できます。

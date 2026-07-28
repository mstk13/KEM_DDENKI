# Git 運用ルール（作業手順）

このリポジトリの編集手順です。ブランチの役割は README「ブランチ運用ルール」に従います。

```
main    ← 本番環境（サーバーが毎朝自動でpull）   管理者のみマージ
 ↑
develop ← 開発用（コードの追加・修正はここ）      開発者全員
```

**編集は必ず `develop` で行います。`main` を直接編集しないでください。**

---

## かんたんな方法（.bat をダブルクリック）

| 場面 | 実行するファイル | 何をするか |
|------|-----------------|-----------|
| 作業を始めるとき | `work_start.bat` | develop を最新にする |
| 編集が終わったとき | `work_finish.bat` | develop に反映する |
| 本番に反映するとき | `release.bat` | develop → main（管理者用） |

`work_finish.bat` は develop までです。**本番には反映されません。**
本番に出すときだけ `release.bat` を実行します。

---

## 1日の流れ

```
🌅 朝    work_start.bat     ← 他の開発者の変更と本番の修正を取り込む
              ↓
💻 日中   ファイルを編集
              ↓
🌇 夕方   work_finish.bat    ← develop に反映（ここまでは本番に影響なし）
              ↓
🚀 頃合いを見て release.bat  ← 本番(main)に反映
```

---

## コマンドで行う方法

### 1. 作業を始めるとき

```powershell
cd C:\Users\Kenmo\KEM_DDENKI
git fetch origin --prune
git switch develop
git merge origin/develop     # 他の開発者の変更を取り込む
git merge origin/main        # 本番側の修正を取り込む
```

### 2. 編集してコミット

```powershell
git add -A
git commit -m "feat(evaluation): 評価項目に自由記述欄を追加"
```

### 3. develop に反映

```powershell
git fetch origin
git merge origin/develop     # 送る前に相手の変更を取り込む
git push origin develop
```

### 4. 本番(main)に反映（管理者のみ）

```powershell
gh pr create --base main --head develop --fill
gh pr merge --merge
git merge origin/main        # develop を main に追いつかせる
git push origin develop
```

---

## 大事な注意

### `develop` は消さない・作り直さない

`develop` は**他の開発者と共有する常設ブランチ**です。

```powershell
git switch -C develop ...    # ❌ 絶対にやらない（相手の作業が消えます）
git push --force             # ❌ 絶対にやらない
```

以前の `deploy-update` は使い捨てブランチでしたが、**`develop` は扱いが逆**です。取り込む（merge）ことはあっても、作り直すことはありません。

### 作業前と作業後を必ずセットで

- **作業前**: `work_start.bat` で相手の変更を取り込む
- **作業後**: `work_finish.bat` でその日のうちに push

push しないまま別のPCで作業すると、同じ機能を二重に作ることになります。

### `main` を直接編集しない

`main` に直接コミットすると `develop` との間に差ができ、そこから分岐が始まります。`main` への反映は必ず `release.bat`（＝ develop → main のPR）経由で行ってください。

---

## コミットメッセージの書き方

`種類(場所): 内容` の形にすると後から探しやすくなります。

| 例 | 使う場面 |
|----|---------|
| `feat(evaluation): 評価項目に自由記述欄を追加` | 機能追加 |
| `fix(sagyo-nippou): 日付が1日ずれる不具合を修正` | バグ修正 |
| `docs: READMEに起動手順を追記` | ドキュメント |
| `refactor: 共通処理を関数にまとめた` | 整理（動作は変えない） |
| `chore: 不要なログファイルを削除` | 雑務 |

---

## 迷ったときの確認コマンド

```powershell
git branch --show-current                    # 今どのブランチにいる？
git status                                   # 未コミットの変更は？
git log --oneline origin/develop..HEAD       # developに未反映の自分のコミット
git log --oneline origin/main..origin/develop # 本番に未反映の変更
```

**push する前に1行目を確認する癖をつけてください。**

---

## 困ったとき

| 症状 | 対処 |
|---|---|
| `[エラー] 衝突しました` | 同じ場所を2人が変更しています。画面を見せて相談してください |
| 警告が出て進めない | 作業が消えるのを防ぐ門番です。無視せず読んでください |
| 何をしたか忘れた | 上の確認コマンドを実行してください |
| 間違えて消したかも | **push前なら復元できます。** すぐ相談してください |

`.bat` は途中で止まっても壊れません。迷ったら閉じて相談してください。

---

## 過去の経緯（2026-07）

7/23に一時的な作業用として作った `deploy-update` を削除し忘れ、7/27にそのブランチ上で作業を再開したため、main と完全に分岐しました（19ファイルでコンフリクト）。同じ機能が両方に別々のコミットとして存在する状態になり、7/28に整理しました。

**原因は「合流し忘れた古いブランチの上で作業したこと」です。** `work_start.bat` が毎回 `origin/develop` と `origin/main` を取り込むのは、これを防ぐためです。

# 引き継ぎ: 自動デプロイ停止の対応と残タスク（2026-08-10）

このドキュメントは、2026-08-10 に発生した自動デプロイ停止の対応記録と、
**まだ終わっていない作業**の引き継ぎです。次に作業する人／AI はここから読んでください。

作業環境はサーバーPC（ホスト名 `desktop-rmsk0vg`）です。

---

## 1. 結論だけ先に（残タスクは2つ）

| # | 残タスク | 誰が | 状態 |
|---|---|---|---|
| 1 | PR を `kenmochi-k` で作り直して `@mstk13` にレビュー依頼 | 作業者／AI | **未完** — GitHub 認証の問題で止まっている |
| 2 | `main` へのマージ | PM (@mstk13) | 未着手 — 1 の完了後 |

障害そのものは**復旧済み**で、自動デプロイは正常稼働しています。
残っているのは「恒久対策を本番に効かせる」ための手続きだけです。

---

## 2. 何が起きたか

2026-08-10 11:08 頃、自動デプロイが停止し、**38分間デプロイが止まりました**。

ログにはこれだけが2分おきに並びます:

```
[2026-08-10 11:10:02] 前回の実行が進行中のためスキップします
[2026-08-10 11:12:02] 前回の実行が進行中のためスキップします
...
```

### 原因

GitHub のトークンが失効した状態で `git fetch` が実行され、**資格情報の入力待ちで
ハング**しました。タスクスケジューラからの無人実行なので誰も応答できません。

`autodeploy.sh` は多重起動を防ぐためロック（`~/kem-ops/autodeploy.lock`）を取りますが、
ハングしたプロセスがそれを握ったままになりました。ロックの失効判定は**1時間**のため、
その間のすべての実行が空振りしました。

### なぜ復旧したか

作業者が `gh auth login` で再認証したことでハングが解け、11:58 に正常復帰しました。
**根本原因が直ったわけではなく、トークンが切れれば必ず再発します。**

---

## 3. 実施済みの対応

### 3-1. 恒久対策（コミット `5bd12aa`、`developer` に反映済み）

`tools/autodeploy/autodeploy.sh` に以下を追加しました。

- `GIT_TERMINAL_PROMPT` / `GCM_INTERACTIVE` / `GIT_ASKPASS` / `SSH_ASKPASS` で
  対話を封じ、認証切れの際は待たずに失敗させる
- `git fetch` に `timeout` を被せる
  （既定120秒、`KEM_AUTODEPLOY_FETCH_TIMEOUT` で変更可）。
  認証以外（DNS・プロキシ・GitHub 側の不調）でも `fetch` は無言で滞留しうるため
- 時間切れ（終了コード124）は原因が分かるよう専用の WARN を出す

いずれの場合もロックは EXIT トラップで解放され、次回の実行に引き継がれます。

**検証済み:** 非到達アドレス（`https://10.255.255.1/hang.git`）を remote にした
使い捨てリポジトリで、`KEM_AUTODEPLOY_FETCH_TIMEOUT=5` を指定して実行し、
「5秒で時間切れ → 専用 WARN 出力 → ロック解放 → 終了コード1」を確認しました。
本番のロックと設定には触れていません。

### 3-2. 自己同期機構のブートストラップ（重要）

調査中に、**自己同期の仕組みが一度も起動していなかった**ことが判明しました。

タスクスケジューラが実行するのは `~/kem-ops/autodeploy.sh`（**リポジトリ外の常設コピー**）です。
コミット `2d39fde`「本体をリポジトリ外に常設し、リポジトリ側から自動同期する」で
「実行のたびにリポジトリ版を常設コピーへ同期する」処理が追加されましたが、
**常設コピー自体がそのコミット以前の版のまま**でした。

同期コードを持たない版が動き続けていたため、自分自身を更新できない
（鶏と卵の）状態です。差分は同期ブロックのみで他は完全一致でした。
つまり `2d39fde` 以降、**リポジトリ側のスクリプト修正は一つも本番に届いていません**でした。

対応として、`projects\KEM_DDENKI`（prod）のリポジトリ版を常設コピーへ手動でコピーし、
同期機構を起動させました。

- 旧版の退避先: `~/kem-ops/autodeploy.sh.bak-20260810`
- 以後はリポジトリ側の修正が自動で常設コピーへ反映されます

### 3-3. ⚠️ 同期元は `main` — だから `main` マージが必要

常設コピーの同期元は、設定ファイル `~/kem-ops/autodeploy.conf` の**最終行の環境**です。

```
dev|/c/Users/kazushi kenmochi/projects/KEM_DDENKI_dev|developer|http://127.0.0.1:8001/login/|
prod|/c/Users/kazushi kenmochi/projects/KEM_DDENKI|main|http://127.0.0.1:8000/login/|backup
```

最終行は `prod`＝**`main` ブランチ**です。スクリプト末尾のループが最後に見つけた
リポジトリを同期元にするためです。

したがって **3-1 の恒久対策は `main` にマージされるまで実際には動きません。**
`developer` に入れただけでは、次回実行時に `main` 版で上書きされます。

---

## 4. 残タスク 1: PR を作り直してレビュー依頼（ここで止まっています）

### 何が問題か

`developer` → `main` の PR **#15** は作成済みですが、
**PM への通知が成立していません。**

<https://github.com/mstk13/KEM_DDENKI/pull/15>

このPCの `gh` は現在 **`mstk13`** でログインしています。これは**PM 本人のアカウント**で、
リポジトリのオーナー（admin 権限あり）です。そのため PR の作成者が PM 自身になり:

| 操作 | 結果 |
|---|---|
| `gh pr edit 15 --add-reviewer mstk13` | **無効**。GitHub は PR 作成者をレビュアーに指定できない。`gh` は成功したように見えて URL を返すが、`reviewRequests` は空のまま |
| `gh pr edit 15 --add-assignee mstk13` | 設定はされるが、自分で自分に割り当てた形なので**通知は飛ばない** |
| コメントで `@mstk13` | 自分自身へのメンションのため**通知されない** |

GitHub 上で PM に通知を飛ばすには、**PR の作成者が PM 以外である必要があります。**

コラボレーターは3名です:

| アカウント | 権限 |
|---|---|
| `mstk13` | admin, maintain, pull, push, triage（＝PM・オーナー） |
| `kenmochi-k` | pull, push, triage |
| `HirokiKenmochi` | pull, push, triage |

### 手順

`kenmochi-k` は `gh` に登録済みですが**トークンが失効**しています
（`gh auth status` で `The token in default is invalid.`）。再認証が必要です。

```bash
# 1. kenmochi-k で再ログイン（対話操作。ブラウザは mstk13 のセッションが残っているため
#    シークレットウィンドウで kenmochi-k としてサインインしてからコードを承認すること）
gh auth login -h github.com

# 2. kenmochi-k を有効化
gh auth switch -h github.com -u kenmochi-k
gh api user --jq .login          # kenmochi-k と出ることを確認

# 3. 作成者が PM 本人だった #15 をクローズ
gh pr close 15 --repo mstk13/KEM_DDENKI \
  --comment "作成者が PM 本人のアカウントとなり、レビュー依頼の通知が飛ばないため作り直します。"

# 4. 同じ内容で PR を再作成（本文は下の「PR 本文の骨子」を使う）
gh pr create --repo mstk13/KEM_DDENKI --base main --head developer \
  --title "fix(autodeploy): fetch のハングでデプロイが停止する問題の対策 + UI修正" \
  --body-file <本文ファイル>

# 5. PM にレビュー依頼
gh pr edit <新しい番号> --repo mstk13/KEM_DDENKI --add-reviewer mstk13

# 6. 通知が成立したことを必ず確認（ここが空なら失敗している）
gh pr view <新しい番号> --repo mstk13/KEM_DDENKI --json reviewRequests
```

> **確認を省略しないこと。** `gh pr edit --add-reviewer` は失敗しても
> エラーを出さず PR の URL を返します。`reviewRequests` に `mstk13` が
> 入っているかどうかだけが、通知が飛んだかの判断材料です。

### 代替案

`kenmochi-k` にログインできない場合:

- **`@HirokiKenmochi` にレビュー依頼する** — 作成者ではないので通知は届きます。
  ただし PM 本人への通知にはなりません
- **Slack・メール・口頭で PM に直接連絡する** — PR #15 はそのまま使えます。
  この場合 GitHub 上に承認履歴は残りません

### PR 本文の骨子

- 自動デプロイの障害対策（本セクション 2・3 の内容）
- **`main` にマージされるまで対策は動かない**旨を明記する
- UI 修正が同時に本番へ反映されることを明記する
- マージ後の確認項目: 自動デプロイのログに
  「自動デプロイ本体を更新しました」が出ること

---

## 5. 残タスク 2: `main` へのマージ（PM の作業）

マージされて初めて恒久対策が動き出します。

マージ後、次の自動デプロイ実行で常設コピーが同期され、ログに次の行が出ます:

```
自動デプロイ本体を更新しました（次回実行から反映）
```

この行を確認できたら、一連の対応は完了です。

```bash
# 確認コマンド
tail -20 ~/kem-ops/autodeploy.log
grep -c "GIT_TERMINAL_PROMPT" ~/kem-ops/autodeploy.sh   # 1 以上なら反映済み
```

---

## 6. 作業時の注意

### 作業クローンには未コミットの変更がある

`projects\KEM_DDENKI_work` の `developer` ブランチに、**工程比較機能の作業中の変更**が
未コミットで残っています（6ファイル +319行、`saas/templates/schedules/compare.html` は未追跡）。

**`git reset --hard` や `git checkout .` で消さないこと。**
ブランチ操作が必要なときは `git stash push -u` で退避してください。

### 編集は必ず work クローンで

| フォルダ | 用途 | ブランチ |
|---|---|---|
| `projects\KEM_DDENKI` | 本番（GitHub の鏡） | `main` |
| `projects\KEM_DDENKI_dev` | 開発（GitHub の鏡） | `developer` |
| `projects\KEM_DDENKI_work` | **編集用** | 作業ブランチ |

前2つは自動デプロイが2分おきに `git reset --hard` + `git clean` するため、
そこで編集した内容は消えます。

### `developer` は更新が活発

2026-08-10 の午前中だけで10コミット以上入っています。push 前に必ず
`git fetch` してリベースしてください。作業ツリーが汚れている状態で
リベースできない場合は、`git worktree add` で別ディレクトリを作り、
そこで cherry-pick して push すると作業中の変更に一切触れずに済みます。

### 認証が切れたときの復旧

```bash
gh auth status                   # どのアカウントが有効か、トークンが生きているか
gh auth login -h github.com      # 対話。デバイスコードをブラウザで承認
gh auth setup-git                # ★ ログイン完了後に実行すること（先に走らせても効かない）
```

認証が切れていても**自動デプロイは別経路で動き続けます**。復旧できない場合は、
`projects\KEM_DDENKI_dev`（`origin/developer` の鏡）からローカル fetch すれば
ネットワークなしで最新化できます。

---

## 7. 関連ドキュメント

- `docs/server_operations.md` — サーバー構成・運用
- `docs/developer_guide.md` — 開発の進め方
- `docs/git_workflow.md` — ブランチ運用
- `docs/branch_protection_setup.md` — `main` のブランチ保護設定手順（要 admin）

## 8. 関連コミット

| コミット | 内容 |
|---|---|
| `5bd12aa` | 今回の恒久対策（`developer`） |
| `2d39fde` | 自己同期の追加。**この時点で常設コピーの手動更新が必要だったが行われていなかった** |
| `b9c2814` | 自動デプロイの初期実装 |

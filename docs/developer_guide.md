<p align="center">
  <img src="../saas/static/img/icon-192.png" width="88" alt="ケンモチ電機 業務管理システム">
</p>

# 開発者ガイド

**編集してから本番に出るまで、何をどの順でやるか**を1枚にまとめたページです。
サーバーPCを触る必要はありません。手元のPCと GitHub の操作だけで完結します。

---

## 1. 環境は3つある

| 環境 | URL | 中身 | 誰が見る |
|------|-----|------|---------|
| **手元** | http://localhost:8000/ | 自分のPCで動かすDocker | 自分だけ |
| **開発環境** | https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/ | `developer` ブランチが**自動で**反映される | 開発者・PM |
| **本番** | https://desktop-rmsk0vg.tail8efe0d.ts.net/ | `main` ブランチが**自動で**反映される | 社員全員 |

- 開発環境と本番は、**データベースも完全に別**です。開発環境で何をしても本番のデータは壊れません。
- どちらも Tailscale VPN の中からのみ開けます。
- 開発環境のログイン: 社員番号 `admin` ／ 管理者パスワードは管理者に確認してください。

> [!WARNING]
> 開発環境と本番のサーバーPC上のフォルダは、GitHub の内容で毎回上書きされます。
> **サーバーPC上で直接ファイルを編集しないでください。**消えます。

---

## 2. 全体の流れ

```
  手元のPCで編集
        │  git push origin developer
        ▼
  GitHub の developer ブランチ
        │  サーバーPCが2分おきに確認 → 自動で取り込み
        ▼
  開発環境 https://…ts.net:8443/  ← ここで動作確認
        │  Pull Request を作る
        ▼
  PM がレビューして Approve
        │  main にマージ
        ▼
  本番 https://…ts.net/           ← 自動で反映（最大2分）
```

**開発者が本番に直接触ることはありません。** main へのマージだけが本番への唯一の入口です。

---

## 3. 手順

### 3-1. 最初の1回だけ

```bash
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI

# 改行コードを LF に固定する（Windows 必須）
# CRLF のままだと Linux コンテナが entrypoint.sh を実行できず起動に失敗します
git config core.autocrlf false

git switch developer

cd saas
cp .env.example .env      # 必要なら値を編集
docker compose up -d      # → http://localhost:8000/
```

### 3-2. 作業を始めるとき

```bash
git switch developer
git pull origin developer     # 他の人の変更を取り込む
```

### 3-3. 編集して手元で確認

```bash
# 編集する

cd saas
docker compose restart web    # → http://localhost:8000/ で確認

# テスト（マージ前に必ず通す。CI でも同じものが走ります）
docker compose exec web sh -c "USE_SQLITE=true python -m pytest tests/ -v"
docker compose exec web ruff check .
docker compose exec web sh -c "USE_SQLITE=true python manage.py makemigrations --check --dry-run"
```

### 3-4. 開発環境に反映する

```bash
git add -A
git commit -m "feat(reports): 日報に写真添付を追加"
git push origin developer
```

**これだけです。** 最大2分で https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/ に反映されます。
外出先のPCから push しても同じように反映されます（サーバーPCは誰も触りません）。

反映されたか確認する:

```bash
# 開発環境が今どのコミットで動いているか
curl -s https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/health/ | head
```

### 3-5. 本番に出す（PM承認）

開発環境で問題ないことを確認してから、Pull Request を作ります。

```bash
gh pr create --base main --head developer --fill
```

または GitHub の画面から `developer` → `main` の Pull Request を作成します。

1. **CI が緑になるのを待つ**（ruff / マイグレーション整合性 / テスト）
2. **PM にレビューを依頼**する
3. PM が **Approve** する
4. PM が **Merge** する
5. 最大2分で本番に反映される

> [!IMPORTANT]
> この「PM承認なしにマージできない」は、GitHub のブランチ保護を設定して初めて**強制**されます。
> 未設定のあいだは技術的には `main` に直接 push できてしまうので、ルールとして守ってください。
> 設定手順（リポジトリ管理者向け）: [main ブランチ保護の設定](branch_protection_setup.md)

マージ後、`developer` を `main` に追いつかせておきます。

```bash
git switch developer
git pull origin main
git push origin developer
```

---

## 4. コミットメッセージ

`種類(場所): 内容` の形にします。

| 例 | 使う場面 |
|----|---------|
| `feat(reports): 日報に写真添付を追加` | 機能追加 |
| `fix(costs): 消化率が1%ずれる不具合を修正` | バグ修正 |
| `docs: READMEにアクセス手順を追記` | ドキュメント |
| `refactor: 共通処理を services.py に移動` | 整理（動作は変えない） |
| `chore: 不要な依存を削除` | 雑務 |

---

## 5. やってはいけないこと

| ❌ | なぜ |
|----|------|
| `main` に直接 push する | 本番に無審査で反映されます。必ず PR 経由で |
| `git push --force` | 他の人のコミットが消えます |
| サーバーPC上でファイルを編集する | 次の自動反映で上書きされて消えます |
| 開発環境のDBを本番だと思って扱う | 別物です。本番データは入っていません |
| `.env` をコミットする | 秘密鍵とパスワードが公開されます（`.gitignore` 済み） |

---

## 6. 困ったとき

| 症状 | 対処 |
|------|------|
| push したのに開発環境が変わらない | 2分待つ。それでも変わらなければ [サーバー運用ガイド](server_operations.md) の「自動デプロイのログを見る」へ |
| コンテナが `exec ./entrypoint.sh: no such file or directory` で起動しない | 改行コードが CRLF になっています。`git config core.autocrlf false` の後、リポジトリを clone し直してください |
| `Conflicting migrations detected` | マイグレーションが分岐しています。`docker compose exec web python manage.py makemigrations --merge` |
| CI の `makemigrations --check` が落ちる | モデルを変えたのにマイグレーションを作っていません。`makemigrations` を実行してコミットしてください |
| 本番でエラーが出た | 自動デプロイは起動確認に失敗すると自動で前のバージョンへ戻します。戻っていない場合は [サーバー運用ガイド](server_operations.md) の「手動で戻す」へ |

---

## 7. 設計ルール

コードを書く前に [saas/CLAUDE.md](../saas/CLAUDE.md) の「絶対ルール」を読んでください。特に:

- テナント帰属モデルは `TenantModel` を継承する
- 金額計算は `Decimal` のみ（`float` 禁止）
- 新規モデルには simple-history を付け、越境テストを同じPRに含める
- 設計判断をしたら `docs/saas/adr/` に1ファイル追加する

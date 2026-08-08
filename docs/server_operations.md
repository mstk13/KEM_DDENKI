# サーバー運用ガイド

アプリを常時稼働させているPC（ホスト名 `desktop-rmsk0vg`）の構成と、
何かあったときの対処をまとめたページです。

**通常はこのPCを触る必要はありません。** 電源が入っていれば、
起動・更新・バックアップはすべて自動で回ります。

---

## 1. このPCで動いているもの

| # | 何 | どこ | いつ動く |
|---|-----|------|---------|
| 1 | Docker Desktop | — | サインイン時に自動起動 |
| 2 | 本番スタック（web/db/redis） | `projects\KEM_DDENKI\saas` | Docker 起動時に自動復帰 |
| 3 | 開発スタック（web/db/redis） | `projects\KEM_DDENKI_dev\saas` | Docker 起動時に自動復帰 |
| 4 | Tailscale serve | — | Windows サービスとして常駐 |
| 5 | 自動デプロイ | タスク `KEM_DDENKI AutoDeploy` | 2分おき |
| 6 | 日次バックアップ | タスク `KEM_DDENKI Daily Backup` | 毎日 12:30 |

### ポートの割り当て

| | 本番 | 開発 |
|---|------|------|
| Compose プロジェクト名 | `saas` | `kemdev` |
| ブランチ | `main` | `developer` |
| Web | 8000 | 8001 |
| PostgreSQL | 5432 | 5433 |
| Redis | 6379 | 6380 |
| 公開URL | `https://desktop-rmsk0vg.tail8efe0d.ts.net/` | `https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/` |

プロジェクト名が違うため、コンテナもボリュームも完全に別物です。
**開発環境のDBを操作しても本番には影響しません。**

---

## 2. 自動デプロイの仕組み

GitHub からこのPCへ届く経路がない（NAT の内側・Tailscale は VPN 内限定）ため、
Webhook ではなく **こちらから2分おきに GitHub を見に行く** 方式にしています。

```
タスクスケジューラ（2分おき）
  └→ tools/autodeploy/autodeploy.sh
       ├ dev :  git fetch origin developer
       │        HEAD と同じ → 何もしない
       │        違う        → reset --hard → build → restart → 起動確認
       └ prod:  git fetch origin main
                HEAD と同じ → 何もしない
                違う        → バックアップ → reset --hard → build → restart → 起動確認
                              起動確認に失敗したら前のコミットへ自動で巻き戻す
```

- **設定**: `~/kem-ops/autodeploy.conf`（このPC固有・Git管理外。雛形は `tools/autodeploy/autodeploy.conf.example`）
- **ログ**: `~/kem-ops/autodeploy.log`
- **実行されるスクリプト**: `~/kem-ops/autodeploy.sh`（リポジトリ外の常設コピー）
- **その正**: `tools/autodeploy/autodeploy.sh`（リポジトリ内。実行のたびに常設コピーへ自動同期される）

> [!NOTE]
> スクリプトの実体をリポジトリ外に置いているのは、リポジトリを巻き戻したときに
> 自動デプロイ本体まで一緒に消えて、二度と動かなくなるのを防ぐためです。
> リポジトリ側を直せば、次の実行で常設コピーに反映されます。

サーバー上のリポジトリは **GitHub の鏡** として扱われます。`reset --hard` と `clean` が走るため、
このPC上で直接編集したものは次回の反映で消えます。`.env` など `.gitignore` 対象は消えません。

### 自動デプロイのログを見る

```bash
tail -50 ~/kem-ops/autodeploy.log
```

更新が無い回は何も出力しません（ログが増えないのは正常です）。

### いま何のコミットが動いているか

```bash
curl -s http://127.0.0.1:8000/health/    # 本番
curl -s http://127.0.0.1:8001/health/    # 開発
```

```json
{"status": "ok", "commit": "a1b2c3d", "branch": "main", "deployed_at": "2026-08-08 19:04:11"}
```

### 今すぐ反映したい（2分待たない）

```bash
bash ~/kem-ops/autodeploy.sh
bash ~/kem-ops/autodeploy.sh dev   # 開発だけ
```

### 手動で戻す

自動の巻き戻しが効かなかった場合:

```bash
cd "/c/Users/kazushi kenmochi/projects/KEM_DDENKI"
git log --oneline -5                 # 戻したいコミットを選ぶ
git reset --hard <コミットID>
cd saas && docker compose up -d --build && docker compose restart web
```

このあと `main` を直さないと、次の自動デプロイでまた同じコミットに戻ります。
**GitHub 側で revert してください。**

---

## 3. バックアップ

| | |
|---|---|
| 保存先 | `D:\backup\kem_ddenki\` |
| 中身 | PostgreSQL 全体ダンプ + media ファイル |
| 頻度 | 毎日 12:30（PC が落ちていた場合は次回起動時に実行） |
| 保持 | 14日 |
| ログ | `D:\backup\kem_ddenki\backup.log` |
| スクリプト | `saas/scripts/backup.sh` |

対象は**本番のみ**です（開発環境は捨てて作り直せるため取っていません）。
本番への自動デプロイ時にも、反映の直前に1回取得します。

### 手動でバックアップする

```bash
bash "/c/Users/kazushi kenmochi/projects/KEM_DDENKI/saas/scripts/backup.sh"
```

### バックアップから復元する

> [!CAUTION]
> 下の手順は**現在の本番データを破棄して**置き換えます。実行前に必ず今のバックアップを取ってください。

```bash
cd "/c/Users/kazushi kenmochi/projects/KEM_DDENKI/saas"

# 1. 念のため現状を退避
bash scripts/backup.sh

# 2. 中身を確認してから戻す（まず検証用DBで開いて中身を見るのが安全）
docker compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS restore_test;" -c "CREATE DATABASE restore_test;"
zcat /d/backup/kem_ddenki/db_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U postgres -d restore_test -q
docker compose exec -T db psql -U postgres -d restore_test -c "select count(*) from accounts_user;"

# 3. 本番DBを置き換える
docker compose stop web
docker compose exec -T db psql -U postgres -c "DROP DATABASE kensetsu_saas;" -c "CREATE DATABASE kensetsu_saas;"
zcat /d/backup/kem_ddenki/db_YYYYMMDD_HHMMSS.sql.gz | docker compose exec -T db psql -U postgres -d kensetsu_saas -q
docker compose start web

# 4. 検証用DBを片付ける
docker compose exec -T db psql -U postgres -c "DROP DATABASE restore_test;"
```

media ファイルを戻す場合:

```bash
tar xzf /d/backup/kem_ddenki/media_YYYYMMDD_HHMMSS.tar.gz -C /tmp
docker cp /tmp/media/. saas-web-1:/app/media/
```

---

## 4. PCを再起動したあと

**何もしなくて構いません。** サインインすれば次の順で自動的に立ち上がります。

```
Windows サインイン
  → Docker Desktop 起動（AutoStart 有効）
  → コンテナ復帰（restart: always）
  → 数十秒でアプリが応答
```

Tailscale の公開設定（serve）は tailscaled 側に保存されているため、再設定は不要です。

確認したいとき:

```bash
docker ps
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8000/login/
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/login/
"/c/Program Files/Tailscale/tailscale.exe" serve status
```

> [!IMPORTANT]
> コンテナは **Windows にサインインしないと起動しません**（Docker Desktop がユーザーセッションで動くため）。
> 再起動後はサインインまで済ませておいてください。

---

## 5. よくあるトラブル

| 症状 | 確認すること | 対処 |
|------|------------|------|
| どの端末からもアプリが開けない | `docker ps` にコンテナが出るか | 出ない → Docker Desktop を起動。出るのに開けない → `docker compose logs web` |
| 特定の端末だけ開けない | その端末の Tailscale | Tailscale アプリで接続状態にする |
| push しても反映されない | `tail -50 ~/kem-ops/autodeploy.log` | `git fetch に失敗` → 認証切れ。`cd リポジトリ && git fetch` を手で実行して認証し直す |
| 反映後にアプリが落ちた | 同上のログ | `巻き戻し完了` と出ていれば前バージョンで稼働中。GitHub 側で revert する |
| ディスクが埋まってきた | `docker system df` | `docker image prune -a`（稼働中のイメージは消えません） |
| バックアップが増え続ける | `ls /d/backup/kem_ddenki` | 14日で自動削除される。されていなければ `backup.log` を確認 |

### コンテナのログを見る

```bash
cd "/c/Users/kazushi kenmochi/projects/KEM_DDENKI/saas"      # 本番
cd "/c/Users/kazushi kenmochi/projects/KEM_DDENKI_dev/saas"  # 開発
docker compose logs web --tail 100
docker compose logs db --tail 50
```

---

## 6. 設定を変えるとき

| 変えたいもの | 場所 | 反映方法 |
|-------------|------|---------|
| 管理者パスワード（社長ログイン） | 各 `saas/.env` の `PRESIDENT_PIN` | `docker compose up -d web` |
| 公開ポート | 各 `saas/.env` の `WEB_PORT` 等 | `docker compose up -d` + `tailscale serve` を貼り直す |
| 自動デプロイの間隔 | タスクスケジューラ `KEM_DDENKI AutoDeploy` | タスクのトリガーを編集 |
| バックアップの時刻・保持日数 | タスク `KEM_DDENKI Daily Backup` / `scripts/backup.sh` の `KEEP_DAYS` | — |
| 監視対象の環境 | `~/kem-ops/autodeploy.conf` | 次回実行から反映 |

`.env` はどちらも Git 管理外です。**このPCにしか存在しないので、消さないでください。**
（内容は `.env.example` を見れば復元できますが、`DJANGO_SECRET_KEY` を変えると全員ログアウトされます）

---

## 7. サーバーを新しいPCに移すとき

1. Docker Desktop / Git / Tailscale を入れ、Tailscale にサインイン
2. 本番用と開発用にリポジトリを2つ clone する（`git config core.autocrlf false` を忘れずに）
   - 本番: `main` ブランチ
   - 開発: `developer` ブランチ
3. それぞれ `saas/.env` を作る（開発側は `COMPOSE_PROJECT_NAME=kemdev` とポートをずらす）
4. 本番DBを最新バックアップから復元する（第3章）
5. `docker compose up -d --build` を両方で実行
6. `tailscale serve --bg 8000` と `tailscale serve --bg --https=8443 http://127.0.0.1:8001`
7. `~/kem-ops/autodeploy.conf` を作り、`tools/autodeploy/autodeploy.sh` を `~/kem-ops/autodeploy.sh` にコピーする
8. タスクスケジューラに AutoDeploy と Daily Backup を登録する
9. Docker Desktop の「サインイン時に起動」を有効にする

# KEM_DDENKI サーバーセットアップガイド

> [!IMPORTANT]
> **この手順は現在の構成では使っていません。**
> 実際の外部公開は Cloudflare Tunnel ではなく **Tailscale serve** で行っており、
> 独自ドメインもポート開放も使っていません。
> 現在の構成は [サーバー運用ガイド](../../docs/server_operations.md)、
> 端末側の接続手順は [Tailscale セットアップ](../../docs/tailscale_setup.md) を参照してください。
> このページは将来ドメイン公開に切り替える場合の参考として残しています。

---

常時稼働デスクトップPC（FRONTIER BTO / i5-10400F / 32GB / RTX 3060 12GB / Windows 11 Home）に
KEM_DDENKIを構築し、社内LAN + 社外（Cloudflare Tunnel）からアクセスできるようにする手順。

本ドキュメントをClaude Codeに読み込ませ、指示に従って自動セットアップを行うことを想定。

---

## 前提条件

- デスクトップPC: FRONTIER BTO, i5-10400F, 32GB RAM, Windows 11 Home
- 有線LANで社内ネットワークに接続済み
- 外付けUSB 1TB（バックアップ用）を接続済み
- ノートPCからリモート操作する

---

## Phase A: デスクトップPC 初期設定（デスクトップPC上で実行）

### A-1. IPアドレス固定

1. コマンドプロンプトで現在のIPとMACアドレスを確認:
   ```
   ipconfig /all
   ```
   → 「イーサネット」の「IPv4 アドレス」と「物理アドレス」をメモ

2. ルーター管理画面（通常 http://192.168.0.1 ）にアクセス

3. DHCP予約設定で、このPCのMACアドレスに固定IPを割り当て:
   - IPアドレス: 任意の固定IP（DHCP のままだと後でURLが壊れる）
   - これによりPCを再起動してもIPが変わらなくなる

4. PC を再起動して固定IPが反映されたか確認:
   ```
   ipconfig
   ```

### A-2. Windows 自動ログオン設定

再起動後にパスワード入力なしでログインし、Docker Desktopが自動起動するようにする。

1. Win + R → `netplwiz` と入力してEnter
2. 「ユーザーがこのコンピューターを使うには、ユーザー名とパスワードの入力が必要」のチェックを外す
3. 「適用」→ パスワードを2回入力 → OK

※ Windows 11 でこのオプションが表示されない場合:
1. Win + R → `regedit` でレジストリエディタを開く
2. `HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device`
3. `DevicePasswordLessBuildVersion` の値を `0` に変更
4. 再度 `netplwiz` を開くとチェックボックスが表示される

### A-3. Windows Update 再起動制御

1. 設定 → Windows Update → 詳細オプション
2. 「アクティブ時間」を手動で設定: 5:00 〜 23:00
3. これにより業務時間中の自動再起動を防止

### A-4. スリープ・画面オフ設定

サーバーなのでスリープさせない:

1. 設定 → システム → 電源とバッテリー → 画面とスリープ
2. 画面の電源を切る: 30分
3. スリープ: なし（「しない」を選択）

PowerShellで一括設定する場合:
```powershell
powercfg /change standby-timeout-ac 0
powercfg /change hibernate-timeout-ac 0
powercfg /change monitor-timeout-ac 30
```

### A-5. Windows ファイアウォール設定

他のPCからのアクセスを許可する:

```powershell
# 管理者権限のPowerShellで実行
# Django (8000番ポート) を許可
netsh advfirewall firewall add rule name="KEM_DDENKI Django" dir=in action=allow protocol=tcp localport=8000

# PostgreSQL (5432番ポート) ※ 外部DBアクセスが必要な場合のみ
# netsh advfirewall firewall add rule name="KEM_DDENKI PostgreSQL" dir=in action=allow protocol=tcp localport=5432
```

### A-6. Docker Desktop インストールと設定

1. https://www.docker.com/products/docker-desktop/ からダウンロード・インストール
2. インストール時に「Use WSL 2 instead of Hyper-V」を選択
3. インストール後、Docker Desktop を起動
4. Settings → General:
   - ✅ Start Docker Desktop when you sign in to your computer
   - ✅ Use the WSL 2 based engine
5. Settings → Resources → WSL Integration:
   - Ubuntu（デフォルトディストリビューション）を有効化

### A-7. Git インストールと リポジトリ取得

```powershell
# Git がなければインストール（winget使用）
winget install Git.Git

# PowerShell を再起動してから:
cd C:\Users\<ユーザー名>
git clone https://github.com/mstk13/KEM_DDENKI.git
cd KEM_DDENKI
git checkout feature/ai-phase2-claude-api
```

### A-8. 環境変数ファイル作成

```powershell
cd C:\Users\<ユーザー名>\KEM_DDENKI\saas
copy .env.example .env
```

`.env` をメモ帳で開いて以下を設定:

```
DJANGO_SECRET_KEY=<ランダムな長い文字列に変更>
DJANGO_DEBUG=False
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,app.your-domain.com

DB_NAME=kensetsu_saas
DB_USER=postgres
DB_PASSWORD=<強力なパスワードに変更>
DB_HOST=db
DB_PORT=5432

ANTHROPIC_API_KEY=<AnthropicダッシュボードからコピーしたAPIキー>

# 社外アクセスを設定する場合（Phase C 完了後）
# CLOUDFLARE_TUNNEL_TOKEN=<Cloudflareトンネルトークン>
```

DJANGO_SECRET_KEY の生成（WSL またはPowerShellで）:
```bash
python -c "import secrets; print(secrets.token_urlsafe(50))"
```

### A-9. アプリケーション起動

```powershell
cd C:\Users\<ユーザー名>\KEM_DDENKI\saas
docker compose up -d
```

起動確認:
```powershell
# コンテナ状態確認
docker compose ps

# ログ確認
docker compose logs web --tail 20

# ブラウザで確認
start http://localhost:8000/
```

### A-10. 既存データの移行（ノートPCからデータを移す場合）

ノートPC側（WSLターミナル）で:
```bash
cd /mnt/c/Users/masat/KEM_DDENKI/saas
docker compose exec -T db pg_dump -U postgres kensetsu_saas > /mnt/c/Users/masat/Desktop/backup.sql
```

`backup.sql` をUSBメモリやネットワーク共有でデスクトップPCにコピー。

デスクトップPC側で:
```powershell
cd C:\Users\<ユーザー名>\KEM_DDENKI\saas
# 既存データを一旦リセットしてインポート
docker compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS kensetsu_saas;"
docker compose exec -T db psql -U postgres -c "CREATE DATABASE kensetsu_saas;"
type C:\Users\<ユーザー名>\Desktop\backup.sql | docker compose exec -T db psql -U postgres kensetsu_saas
```

---

## Phase B: ノートPCからリモート操作

Windows 11 Home はリモートデスクトップの「ホスト」になれないため、
代替手段でリモートアクセスする。

### 方法1: RustDesk（推奨 — 無料・自己ホスト可能）

**デスクトップPC（サーバー側）:**
1. https://rustdesk.com/ からダウンロード・インストール
2. 起動するとIDとパスワードが表示される → メモ
3. 設定 → 「Windows起動時に自動起動」をON
4. 設定 → セキュリティ → パスワードを固定（「固定パスワードのみ使用」）

**ノートPC（クライアント側）:**
1. 同じく RustDesk をインストール
2. デスクトップPCのIDを入力 → 接続 → パスワード入力

### 方法2: Chrome リモート デスクトップ（Googleアカウントがあれば簡単）

**デスクトップPC:**
1. Chrome で https://remotedesktop.google.com/access にアクセス
2. 「リモートアクセスの設定」→ 拡張機能インストール
3. PCの名前とPINを設定
4. 「リモート接続を有効にする」

**ノートPC:**
1. Chrome で https://remotedesktop.google.com/access にアクセス
2. 同じGoogleアカウントでログイン
3. デスクトップPCをクリック → PIN入力 → 接続

### 方法3: SSH（CLIのみ。GUIは不要な場合）

**デスクトップPC（WSLで設定）:**
```bash
# WSL (Ubuntu) 内で
sudo apt update && sudo apt install openssh-server -y
sudo systemctl enable ssh
sudo systemctl start ssh
```

Windows側ファイアウォール:
```powershell
netsh advfirewall firewall add rule name="SSH" dir=in action=allow protocol=tcp localport=22
```

**ノートPC から接続:**
```bash
ssh <ユーザー名>@<サーバーのLAN IP>
cd /mnt/c/Users/<ユーザー名>/KEM_DDENKI/saas
docker compose ps
docker compose logs web --tail 20
```

### リモート操作でよく使うコマンド

```bash
# コンテナ状態確認
docker compose ps

# ログ確認
docker compose logs web --tail 30
docker compose logs db --tail 10

# 再起動
docker compose restart web

# 全体再起動
docker compose down && docker compose up -d

# マイグレーション実行（コード更新後）
docker compose exec web python manage.py migrate

# 管理ユーザー作成
docker compose exec web python manage.py createsuperuser

# ML モデル学習（完工済み現場5件以上必要）
docker compose exec web python manage.py train_cost_model

# バックアップ手動実行
bash scripts/backup.sh /mnt/d/backup
```

---

## Phase C: 社外アクセス（Cloudflare Tunnel）

### C-1. ドメイン取得

ドメインを持っていない場合、以下のいずれかで取得（年額1,500円程度〜）:
- Cloudflare Registrar（Cloudflareで直接購入可能）
- お名前.com
- Google Domains

### C-2. Cloudflare アカウント作成とドメイン登録

1. https://dash.cloudflare.com/sign-up でアカウント作成
2. 「サイトを追加」→ ドメイン名入力 → 無料プラン選択
3. 表示されるネームサーバーをドメインレジストラで設定
4. 反映を待つ（数分〜数時間）

### C-3. トンネル作成

1. Cloudflare ダッシュボード → Zero Trust（https://one.dash.cloudflare.com/）
2. Networks → Tunnels → 「トンネルを作成」
3. Cloudflared を選択 → トンネル名: `kem-ddenki`
4. **トークンをコピー**（`eyJh...` で始まる長い文字列）
5. Public Hostname を追加:
   - サブドメイン: `app`
   - ドメイン: 取得したドメイン
   - タイプ: HTTP
   - URL: `web:8000`

### C-4. デスクトップPCで設定

```bash
# .env にトークンを追加
# CLOUDFLARE_TUNNEL_TOKEN=eyJhxxxxxxxx...

# DJANGO_ALLOWED_HOSTS にドメインを追加
# DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,app.your-domain.com

# Tunnel付きで起動
docker compose --profile tunnel up -d

# ログ確認（Connection registered が出れば成功）
docker compose logs cloudflared
```

### C-5. アクセス制御（Cloudflare Access）

**重要: これを設定しないとURLを知っている誰でもアクセスできてしまう。**

1. Zero Trust → Access → Applications → 「アプリケーションを追加」
2. Self-hosted を選択
3. Application name: `KEM_DDENKI`
4. Application domain: `app.your-domain.com`
5. Session Duration: `24 hours`
6. ポリシー作成:
   - Policy name: `社員のみ`
   - Action: Allow
   - Include: Emails → 許可するメールアドレスを列挙
   - または: Emails ending in → `@your-domain.com`

これでアクセス時にメールアドレス入力 → ワンタイムコード受信 → 入力で認証。

### C-6. 動作確認

社外のネットワーク（スマホのモバイル回線など）から:
```
https://app.your-domain.com/
```
→ Cloudflare Access 認証画面 → メール認証 → KEM_DDENKI ログイン画面

---

## Phase D: バックアップ設定

### D-1. 外付けUSBのマウント確認

外付けUSB 1TBのドライブレターを確認（例: D: や E:）。
WSL からは `/mnt/d/` や `/mnt/e/` でアクセスできる。

### D-2. バックアップディレクトリ作成

```powershell
mkdir D:\backup\kem_ddenki
```

### D-3. Windowsタスクスケジューラで日次バックアップ

1. Win + R → `taskschd.msc`
2. 「タスクの作成」
3. 全般タブ:
   - 名前: `KEM_DDENKI Daily Backup`
   - 「ユーザーがログオンしているかどうかにかかわらず実行する」
   - 「最上位の特権で実行する」にチェック
4. トリガータブ → 新規:
   - 毎日 03:00
5. 操作タブ → 新規:
   - プログラム: `wsl`
   - 引数: `bash -c "cd /mnt/c/Users/<ユーザー名>/KEM_DDENKI/saas && bash scripts/backup.sh /mnt/d/backup/kem_ddenki"`
6. OK → パスワード入力

### D-4. バックアップ確認

翌日以降、バックアップファイルが作成されているか確認:
```powershell
dir D:\backup\kem_ddenki\
```

`db_20260808_030000.sql.gz` のようなファイルがあればOK。

### D-5. リストア手順（万が一の復旧用）

```bash
cd /mnt/c/Users/<ユーザー名>/KEM_DDENKI/saas

# 最新のバックアップを解凍
gunzip -k /mnt/d/backup/kem_ddenki/db_XXXXXXXX_XXXXXX.sql.gz

# DBをリストア
docker compose exec -T db psql -U postgres -c "DROP DATABASE IF EXISTS kensetsu_saas;"
docker compose exec -T db psql -U postgres -c "CREATE DATABASE kensetsu_saas;"
cat /mnt/d/backup/kem_ddenki/db_XXXXXXXX_XXXXXX.sql | docker compose exec -T db psql -U postgres kensetsu_saas

# マイグレーション再実行
docker compose exec web python manage.py migrate
```

---

## Phase E: UPS（無停電電源装置）— 推奨

停電時にDBが壊れるのを防ぐ。

### 推奨機種（家庭用で十分）
- APC BE425M-JP（約6,000円）
- CyberPower CP550JP（約5,000円）

### 接続
1. UPS にデスクトップPC + 外付けUSB を接続
2. UPS のUSBケーブルをPCに接続（シャットダウン連携用）
3. Windows の電源オプションで「バッテリ残量が少なくなったらシャットダウン」を設定

---

## チェックリスト（完了確認用）

### デスクトップPC設定
- [ ] IPアドレス固定
- [ ] 自動ログオン設定
- [ ] Windows Update アクティブ時間設定
- [ ] スリープ無効化
- [ ] ファイアウォール 8000番ポート開放
- [ ] Docker Desktop インストール・自動起動ON
- [ ] Git インストール・リポジトリ取得
- [ ] .env ファイル作成・設定
- [ ] docker compose up -d で起動確認
- [ ] 管理ユーザー作成（createsuperuser）

### リモートアクセス
- [ ] RustDesk または Chrome リモートデスクトップ設定
- [ ] ノートPCからリモート接続確認
- [ ] SSH 接続確認（任意）

### 社外アクセス
- [ ] ドメイン取得
- [ ] Cloudflare アカウント・ドメイン登録
- [ ] トンネル作成・トークン取得
- [ ] .env に CLOUDFLARE_TUNNEL_TOKEN 設定
- [ ] docker compose --profile tunnel up -d
- [ ] Cloudflare Access 認証設定
- [ ] 社外ネットワークからアクセス確認

### バックアップ
- [ ] 外付けUSB接続・マウント確認
- [ ] バックアップスクリプト動作確認
- [ ] タスクスケジューラで日次バックアップ設定
- [ ] バックアップファイル生成確認

### オプション
- [ ] UPS 接続
- [ ] データ移行（ノートPCから）

# Cloudflare Tunnel セットアップ手順

> [!IMPORTANT]
> **この手順は現在の構成では使っていません。**
> 実際の外部公開は Cloudflare Tunnel ではなく **Tailscale serve** で行っており、
> 独自ドメインもポート開放も使っていません。
> 現在の構成は [サーバー運用ガイド](../../docs/server_operations.md)、
> 端末側の接続手順は [Tailscale セットアップ](../../docs/tailscale_setup.md) を参照してください。
> このページは将来ドメイン公開に切り替える場合の参考として残しています。

---

社外（自宅・出先）からKEM_DDENKIに安全にアクセスするための設定手順。
ルーターのポート開放は不要。HTTPS自動対応。

---

## 前提条件

- Docker + Docker Compose が動作していること
- 独自ドメインを持っていること（なければ取得する。年額1,500円程度〜）

---

## 1. Cloudflareアカウント作成

1. [https://dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up) にアクセス
2. メールアドレスとパスワードで登録
3. 無料プラン（Free）を選択

## 2. ドメインをCloudflareに登録

1. ダッシュボード →「サイトを追加」→ ドメイン名を入力
2. 無料プランを選択
3. 表示されたネームサーバー（例: `xxx.ns.cloudflare.com`）をドメインレジストラで設定
4. ネームサーバー反映まで数分〜数時間待つ

> **ドメインを持っていない場合:**
> Cloudflare Registrar や Google Domains、お名前.com 等で取得してください。
> `.com` で年額約1,500円、`.dev` で約1,400円程度です。

## 3. Cloudflare Tunnel の作成

1. Cloudflareダッシュボード → **Zero Trust** に移動
   （左メニュー → Zero Trust、または [https://one.dash.cloudflare.com/](https://one.dash.cloudflare.com/)）
2. **Networks** → **Tunnels** → 「トンネルを作成」
3. **Cloudflared** を選択 → 「次へ」
4. トンネル名を入力（例: `kem-ddenki`）→ 「トンネルを保存」
5. **トークンが表示される** → これをコピー（`eyJh...` で始まる長い文字列）

## 4. Public Hostname の設定

トンネル作成画面の続き、または作成後にトンネルの設定画面で：

1. 「パブリックホスト名を追加」をクリック
2. 以下を入力：

| 項目 | 値 |
|------|-----|
| サブドメイン | `app`（任意。例: `app.example.com`） |
| ドメイン | Cloudflareに登録したドメイン |
| タイプ | `HTTP` |
| URL | `web:8000` |

3. 「ホスト名を保存」

> `web:8000` はDocker内部のサービス名とポートです。
> Nginxを前段に置く構成の場合は `nginx:80` に変更してください。

## 5. .env にトークンを設定

```bash
cd saas
cp .env.example .env  # 初回のみ
```

`.env` を編集し、手順3でコピーしたトークンを設定：

```
CLOUDFLARE_TUNNEL_TOKEN=eyJhxxxxxxxxxxxxxxxx...
```

## 6. 起動

```bash
# cloudflaredコンテナも一緒に起動
docker compose --profile tunnel up -d

# ログ確認
docker compose logs cloudflared
```

以下のようなログが出れば成功：
```
INF Connection registered connIndex=0 ...
INF Connection registered connIndex=1 ...
```

## 7. 動作確認

ブラウザで `https://app.example.com`（手順4で設定したホスト名）にアクセス。
KEM_DDENKIのログイン画面が表示されればOK。

---

## 8. アクセス制御の設定（推奨）

このままだとURLを知っている人は誰でもアクセスできてしまいます。
**Cloudflare Access** でメールアドレスOTP認証を追加します。

1. Zero Trust → **Access** → **Applications** → 「アプリケーションを追加」
2. **Self-hosted** を選択
3. 以下を入力：

| 項目 | 値 |
|------|-----|
| Application name | `KEM_DDENKI` |
| Session Duration | `24 hours` |
| Application domain | `app.example.com` |

4. 「次へ」→ ポリシーを作成：

| 項目 | 値 |
|------|-----|
| Policy name | `社員のみ` |
| Action | `Allow` |
| Include | **Emails** → 許可するメールアドレスを列挙 |

> **例:** `tanaka@example.com`, `suzuki@example.com` など社員のメールを追加。
> または **Emails ending in** で `@example.com` とすれば全社員を許可できます。

5. 「保存」

これで、アクセス時にメールアドレスを入力 → ワンタイムコードが届く → 入力で認証、という流れになります。

---

## トラブルシューティング

### cloudflaredコンテナが起動しない

```bash
docker compose --profile tunnel logs cloudflared
```

- `TUNNEL_TOKEN is not set` → `.env` にトークンが設定されていない
- `connection refused` → `web` サービスが起動していない（`docker compose ps` で確認）

### 外部からアクセスできない

1. Cloudflareダッシュボードでトンネルのステータスが「HEALTHY」か確認
2. Public Hostname の URL が `web:8000` になっているか確認
3. `DJANGO_ALLOWED_HOSTS` にドメインを追加：
   ```
   DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,app.example.com
   ```

### 社内LAN経由のアクセスは？

Cloudflare Tunnel を使っても、社内LANからは `http://<サーバーのLAN IP>:8000` でアクセスできます。
両方のアクセス経路が共存します。

ただし**現在の構成では社内LANの直接アクセスは提供していません**。DHCP でIPが変わると
URLが壊れるため、社内・社外とも Tailscale 経由に統一しています。

### トンネルを停止したい

```bash
# cloudflaredだけ停止（他のコンテナは動き続ける）
docker compose --profile tunnel stop cloudflared

# または --profile tunnel を外して起動し直す
docker compose up -d
```

---

## 構成図

```
【社外アクセス】
  スマホ/PC → HTTPS → Cloudflare Edge
    → (Access認証) → Cloudflare Tunnel
    → cloudflaredコンテナ → web:8000 → Django

【社内アクセス（従来通り）】
  社内PC → HTTP → <サーバーのLAN IP>:8000 → Django
```

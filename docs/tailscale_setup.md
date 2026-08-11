# Tailscale セットアップ手順

社外（外部ネットワーク）からケンモチ電機のアプリにアクセスするための手順です。  
Tailscale は無料の VPN サービスで、インストールしてログインするだけで社内サーバーに安全に接続できます。

---

## 共有アカウント情報

| 項目 | 値 |
|------|-----|
| ログイン方法 | Google アカウント |
| アカウント | kec.apps.network@gmail.com |

> パスワードは管理者（mstk13）に確認してください。

---

## アクセスURL（Tailscale接続後）

| 環境 | URL | 使う人 |
|------|-----|--------|
| **本番** | https://desktop-rmsk0vg.tail8efe0d.ts.net/ | 社員全員 |
| **開発** | https://desktop-rmsk0vg.tail8efe0d.ts.net:8443/ | 開発者・PM |

社内にいても社外にいても、開くURLは同じです。Tailscale がつながってさえいれば、
自宅でも現場でも同じように使えます。

### 名前で開けないときの代替URL

| 環境 | URL |
|------|-----|
| 本番 | http://100.76.219.49:8000/ |
| 開発 | http://100.76.219.49:8001/ |

サーバーの Tailscale IP に直接つなぐURLです。名前解決を使わないため、
ブラウザのセキュア DNS の影響を受けません。中身は上の表と同じアプリです。

---

## PC（Windows）のセットアップ

### 手動セットアップ

1. https://tailscale.com/download にアクセス
2. **Windows** 版をダウンロード・インストール
3. タスクトレイの Tailscale アイコンをクリック → **Log in**
4. **Google** を選択 → 共有アカウントでログイン
5. ブラウザで https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開いて表示されれば完了

### コマンドでセットアップする場合

winget が使える PC なら、以下でインストールからログインまで進められます。

```powershell
winget install --id Tailscale.Tailscale -e
& "C:/Program Files/Tailscale/tailscale.exe" up
```

`tailscale up` がログインURLを表示するので、ブラウザで開いて共有 Google アカウントで
ログインしてください。接続できたか確認するには:

```powershell
& "C:/Program Files/Tailscale/tailscale.exe" status
```

`desktop-rmsk0vg` が一覧に出ていれば成功です。

> 以前ここに載っていた `raw.githubusercontent.com` から手順書を読ませるコマンドは、
> **このリポジトリが非公開のため動作しません**（匿名アクセスは 404 になります）。

---

## PC（Mac）のセットアップ

1. App Store で「**Tailscale**」を検索・インストール
2. メニューバーの Tailscale アイコンをクリック → **Log in**
3. **Google** を選択 → 共有アカウントでログイン
4. ブラウザで https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開いて表示されれば完了

---

## スマホ（iPhone）のセットアップ

1. **App Store** を開く
2. 「**Tailscale**」で検索
3. インストール（無料）
4. アプリを開く → **Get Started**
5. **Google** を選択 → 共有アカウントでログイン
6. 「Tailscale would like to add VPN Configurations」と表示されたら **Allow（許可）**
7. Safari で https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開く
8. ポータルが表示されれば完了

> ホーム画面にアイコンを追加する場合:  
> Safari で開いた状態 → 共有ボタン（□↑）→「ホーム画面に追加」

---

## スマホ（Android）のセットアップ

1. **Google Play** を開く
2. 「**Tailscale**」で検索
3. インストール（無料）
4. アプリを開く → **Get Started**
5. **Google** を選択 → 共有アカウントでログイン
6. 「VPN接続リクエスト」が表示されたら **OK**
7. Chrome で https://desktop-rmsk0vg.tail8efe0d.ts.net/ を開く
8. ポータルが表示されれば完了

> ホーム画面にアイコンを追加する場合:  
> Chrome で開いた状態 → メニュー（⋮）→「ホーム画面に追加」

---

## 注意事項

- Tailscale は VPN 接続中のみ有効です。スマホのステータスバーに VPN アイコンが表示されて
  いることを確認してください
- **社内Wi-Fiにつないでいても、Tailscale が入っていない端末からは開けません。**
  社内LANの直接アクセスは提供していません（サーバーのIPがDHCPで変わると壊れるため）
- アプリを入れるだけでは不十分です。上の共有 Google アカウントで**サインインするところまで**
  必要です
- **ブラウザのセキュア DNS は切ってください**（下記）。切らないと Tailscale が
  つながっていても名前でアクセスできません
- 1つの Google アカウントで最大 100 台まで接続可能（無料プラン）
- サーバーPCの電源が落ちている・Windows にサインインしていない場合はつながりません

---

## セキュア DNS を切る（PC のみ・初回1回）

アプリのURL（`…tail8efe0d.ts.net`）は **Tailscale の中にしか存在しない名前**で、外部のDNS
サーバーには登録されていません。ブラウザの「セキュア DNS（DNS over HTTPS）」が有効だと、
ブラウザはパソコンの名前解決を飛び越えて外部のDNSへ直接問い合わせるため、この名前が
見つからずアクセスに失敗します。**Tailscale はつながっているのに開けない**、という
分かりにくい症状になります。

| ブラウザ | 手順 |
|---------|------|
| Chrome | `chrome://settings/security` → 「**セキュア DNS を使用する**」を**オフ** |
| Edge | `edge://settings/privacy` → 「**セキュア DNS を使用して…**」を**オフ** |
| Safari (iPhone / Mac) | 影響しません。設定変更は不要です |

切りたくない場合は、代替URL `http://100.76.219.49:8000/` を使ってください。
どちらのURLでも、通信は Tailscale によって暗号化されています。

判定方法:

```
名前のURL  → 開けない
IPのURL    → 開ける          ⇒ セキュア DNS が原因
両方開けない                 ⇒ Tailscale が未接続
```

---

## トラブルシューティング

| 症状 | 対処法 |
|------|--------|
| IPのURLなら開けるが名前だと開けない | ブラウザのセキュア DNS。上記手順で切る |
| `DNS_PROBE_FINISHED_NXDOMAIN` と出る | 同上 |
| ページが開かない | Tailscale アプリが「Connected」か確認。切断されていたら再接続 |
| ログインできない | 共有アカウントのパスワードを管理者に確認 |
| VPN許可の画面が出ない | 端末の設定 → VPN → Tailscale を手動で許可 |
| 接続が遅い | 一度 Tailscale をオフ→オンにして再接続 |

---

## 管理者向け: 鍵の有効期限について

Tailscale の端末には認証キーの有効期限があり、切れると tailnet から自動的に切断されます。

**サーバーPC（`desktop-rmsk0vg`）は有効期限を無効化してあります。**
これを元に戻すと、期限が来た時点で全端末からアプリにアクセスできなくなります。
アプリ自体は動いたままなので原因が分かりにくい障害になります。**再有効化しないでください。**

確認方法:

```bash
tailscale status --json | grep KeyExpiry    # サーバー側が null なら無効化済み
```

社員の端末は期限が切れても本人が再ログインすれば復旧するため、無効化は不要です。

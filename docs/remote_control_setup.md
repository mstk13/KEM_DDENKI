# Remote Control セットアップ手順

自分のPCで動いている Claude Code を、**スマホやブラウザから操作する**ための手順です。
外出先から進捗を見たり、確認（許可を求められたとき）に答えたり、指示を追加したりできます。

> [!NOTE]
> これは Claude Code の機能で、このリポジトリのアプリとは無関係です。
> ケンモチ電機のアプリを社外から開く手順は [Tailscale セットアップ](tailscale_setup.md) を参照してください。

---

## 2種類あります（間違えやすい）

| | どこで動くか | 使うとき |
|---|---|---|
| **Remote Control** | **自分のPC**。スマホは画面と入力だけ | 手元のファイル・Docker・MCP をそのまま使いたい |
| クラウドセッション | Anthropic のクラウド（使い捨てコンテナ） | PCを閉じても進めたい。GitHub のリポジトリだけで足りる |

クラウドセッションは claude.ai/code やスマホアプリの **Code** タブから作れるもので、
**設定なしで最初からスマホで見られます**。ターミナルから作るときは `claude --cloud "…"`、
クラウドのセッションを手元に引き取るときは `claude --teleport` です。

このページは上の **Remote Control** の話です。

---

## 前提条件

| 項目 | 内容 |
|------|------|
| プラン | Pro / Max / Team / Enterprise。**APIキー認証では使えません** |
| ログイン | `claude` を起動して `/login` で claude.ai アカウントにサインイン |
| 接続先 | Bedrock / Vertex / Foundry 経由は不可。`ANTHROPIC_BASE_URL` を `api.anthropic.com` 以外に向けていると不可 |
| 環境変数 | `DISABLE_TELEMETRY` `DO_NOT_TRACK` `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC` `DISABLE_GROWTHBOOK` が設定されていると使えません |
| 信頼 | **プロジェクトのフォルダで**一度 `claude` を起動して信頼ダイアログを承認する（ホームディレクトリでは保存されません） |

Team / Enterprise 契約の場合は、Owner が管理設定で Remote Control を有効にしておく必要があります。

---

## 手順

```bash
cd C:\path\to\KEM_DDENKI     # プロジェクトのフォルダへ（ホームではなく）
claude                        # 起動。初回は信頼ダイアログを承認
/login                        # claude.ai アカウントでサインイン
/remote-control               # 略記 /rc。初回は Enable Remote Control? に y
```

起動のしかたは3通りあります。ふだんは1つめで十分です。

| コマンド | 何が起きるか |
|---------|-------------|
| `/remote-control`（`/rc`） | **開いているセッションを**遠隔操作できるようにする |
| `claude --remote-control "名前"`（`--rc`） | 最初から有効にして起動する。ターミナルでも打てる |
| `claude remote-control` | サーバーモード。ターミナルは待機役になる。**spacebar でQRコード**を表示 |

---

## スマホから繋ぐ

次のどれでも繋がります。

- 表示された**QRコード**をスマホのカメラで読む（Claude アプリが直接開く）
- **Claude アプリ** → 下の **Code** タブ → 一覧から選ぶ
  （Remote Control のセッションは **PCアイコン＋緑のドット**で出ます）
- 表示された**セッションURL**を、どのブラウザでも開く

アプリが入っていなければ、`claude` の中で `/mobile` を打つとインストール用のQRが出ます。

### 繋がると何ができるか

- 手元の環境そのまま（ファイル・MCP・`.claude/` の設定）。`@` でローカルのファイル名が補完される
- ターミナル・ブラウザ・スマホのどこからでも交互に指示できる（会話は同期される）
- **未コミットの差分**をスマホで確認できる
- **許可を求められたときにスマホから答えられる**
- 長い処理が終わったらプッシュ通知が来る（「テストが終わったら通知して」と頼んでもよい）

---

## 止める・戻す

| やりたいこと | 操作 |
|-------------|------|
| 切断する（ローカルのセッションは残す） | もう一度 `/remote-control` → 状態パネルから切断 |
| サーバーモードを止める | Ctrl+C |
| 止めたセッションに戻す | 同じフォルダで `claude remote-control --continue`（**停止後およそ4時間**まで） |
| 全セッションで自動接続にする | `claude` の中で `/config` → **Enable Remote Control for all sessions** |
| 完全に禁止する | 設定の `disableRemoteControl` |

---

## サーバーPCで使うときの注意

サーバーPC（Docker が動いているPC）で有効にすれば、外出先から
[サーバー運用ガイド](server_operations.md) の作業（ログ確認・コンテナ再起動・手動デプロイ）を
スマホ越しにできます。

> [!WARNING]
> **本番DBを触れるPCに、AI の実行環境を開くことになります。**
> - 権限モードは**既定（都度承認）のまま**にして、承認はスマホから返す
> - `--dangerously-skip-permissions` の類は使わない
> - **常時有効（自動接続）にはしない。** 使うときだけ `/remote-control` で繋ぎ、終わったら切る
> - 復元（`docs/server_operations.md` 3章）のような、間違えると戻せない作業は遠隔でやらない

`git push` で最大2分後に自動反映される仕組みは既にあるので、
**ふだんのリリースにサーバーPCの遠隔操作は不要**です。障害対応のための手段と考えてください。

---

## つながらないとき

| 症状 | 原因 | 対処 |
|------|------|------|
| `claude remote-control` がすぐ終わる | ログインしていない／APIキー認証 | `/login` で claude.ai アカウントにサインイン |
| `Remote Control may not be available for this organization` | 組織で無効 | Owner に管理設定で有効化してもらう |
| 有効にならない・表示が出ない | `ANTHROPIC_BASE_URL` や `DISABLE_TELEMETRY` 等が設定されている | その環境変数を外す（シェル・`settings.json` の両方を確認） |
| 毎回信頼ダイアログが出る | ホームディレクトリで起動している | プロジェクトのフォルダで起動する |
| 接続が切れた | 通信の切断 | `/remote-control` で再接続 |
| `Another connection took over this session` | 別の端末が同じセッションを持った | 取り戻したいときだけ `/remote-control` |

---

## 仕組み・安全性

- PCからは**外向きのHTTPS通信だけ**で、**受信ポートは開きません**（ポート開放・固定IPは不要）
- コードの実行とファイルアクセスは**PC上に留まります**。スマホは画面と入力だけ
- 接続中は、会話の記録（指示・応答・ツールの実行）が Anthropic のサーバーに保存されます。
  端末間で会話を同期し、通信が切れても復帰するためです

公式資料: <https://code.claude.com/docs/en/remote-control>

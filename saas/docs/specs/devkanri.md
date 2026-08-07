# 開発管理（devkanri）仕様書

バージョン: 1.0
作成日: 2026-08-02
ステータス: ドラフト

---

## 1. 概要

社内システムの開発タスクを管理するアプリ。Developer 権限を持つ社員のみがアクセスできる。
Discord 連携によるタスク通知・操作、GitHub 連携による PR/Issue の紐づけを行う。

### 1.1 アクセス制限

- **社員番号が `G` で始まる（Developer）** のみアクセス可能
- 社長（`Y`）もアクセス可能
- それ以外の社員にはサイドバーにも表示しない

### 1.2 対象ユーザー

| ロール | できること |
|---|---|
| **Developer** | プロジェクト・タスクの全操作、Discord通知受信 |
| **社長** | 全プロジェクトの閲覧・進捗確認 |

---

## 2. 既存機能（維持）

### 2.1 プロジェクト管理

- プロジェクトの作成・編集・削除
- ステータス: 計画中 / 進行中 / 完了 / 中断
- 責任者の割り当て
- 開始日・期限の設定

### 2.2 タスク管理

- カンバンボード（未着手 / 作業中 / レビュー / 完了）
- タスク一覧（フィルタ付き）
- 優先度: 緊急 / 高 / 中 / 低
- カテゴリ: 機能追加 / バグ修正 / リファクタ / ドキュメント / テスト / インフラ / その他
- 担当者の割り当て
- 見積時間・実績時間
- コメント機能

### 2.3 ダッシュボード

- KPI（総タスク / 完了 / 作業中 / 未着手 / 未解決バグ）
- ステータス分布グラフ
- カテゴリ別タスク数
- 担当者別進捗
- 期限切れタスク警告

---

## 3. 追加機能

### 3.1 Discord 連携の強化

#### 3.1.1 通知（Bot → Developer）

現在の通知（タスク割当・ステータス変更）に加えて：

| イベント | 通知内容 | タイミング |
|---|---|---|
| タスク割当 | 「@ユーザー タスク #123 が割り当てられました」 | 即時 |
| ステータス変更 | 「タスク #123 が 作業中 → レビュー に変更されました」 | 即時 |
| **期限アラート** | 「⚠️ タスク #123 の期限が明日です」 | 毎朝9時 |
| **期限超過** | 「🔴 タスク #123 が期限を過ぎています（2日超過）」 | 毎朝9時 |
| **コメント追加** | 「💬 タスク #123 に佐藤さんがコメントしました」 | 即時 |
| **プロジェクト進捗** | 「📊 プロジェクトX: 12/20タスク完了（60%）」 | 毎週月曜9時 |

#### 3.1.2 Discordからのタスク操作（コマンド）

Discordのスラッシュコマンド or メッセージコマンドで操作：

| コマンド | 動作 |
|---|---|
| `/task list` | 自分の未完了タスク一覧を表示 |
| `/task show 123` | タスク #123 の詳細を表示 |
| `/task done 123` | タスク #123 を完了にする |
| `/task start 123` | タスク #123 を作業中にする |
| `/task comment 123 テキスト` | タスク #123 にコメントを追加 |
| `/task create プロジェクト名 タスク名` | 新しいタスクを作成 |

#### 3.1.3 実装方式

- **通知:** プロジェクトごとの Discord Webhook URL を使用（既存）
- **コマンド操作:** Discord Bot を別プロセスで稼働させ、Django API を呼び出す
- Discord Bot は `discord.py` ライブラリで実装
- Bot → Django API は内部認証トークンで保護

### 3.2 GitHub 連携

#### 3.2.1 PR/Issue の紐づけ

| 機能 | 説明 |
|---|---|
| タスクに GitHub Issue URL を記録 | タスク詳細画面に Issue へのリンクを表示 |
| タスクに GitHub PR URL を記録 | タスク詳細画面に PR へのリンクを表示 |
| PR マージ時に自動でタスクを完了 | GitHub Webhook で PR merge イベントを受信 |

#### 3.2.2 タスク詳細画面への表示

```
┌─────────────────────────────────────────┐
│ #123 ログイン画面のバグ修正              │
│ [作業中] [優先度: 高] [バグ修正]         │
├─────────────────────────────────────────┤
│                                         │
│  GitHub:                                │
│   Issue: mstk13/KEM_DDENKI#45 ← リンク  │
│   PR:    mstk13/KEM_DDENKI#52 ← リンク  │
│                                         │
│  ...                                    │
└─────────────────────────────────────────┘
```

#### 3.2.3 実装方式

- タスクモデルに `github_issue_url`, `github_pr_url` フィールドを追加
- GitHub Webhook エンドポイント `/dev/github-webhook/` を作成
- PR の description に `closes #123` があればタスク #123 を完了にする

### 3.3 アクセス制限の実装

#### 3.3.1 サイドバーの制御

```html
{% if is_developer %}
<a href="{% url 'devkanri:project_list' %}">開発管理</a>
{% endif %}
```

#### 3.3.2 ビューの制御

```python
def _is_developer(user):
    """Developer権限を持つかどうか。"""
    if user.is_superuser:
        return True
    profile = getattr(user, "worker_profile", None)
    if not profile:
        return False
    return (profile.employee_code or "").startswith("G")
```

全ビューに `@developer_required` デコレータを適用。

---

## 4. 画面の変更点

### 4.1 タスク詳細画面

既存の画面に以下を追加：

- GitHub Issue URL 入力欄
- GitHub PR URL 入力欄
- リンクはクリックで GitHub に遷移

### 4.2 タスク編集フォーム

- `github_issue_url` フィールド追加
- `github_pr_url` フィールド追加

### 4.3 プロジェクト設定

- Discord Webhook URL（既存）
- GitHub リポジトリ URL（新規）

---

## 5. データモデルの変更

### 5.1 DevTask に追加

| フィールド | 型 | 説明 |
|---|---|---|
| github_issue_url | URLField(blank) | GitHub Issue URL |
| github_pr_url | URLField(blank) | GitHub PR URL |

### 5.2 DevProject に追加

| フィールド | 型 | 説明 |
|---|---|---|
| github_repo_url | URLField(blank) | GitHub リポジトリ URL |

---

## 6. 技術メモ

### 6.1 Discord Bot

- `discord.py` ライブラリで実装
- Docker で別コンテナとして稼働
- Django REST API を呼び出してタスク操作
- 環境変数: `DISCORD_BOT_TOKEN`

### 6.2 GitHub Webhook

- `/dev/github-webhook/` でイベント受信
- `X-Hub-Signature-256` ヘッダーで署名検証
- 環境変数: `GITHUB_WEBHOOK_SECRET`
- 対応イベント: `pull_request` (merged)

### 6.3 定期実行（期限アラート）

- Django management command: `python manage.py send_deadline_alerts`
- cron or Celery beat で毎朝9時に実行
- Docker の場合は entrypoint で cron を設定

---

## 7. 実装フェーズ

### Phase 1: アクセス制限

- [ ] `_is_developer` 判定関数
- [ ] `@developer_required` デコレータ
- [ ] サイドバーの条件分岐（Developer のみ表示）
- [ ] 非 Developer がアクセスした場合は 404

### Phase 2: Discord 通知の強化

- [ ] 期限アラート通知（毎朝9時）
- [ ] 期限超過通知
- [ ] コメント追加通知
- [ ] 週次プロジェクト進捗通知
- [ ] management command: `send_deadline_alerts`

### Phase 3: Discord コマンド操作

- [ ] Discord Bot の実装（`discord.py`）
- [ ] Django API エンドポイント（タスク一覧/詳細/更新/コメント）
- [ ] Bot 用認証トークン
- [ ] Docker コンテナ追加

### Phase 4: GitHub 連携

- [ ] DevTask に `github_issue_url`, `github_pr_url` 追加
- [ ] DevProject に `github_repo_url` 追加
- [ ] タスク詳細画面に GitHub リンク表示
- [ ] GitHub Webhook エンドポイント
- [ ] PR マージ時のタスク自動完了

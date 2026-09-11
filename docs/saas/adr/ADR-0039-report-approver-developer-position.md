# ADR-0039: 日報を承認できる IT 担当を役職「Developer」でも判定する

## ステータス

採用（2026-09-11）

## コンテキスト

ADR-0007 で「日報の承認は社長と IT のみ」と決め、IT 担当は `developer` **ロール**で判定していた
（`apps.permissions.services.can_approve_report()`）。

一方 ADR-0022 の調査どおり、本番の権限ロール（`Role` / `UserRole`）は **0件** で、
IT 担当（G001〜G003）は作業員の **役職「Developer」** でしか見分けられない。
そのため本番では IT 担当に承認ボタンが出ず、承認しようとすると
「日報を承認できるのは社長とITのみです」と断られていた。

プロダクトオーナーから「Developer で入っているが承認ボタンが無い」と報告があった（2026-09-11）。

## 決定

`can_approve_report()` の IT 担当の判定に、役職名「Developer」を加える。

| 承認できる | 判定 |
|---|---|
| 社長 | superuser・`president` ロール・役職「社長」（`is_president`、変更なし） |
| IT 担当 | `developer` ロール（変更なし）**または役職「Developer」（追加）** |

- 役職名は `REPORT_APPROVER_POSITIONS = ("Developer",)` に置き、完全一致で見る
  （人事評価の `POSITION_RESTRICTED_APPS`（ADR-0022）と同じ書き方）
- 役員など他の役職は、これまでどおり承認できない

## 捨てた選択肢

- **本番に developer ロールを投入する**: 管理者アカウントで3人に付与すれば今のコードのままでも通るが、
  役職と二重管理になり、役職を変えたときに外し忘れる。役職で判定している他の機能（ADR-0022）ともずれる
- **機能別の利用者リスト（AppAccess の can_approve、ADR-0030）に切り替える**: 承認者を増やす方針（D3）の本命だが、
  初期データ（誰を承認者にするか、D2）が決まっていない。今回は「社長と IT」という既存の決まりを本番で効かせる修正に留める

## 影響

- 変更: `apps/permissions/services.py`（`can_approve_report` と `REPORT_APPROVER_POSITIONS`）
- 追加テスト: `tests/test_genba_memo_changes.py`（役職 Developer は承認できる／他の役職はできない／一覧に承認ボタンが出て承認できる）
- 本番で承認できる人が増える: 役職「Developer」の作業員に紐づくユーザー（ADR-0022 時点で3人）
- モデル変更・マイグレーションなし

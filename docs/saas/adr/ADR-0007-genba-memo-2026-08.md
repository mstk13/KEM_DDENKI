# ADR-0007: 現場ヒアリングメモ（2026-08）反映時の設計判断

## ステータス

承認

## コンテキスト

現場での手書きヒアリングメモをもとに、developer 版へ改善を反映した。
複数の要望が「既存の似た仕組みのどちらに載せるか」「誰に許すか」の
判断を伴ったため、後から辿れるよう記録する。

## 決定

### 1. 工程の手入力は `sites.Process` に載せる

工程を表すモデルは `sites.Process`（現場詳細の工程表）と
`schedules.Phase`（工期管理のガント）の2系統がある。
AI工程提案（`ai:schedule_suggestion`）は `sites.Process` の実績を
学習元にしているため、「AI提案だけでなく自分でも入力したい」という
要望に対しては `sites.Process` の CRUD を追加した。
`schedules.Phase` は従来どおり工期管理側で扱う。

### 2. 日報の承認は社長と IT のみ

承認は `CostTransaction`（労務費）を生成する不可逆に近い操作のため、
権限を絞る。判定は `apps.permissions.services.can_approve_report()` に
集約し、以下を承認可能とする。

- superuser
- `president` ロール、または Worker の役職名が「社長」
- `developer` ロール（社内での IT 担当）

IT 専用ロールは新設せず、既存の `developer` ロールを IT 担当として扱う。
ロールを増やすと権限マトリクス画面の運用が複雑になるため。

### 3. 権限エラーは `PermissionDenied` に統一する

`HttpResponseForbidden` に HTML 断片を直接書く実装が3か所にあり、
レイアウトのない素のページが表示されて「画面がこわれている」と
受け取られていた。Django 標準の `PermissionDenied` を送出し、
`templates/403.html`（base.html 継承）で表示する形に統一した。

### 4. 日報の種別は固定 choices にする

種別（管理／事務／電工／IT）は職種マスタ（`workers.JobTitle`）とは
別軸の分類で、テナントごとに増減する想定がないため
`DailyReport.ReportType` の TextChoices とした。

### 5. コンテンツ幅の上限を外す

`.content` の `max-width: 1200px` により、ワイドモニタで右側に
大きな余白が出ていた。上限を外し、幅を絞りたい画面のみ
`.content-narrow` を付ける方式に変えた。

## 影響

- マイグレーション: `sites.0002`（estimator 追加）、
  `reports.0005`（report_type 追加）。いずれも null 許容/デフォルト付きの
  加算のみで、expand/contract の expand フェーズに相当する。
- AI機能は `ANTHROPIC_API_KEY` が未設定だと実行できない。
  未設定時は画面に理由を表示し、実行ボタンを無効化する
  （`llm_advisor.check_availability()`）。

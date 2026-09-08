# ADR-0018: 日報の削除を本人と管理者に許す

## ステータス

承認

## コンテキスト

日報管理には編集はあるが削除がなく、誤って作った日報（現場や日付の間違い、
二重入力）を消す手段がなかった。現場から「自分の日報は自分で消したい」、
管理側から「他の人の分も整理したい」という要望が出た。

## 決定

### 1. 削除できるのは「本人」と「日報を管理する立場の人」

判定は `apps.permissions.services.can_delete_report(user, report)` に集約する。

- **本人**（`is_own_report`）: 入力者（`created_by`）が本人、または日報の作業員が
  本人の Worker。事務員が代理入力した自分の日報も本人が消せるよう、両方を見る。
- **管理する立場**（`can_manage_reports`）: 承認できる人（社長・IT = `can_approve_report`）
  に加え、日報モジュールの `admin` 権限を持つロール。既定ロールでは `president` のみ
  だが、権限マトリクス画面で他ロールにも付与できる。

`site_manager` や `office_staff` は `write` 権限止まりなので、他人の日報は消せない。
代理入力は「入力者」として本人扱いになるため、自分で入れた分は消せる。

### 2. 承認済の日報は誰も削除できない

承認時に `CostTransaction`（労務費）を `source_id` で紐づけて計上しており、
FK ではないため日報を消しても労務費は残る。整合が崩れるのを防ぐため、
承認済は管理者でも削除不可とし、画面の削除ボタンも出さない。
承認済を消したい場合は、原価側の取消（`create_reversal`）と合わせて別途扱う。

### 3. 確認画面を挟む（GET → 確認、POST → 削除）

一覧は一括承認の `<form>` の中にあり、行ごとに削除 `<form>` を入れ子にできない。
JS の confirm に頼らず、`/reports/<pk>/delete/` を GET で確認画面、POST で削除とする。
勤怠日報（attendance）の削除と同じ流儀。

## 影響

- `reports:delete` URL と `templates/reports/delete_confirm.html` を追加
- 一覧と編集画面に、削除できる日報にだけ「削除」リンクを表示
- 越境・権限・承認済のテストを `tests/test_report_delete.py` に追加

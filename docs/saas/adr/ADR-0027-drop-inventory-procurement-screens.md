# ADR-0027: 在庫一覧・調達実績の画面を撤去する（データと自動記録は残す）

## ステータス

採用（2026-09-10）

## コンテキスト

システム再設計仕様書 v2.0 §5（決定③）は、材料の業務が「発注 + 納品検収」で
回っているため、在庫管理と調達を廃止し、画面と導線を撤去すると決めた
（データはアーカイブし削除しない — §12）。Phase 0-4「廃止機能の畳み込み」の一部。

撤去対象を調べた結果:

| 画面 | URL 名 | 導線 | データの出どころ |
|---|---|---|---|
| 在庫一覧 | `materials:inventory_list` | **どのテンプレート・ナビからもリンクされていない** | 検収時に `inspect_delivery()` が `Inventory` の数量を加算 |
| 調達実績の一覧 | `materials:procurement_list` | 手入力画面との相互リンクのみ | 検収時に `_create_procurement_records()` が自動作成 |
| 調達実績の手入力 | `materials:procurement_create` | 一覧からのみ | 手入力 |

どちらの画面にもテストはなく、ナビから到達できないため、利用者は URL を直打ちした人に限られる。

## 決定

1. 3つのビュー・URL・テンプレートと、手入力専用の `ProcurementRecordForm` を削除する
2. **モデル・テーブル・検収時の自動記録は残す**
   - `ProcurementRecord` の自動作成は `MaterialSupplier`（材料ごとの仕入先とリードタイム）の
     更新と同じ処理の中にあり、発注側の機能が依存している
   - `Inventory` の加算は検収処理の一部で、止めるとサービス層の計算内容が変わる
     （v2.0 §12「業務ロジックの計算内容を変えない」）
   - どちらも「画面が消えてもデータが溜まり続ける」状態になるが、将来の見積比較・
     取り込み基盤（v2.0 §6）の実績データとして使える余地があるため、止めるかどうかは別途判断する
3. 検収完了のメッセージ「在庫・原価を更新しました」から「在庫」を外す。
   利用者が確認できない在庫を更新したと伝えても意味がないため

## 捨てた選択肢

- **モデルごと削除する**: expand/contract（CLAUDE.md ルール7）に反し、v2.0 §12 の
  「データは削除しない」にも反する
- **URL を残して「廃止しました」ページへリダイレクトする**: ナビから到達できない画面なので、
  リダイレクト先を維持するコストに見合わない。404 で足りる

## 影響

- 削除: `apps/materials/views.py` の `inventory_list` / `procurement_list` / `procurement_create`
- 削除: `apps/materials/urls.py` の3パス、`apps/materials/forms.py` の `ProcurementRecordForm`
- 削除: `templates/materials/inventory_list.html` / `procurement_list.html` / `procurement_form.html`
- 変更: 検収完了メッセージの文言
- 残置: `Inventory` / `ProcurementRecord` モデル、admin、`inspect_delivery()` の自動記録、`seed_demo`
- マイグレーションなし

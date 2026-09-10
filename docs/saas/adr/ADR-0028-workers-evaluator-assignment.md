# ADR-0028: 評価者割当を workers 側に作業員 FK で持ち直す（expand）

## ステータス

採用（2026-09-10）

## コンテキスト

フロントエンド再設計仕様書 v1.1 決定①（v2.0 に継承）は、評価システムを
workers 側（人材評価）に一本化し、`apps/evaluation`（人事評価）から
「評価者割当（EvaluatorTarget）」だけを移植すると決めた。Phase 0-2 の最初の段階。

移植元を調べた結果:

| | `evaluation.EvaluatorTarget` |
|---|---|
| 持ち方 | `evaluator_name` / `target_name` の**名前テキストの組** |
| 使われ方 | 登録・削除の画面と admin だけ。**判定に読んでいるコードはない** |
| 問題 | 改姓・表記揺れ（全角/半角スペース等）で作業員と対応しなくなる |

移植先の workers 側の評価開始画面は、対象者を次の規則で出している（`workers/views.py`）。

- 役員・社長（職種名で判定）: 自分を含む在籍者全員
- それ以外: 自分を除く在籍者全員

割当で絞る仕組みはない。

## 決定

1. `workers.EvaluatorAssignment(TenantModel)` を追加する。
   `evaluator` / `target` はどちらも `Worker` への FK
2. `(company, evaluator, target)` を一意にする。旧モデルの `unique_together` と同じ意味
3. **`evaluator == target` は禁止しない**。役員・社長は自己評価を含めて評価する運用が
   既存コードにあるため
4. simple-history・admin 登録・越境テスト・マイグレーションを同じ PR に含める（CLAUDE.md ルール4）
5. **この PR では判定に使わない（expand のみ）**。評価開始画面の対象者は今までどおり

### 後続の段階

| 段階 | 内容 | 前提 |
|---|---|---|
| 切り替え | 対象者を返すサービス関数を作り、評価開始画面と `eval_targets_api` から呼ぶ。割当の管理画面 | 要求定義 D4（割当0件の評価者の扱い） |
| データ移行 | `EvaluatorTarget` の名前を作業員名と突き合わせて FK に移す。一致しない件数を出す | 切り替えと同時か直前 |
| 閲覧専用化 | `apps/evaluation` の書き込み導線を閉じ、ナビを「人材評価」1項目に | 切り替え後 |

## 捨てた選択肢

- **EvaluatorTarget に FK 列を足して使い続ける**: evaluation アプリは読み取り専用アーカイブ →
  将来廃止と決まっている（v1.1 決定①）。廃止予定のアプリに新しい依存を作ることになる
- **割当と対象者の絞り込みを1つの PR で入れる**: 割当0件の評価者の扱い（D4）が
  決まらないまま入れると、本番で評価者が対象者を選べなくなるおそれがある

## 影響

- 追加: `apps/workers/models.py` の `EvaluatorAssignment`、履歴モデル、マイグレーション
- 追加: `apps/workers/admin.py` に admin 登録
- 追加: `tests/test_workers_evaluator_assignment.py`（越境・一意性・自己割当・履歴）
- 画面・判定・既存データへの影響なし

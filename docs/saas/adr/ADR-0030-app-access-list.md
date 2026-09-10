# ADR-0030: アクセス管理を機能別の利用者リスト（AppAccess）に一本化する（expand）

## ステータス

採用（2026-09-10）。ADR-0022（役職によるアプリ利用制限）は、判定を切り替える PR で置き換える

## コンテキスト

フロントエンド再設計仕様書 v2.0 §4 は、アクセス管理を「機能ごとの使える人リスト」
1本にまとめると決めた。要求定義 4.1（Phase 0-1）の最初の段階にあたる。

今は「誰が何を使えるか」を決める仕組みが4つ並存し、どれも一部しか効いていない。

| 仕組み | 実装 | 状態 |
|---|---|---|
| RBAC | `Role` / `UserRole` / `ModulePermission` | 本番0件。`setup_default_roles()` は一度も呼ばれていない |
| 役職による制限 | `POSITION_RESTRICTED_APPS` / `can_use_app`（ADR-0022） | 人事評価だけ |
| 個別のアプリ許可 | `Worker.allowed_apps` + `AppPermissionMiddleware._PATH_TO_APP` | 全員が空リスト＝無制限 |
| 原価の特例 | `costs.CostAccessGrant` + 社員番号 G 始まり（`_has_cost_access`） | 原価ビューのみ |

アプリキーの語彙も4か所でずれている。

| 定義 | キーの例 | 無いもの |
|---|---|---|
| `ModulePermission.MODULE_CHOICES` | reports, costs, devkanri, settings … 10件 | sites, sales, 評価系 |
| `core.middleware._PATH_TO_APP` | sites, sales, hr_evaluation … 13件 | attendance, estimation, ai, audit-log |
| `workers.forms.APP_PERMISSION_CHOICES` | evaluations, hr_evaluation … 11件 | sales, notifications, settings |
| `tenants.CompanyApp.APP_CODES` | jinzai, nippou, genka … 6件 | ローマ字の別語彙 |

## 決定

**D1（2026-09-10 決定）: 機能別の利用者リストにする。** 役職ベース・ロールベースは採らない。

1. `apps/permissions/app_registry.py` にアプリキーの一覧を1つだけ置く。
   各機能は `key` / 表示名 / URL の前置き / 承認リストの有無（`approvable`）を持つ
   - 既存のキー（`hr_evaluation` / `evaluations` / `devkanri` など）は名前を変えない
   - ミドルウェアに無かった `/attendance/` `/estimation/` `/ai/` `/audit-log/` も含める
   - `approvable` は日報（`reports`）と原価（`costs`）だけ（v2.0 §4）
   - `app_key_for_path()` は今のミドルウェアの解決方法（`/workers/` 配下の
     `/evaluations/` の分岐を含む）に合わせる。書類アラートだけは workers から分ける
   - `ai` は `/ai/` 配下全体。現場・原価・工期の詳細から開く AI 予測・工程提案も
     ここに入るので、分けるかどうかは切り替えの PR で決める
2. `permissions.AppAccess(TenantModel)` を追加する。作業員 × アプリキー × `can_approve`。
   `(company, worker, app_key)` を一意にする
3. 判定は `has_app_access(user, app_key)` / `can_approve_app(user, app_key)` に集める
   - 未ログインは不可、superuser は可、作業員が紐づいていないユーザーは不可
   - 行は作業員の会社で明示的に絞る（ミドルウェアはテナントコンテキストの外で動くため
     `unscoped` を使う）。会社の食い違った行では開かない
   - `can_approve_app` は `can_approve=True` かつ `approvable` な機能のときだけ可。
     承認のない機能は superuser でも不可
   - 未登録のキーは `ValueError`。打ち間違いで黙って閉じたり開いたりしないため
4. simple-history・admin 登録・越境テスト・マイグレーションを同じ PR に含める（CLAUDE.md ルール4）
5. **この PR では判定に使わない（expand のみ）**。ミドルウェア・ナビ・原価ビュー・
   日報承認は今までどおり旧4つの仕組みで動く

### 後続の段階

| 段階 | 内容 | 前提 |
|---|---|---|
| データ移行 | 現状の実効権限を AppAccess に投入する。案は「全員全機能、人事評価は8人、原価は G 始まり + 付与者」 | 要求定義 D2（未決） |
| 切り替え | ミドルウェア・ナビ・原価ビュー・日報承認・人事評価の判定を `has_app_access` / `can_approve_app` へ。ADR-0022 をこの時点で置き換える | データ移行 |
| 管理画面 | 機能 × 社員のチェック表。「既存社員の設定をコピー」「全解除」 | 切り替え |
| contract | `ModulePermission`・`can_use_app`・`allowed_apps`・`CostAccessGrant`・G 始まり特例の判定コードを削除 → 次のリリースで旧テーブルを削除 | 切り替え後 |

## 捨てた選択肢

- **役職ベース（ADR-0022 を広げる）**: 役職 × 全機能の表になり、同じ役職の中で
  「この人だけ原価を見せる」ができない。結局 `CostAccessGrant` のような個別の特例が増える
- **ロールベース（既存の RBAC を使う）**: 本番0件で、ロールを設計して22人に付与する
  作業が先に要る。ロールと機能の対応を1段挟むぶん、管理画面で「この人が何を使えるか」が
  直接読めない（v2.0 §4 のチェック表の要件に合わない）
- **`Worker.allowed_apps` の JSON をそのまま使う**: 承認フラグを持てず、履歴・一意性・
  「この機能を使える人」の逆引きができない。仕様書どおり正規化したモデルに移す
- **レジストリ・モデル・判定の切り替えを1つの PR で入れる**: 移行データ（D2）が
  決まらないまま切り替えると、本番で誰かが締め出されるか開きすぎる（AC-5）

## 影響

- 追加: `apps/permissions/app_registry.py`（アプリキーの一覧と `get_app` / `APP_CHOICES` / `app_key_for_path`）
- 追加: `apps/permissions/models.py` の `AppAccess`、履歴モデル、マイグレーション
- 追加: `apps/permissions/admin.py` に admin 登録
- 追加: `apps/permissions/services.py` に `has_app_access` / `can_approve_app`
- 追加: `tests/test_app_access.py`（レジストリとミドルウェアの一致・越境・一意性・履歴・判定）
- 画面・判定・既存データへの影響なし

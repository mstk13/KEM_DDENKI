# ADR-0017: アプリの利用制限を役職（Position）で決める

## ステータス

採用（2026-09-08）

## コンテキスト

「社員の役職ごとに使えるアプリを変えたい。役員と Developer 以外は人事評価一覧を
見せたくない」という要望を受けた。実装できる場所を調べたところ、権限の仕組みが
**3つ並存していて、どれも役職を見ていない**ことが分かった。

| 仕組み | 実装 | 本番の状態 |
|---|---|---|
| RBAC | `apps/permissions` の Role / UserRole / ModulePermission | **0件**。`setup_default_roles()` は書かれているが一度も呼ばれていない |
| 個別のアプリ許可 | `Worker.allowed_apps` + `AppPermissionMiddleware` | 全22人が空リスト＝無制限 |
| ビュー内の場当たり判定 | `_is_president` / `_is_admin` / Django Groups | バラバラ |

一方 `Worker.position` は**全22人に入っている**（社長1 / 役員4 / Developer3 /
シニア5 / 正社員2 / ジュニア1 / 試用期間2 / パート1 / アルバイト2）。
役職を判定できる項目はこれだけである。

### 見つかった不具合

`AppPermissionMiddleware` の `_PATH_TO_APP` に `/evaluation/` が無く、
**人事評価アプリ全体が権限チェックを素通りしていた**。`allowed_apps` を設定しても
人事評価だけは止まらない。`/attendance/` `/estimation/` `/ai/` も同様に未登録。

## 決定

**`Worker.position.name` を軸にし、制限したいアプリだけを列挙する。**

```python
# apps/permissions/services.py
POSITION_RESTRICTED_APPS = {
    "hr_evaluation": ("社長", "役員", "Developer"),
}
```

判定は `can_use_app(user, app_code)` に集約し、次の2か所から同じ関数を呼ぶ。

1. `AppPermissionMiddleware` — URL を実際に止める
2. `{{ user|can_use:"..." }}` テンプレートフィルタ — サイドバーの出し分け

### RBAC を使わなかった理由

`Role` が本番に0件なので、`has_role()` は superuser 以外すべて False を返す。
これを判定に使うと**全員が締め出される**。ロールを投入してから移る道はあるが、
22人へのロール付与という運用作業が先に必要になり、今回の要望とは別の話になる。

### 「許可するアプリの表」ではなく「制限するアプリの一覧」にした理由

役職 × 全アプリ（約16領域）の表を先に作ると、未記入のマスに引っかかって
既存の画面が突然閉じる。今は誰も締め出されていない状態なので、
**閉じたい行を1行ずつ足す**ほうが、閉じた範囲がそのまま読めて事故が起きない。

### 社長を含めた理由

要望は「役員と Developer 以外」だったが、役員より上位の社長を締め出すのは
意図と違うと判断した。`is_president()` など既存の判定も社長を最上位に扱っている。
社員番号 Y 始まり（管理者）と superuser も、`AppPermissionMiddleware` が既に
素通しにしているので判定を揃えた。

### 人事評価アプリ全体を対象にした理由

一覧（`/evaluation/`）だけを塞いでも、同じアプリの「評価対象設定」
（`/evaluation/assignments/`）や `employee_summary` から中身が見える。
`/evaluation/` 配下をまとめて対象にした。

なお「人材評価」（`/workers/evaluations/`）は別機能なので対象外。
ミドルウェアは前者を `hr_evaluation`、後者を `evaluations` と別コードで扱う。

## 影響

- `apps/permissions/services.py` に `POSITION_RESTRICTED_APPS` / `get_position_name()` /
  `can_use_app()` を追加
- `apps/core/middleware.py` の `_PATH_TO_APP` に `/evaluation/` を追加し、
  `allowed_apps` の判定より先に役職判定を通す
- `apps/permissions/templatetags/permission_tags.py` に `can_use` フィルタを追加
- `templates/base.html` の人事評価3項目を `{% if user|can_use:"hr_evaluation" %}` で囲む
- `apps/workers/forms.py` の `APP_PERMISSION_CHOICES` に `hr_evaluation` を追加
- モデル変更なし。マイグレーション不要
- `tests/test_position_app_access.py`（21件）

### 本番で閉じる人／開く人

| | 人数 | 例 |
|---|---|---|
| 見られる | 8 | Y001 社長、S001・E003・E004・E006 役員、G001〜G003 Developer |
| 見られなくなる | 14 | シニア5、正社員2、ジュニア1、試用期間2、パート1、アルバイト2、役職未設定1 |

`evaluation.Evaluation` は本番で0件のため、閉じても失われる業務は無い。

## 積み残し

- `/attendance/` `/estimation/` `/ai/` `/audit-log/` も `_PATH_TO_APP` に無く、
  `allowed_apps` が効かない。今回の要望の範囲外なので触っていない
- サイドバーの権限による出し分けは人事評価の3項目のみ。他の約45リンクは
  全員に出たままで、`module_permission_required` が付いた15ビュー（costs 11 /
  settings 4）は**メニューに出るのに押すと403**になる
- 役職ではなく個人で例外を作りたくなった場合は `Worker.allowed_apps` を使う。
  ただし現在は「役職で不可なら allowed_apps でも開けられない」順序になっている

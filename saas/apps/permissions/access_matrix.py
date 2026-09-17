"""作業員 × 機能 のチェック表（ADR-0082）。

社長・管理者が「誰がどの機能を開けるか」を1枚の表で決める画面の中身。
表に付けた印は `AppAccess`（ADR-0030）に書く。1行あれば、その作業員は
その機能を使える。

## なぜ AppAccess を正にするか

今まで「誰がどの機能を開けるか」は `Worker.allowed_apps`（JSON の配列）で
決めていた。配列には次の弱点がある。

* **空が「制限なし」を意味する** ので、「何も使えない」を書き分けられない
* **履歴が残らない** ので、いつ誰が閉じたのかを後から辿れない
* **語彙が4か所に分かれている**（ADR-0030 の冒頭）

`AppAccess` は1行1マスで、simple-history が付いていて、語彙は
`app_registry` の1か所だけ。表の形にそのまま対応する。

## それでも allowed_apps を書き直す

入口で止めているのは今も `AppPermissionMiddleware` で、見ているのは
`allowed_apps` のほうである。`AppAccess` はまだ誰も読んでいない（expand の段階）。
表で印を外しても画面が開けるままでは、設定した意味がない。

そこで**この画面で直した作業員だけ** `allowed_apps` を書き直す。
触っていない作業員には一切書かない。1回の保存で全員の権限が動くと、
どこで何が変わったのか分からなくなる。

写せない機能が4つある（`UNMIRRORED_APPS`）。積算・勤怠・AI は URL に
入口の制限がまだ無く、書類アラートは `/workers/` 配下なので作業員管理と
アプリコードが重なる。印は `AppAccess` に残るが、入口はまだ変わらない。
ここを無理に写すと、書類アラートの印を外したせいで作業員管理ごと閉じる。
"""
from __future__ import annotations

from django.db import transaction

from apps.permissions.app_registry import APPS
from apps.permissions.models import AppAccess

# allowed_apps へ写せる機能と、その先の AppPermissionMiddleware のアプリコード
# （core.middleware._PATH_TO_APP が URL から決めるもの）。
MIRRORED_APPS: dict[str, str] = {
    "sites": "sites",
    "reports": "reports",
    "schedules": "schedules",
    "costs": "costs",
    "materials": "materials",
    "workers": "workers",
    "evaluations": "evaluations",
    "hr_evaluation": "hr_evaluation",
    "bids": "bids",
    "sales": "sales",
    "masters": "masters",
    "notifications": "notifications",
    "settings": "settings",
    "devkanri": "devkanri",
}

# 写せない機能。印は AppAccess に残るが、今は入口が変わらない。
#   estimation / attendance / ai … URL に入口の制限がまだ無い
#   document_alerts             … /workers/ 配下で、作業員管理とコードが重なる
UNMIRRORED_APPS: tuple[str, ...] = ("estimation", "attendance", "ai", "document_alerts")

# allowed_apps は空の配列が「制限なし」を表すため、「どの機能も使えない」を
# 空では書けない。どのアプリコードとも一致しない印を1つ入れて塞ぐ。
NO_APP_SENTINEL = "__none__"

_ALL_MIRRORED_CODES = set(MIRRORED_APPS.values())


def allowed_apps_for(app_keys) -> list[str]:
    """印の付いた機能から、`Worker.allowed_apps` に入れる配列を作る。"""
    codes = sorted({MIRRORED_APPS[key] for key in app_keys if key in MIRRORED_APPS})
    if set(codes) == _ALL_MIRRORED_CODES:
        # 写せる機能がすべて開いている＝制限なし。空の配列がその意味を持つ。
        return []
    return codes or [NO_APP_SENTINEL]


def active_workers(company):
    """表の行になる作業員。一覧・名簿と同じ社員番号順に並べる。"""
    from apps.workers.models import Worker, sort_workers_by_code

    # unscoped: 設定画面はログインユーザーの会社を明示して引く。
    return sort_workers_by_code(
        Worker.unscoped.filter(company=company, is_active=True).select_related("position"),
    )


def _rows_by_worker(company, workers) -> dict[int, dict[str, bool]]:
    """{作業員ID: {機能キー: 承認できるか}}。行が無い機能は入らない。"""
    result: dict[int, dict[str, bool]] = {worker.pk: {} for worker in workers}
    # unscoped: 同上。
    for row in AppAccess.unscoped.filter(company=company, worker__in=workers):
        result.setdefault(row.worker_id, {})[row.app_key] = row.can_approve
    return result


def ensure_seeded(company, user=None) -> int:
    """1行も無い会社に、今の実効権限をそのまま写した行を作る（ADR-0045）。

    白紙の表を出すと、全員がどの機能も使えない状態から付け直すことになり、
    保存した瞬間に全社が閉じる。最初の1回だけ今の状態を写す。

    Returns:
        作った行数。既に行があれば 0。
    """
    from apps.permissions.legacy_access import legacy_access_plan, sync_app_access

    # unscoped: 同上。
    if AppAccess.unscoped.filter(company=company).exists():
        return 0
    result = sync_app_access(company, legacy_access_plan(company), apply=True, user=user)
    return result.created


def build_matrix(company) -> dict:
    """画面に渡す表。行が作業員、列が機能。"""
    workers = active_workers(company)
    granted = _rows_by_worker(company, workers)
    apps = [
        {
            "key": app.key,
            "label": app.label,
            "approvable": app.approvable,
            "mirrored": app.key in MIRRORED_APPS,
        }
        for app in APPS
    ]

    rows = []
    for worker in workers:
        access = granted.get(worker.pk, {})
        rows.append({
            "worker": worker,
            "cells": [
                {
                    "app": app,
                    "checked": app["key"] in access,
                    "can_approve": access.get(app["key"], False),
                    "name": f"access_{worker.pk}_{app['key']}",
                    "approve_name": f"approve_{worker.pk}_{app['key']}",
                }
                for app in apps
            ],
        })

    return {
        "apps": apps,
        "rows": rows,
        "unmirrored_labels": [
            app["label"] for app in apps if not app["mirrored"]
        ],
    }


@transaction.atomic
def save_matrix(company, posted, user=None) -> int:
    """送られてきたチェックを AppAccess に書き、直した作業員の allowed_apps を写す。

    Returns:
        設定が変わった作業員の人数。
    """
    workers = active_workers(company)
    # unscoped: 同上。
    existing = {
        (row.worker_id, row.app_key): row
        for row in AppAccess.unscoped.filter(company=company, worker__in=workers)
    }

    changed = 0
    for worker in workers:
        checked_keys = set()
        worker_changed = False
        for app in APPS:
            checked = posted.get(f"access_{worker.pk}_{app.key}") == "on"
            # 承認は、承認のある機能（日報・原価）でだけ意味を持つ。
            approve = app.approvable and posted.get(f"approve_{worker.pk}_{app.key}") == "on"
            row = existing.get((worker.pk, app.key))
            if checked:
                checked_keys.add(app.key)
                if row is None:
                    AppAccess.unscoped.create(  # unscoped: company を明示指定
                        company=company,
                        worker=worker,
                        app_key=app.key,
                        can_approve=approve,
                        created_by=user,
                    )
                    worker_changed = True
                elif row.can_approve != approve:
                    row.can_approve = approve
                    row.save(update_fields=["can_approve", "updated_at"])
                    worker_changed = True
            elif row is not None:
                row.delete()
                worker_changed = True

        if worker_changed:
            changed += 1
            allowed = allowed_apps_for(checked_keys)
            if worker.allowed_apps != allowed:
                worker.allowed_apps = allowed
                worker.save(update_fields=["allowed_apps", "updated_at"])

    return changed


def accessible_app_labels(worker) -> list[str]:
    """その作業員が使える機能の名前。作業員の詳細・編集画面に出す。"""
    # unscoped: 作業員から辿るので会社は絞り込み済み。
    keys = set(
        AppAccess.unscoped.filter(company_id=worker.company_id, worker=worker)
        .values_list("app_key", flat=True),
    )
    return [app.label for app in APPS if app.key in keys]

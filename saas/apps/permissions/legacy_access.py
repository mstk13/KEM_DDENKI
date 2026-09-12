"""今の実効権限から、機能別の利用者リスト（AppAccess）の行を作る（ADR-0045）。

ADR-0030「後続の段階」のデータ移行にあたる。

D2（2026-09-12 決定）: 利用者リストに切り替えるときは、今の実効権限をそのまま再現する。

今「その機能に入れるか」は、次の2段を通れるかで決まっている。

  1. AppPermissionMiddleware … superuser と社員番号 Y 始まりは素通し。それ以外は
     役職による制限（can_use_app。今は人事評価だけ）と Worker.allowed_apps（空なら無制限）
  2. ビューの入口 … 原価（has_module_permission costs read）、設定・変更ログ
     （has_module_permission settings admin）、書類アラート（Y 始まり・superuser・事務員ロール）

日報の承認は can_approve_report で決まる。原価には今「承認」が無いので、承認フラグは立てない。

判定は既存の関数をそのまま呼ぶ（規則を写すと、いつか食い違うため）。
ログインユーザーが紐づいていない作業員は関数に渡すユーザーが無いので、作業員の項目
（役職・社員番号・allowed_apps）だけで同じ規則を評価する。ユーザーに付く権限
（ロール・原価の個別許可・User.employee_no）は持たないものとして扱う。

機能の中の一部の画面だけを絞っている判定（作業員の編集など）は、機能の入口ではないので対象外。
切り替えた後もビューの中に残る。
"""
from __future__ import annotations

from dataclasses import dataclass

from django.db import transaction

from apps.core.middleware import _PATH_TO_APP
from apps.permissions.app_registry import APPS
from apps.permissions.models import AppAccess
from apps.permissions.services import (
    POSITION_RESTRICTED_APPS,
    REPORT_APPROVER_POSITIONS,
    can_approve_report,
    can_use_app,
    has_module_permission,
    has_role,
)

# ビューの入口で、ミドルウェアとは別に機能ごと絞っている判定。値は has_module_permission の引数。
_MODULE_GATES = {
    # apps/costs/views.py
    "costs": ("costs", "read"),
    # 権限管理（/settings/permissions/）・変更ログ（/audit-log/）
    "settings": ("settings", "admin"),
}

# is_president が社長とみなす役職。ログインのない作業員の承認の判定に使う。
_PRESIDENT_POSITION = "社長"


def middleware_app_code(path: str) -> str | None:
    """AppPermissionMiddleware と同じ手順で、path をアプリコードに解決する。"""
    for prefix, code in _PATH_TO_APP.items():
        if path.startswith(prefix):
            if code == "workers" and "/evaluations/" in path:
                return "evaluations"
            return code
    return None


def _position_name(worker) -> str:
    return worker.position.name if worker.position_id else ""


def _is_y_admin(worker) -> bool:
    return bool(worker.employee_code and worker.employee_code.startswith("Y"))


def _passes_middleware(worker, user, path: str) -> bool:
    """AppPermissionMiddleware を通れるか。"""
    if (user is not None and user.is_superuser) or _is_y_admin(worker):
        return True
    code = middleware_app_code(path)
    if code is None:
        return True

    if user is not None:
        if not can_use_app(user, code):
            return False
    else:
        allowed_positions = POSITION_RESTRICTED_APPS.get(code)
        if allowed_positions is not None and _position_name(worker) not in allowed_positions:
            return False

    return not (worker.allowed_apps and code not in worker.allowed_apps)


def _passes_view_gate(worker, user, app_key: str) -> bool:
    """ビューの入口の判定を通れるか。"""
    gate = _MODULE_GATES.get(app_key)
    if gate is not None:
        return user is not None and has_module_permission(user, *gate)
    if app_key == "document_alerts":
        # workers.views.document_alert_dashboard と同じ: 社員番号 Y 始まり・superuser・事務員ロール
        if _is_y_admin(worker):
            return True
        return user is not None and (user.is_superuser or has_role(user, "office_staff"))
    return True


def _can_approve(worker, user, app_key: str) -> bool:
    if app_key != "reports":
        return False  # 原価には今「承認」が無い
    if user is not None:
        return can_approve_report(user)
    position = _position_name(worker)
    return position == _PRESIDENT_POSITION or position in REPORT_APPROVER_POSITIONS


def legacy_access_for_worker(worker) -> dict[str, bool]:
    """作業員が今の判定で使える機能と、その機能で承認できるか。

    Returns:
        {app_key: can_approve}。使えない機能は含まない。
    """
    user = worker.user
    access = {}
    for app in APPS:
        usable = all(
            _passes_middleware(worker, user, prefix) for prefix in app.path_prefixes
        ) and _passes_view_gate(worker, user, app.key)
        if usable:
            access[app.key] = app.approvable and _can_approve(worker, user, app.key)
    return access


def legacy_access_plan(company) -> list[tuple[object, dict[str, bool]]]:
    """会社の在籍中の作業員それぞれについて、今の判定で使える機能を返す（社員番号順）。"""
    from apps.workers.models import Worker, sort_workers_by_code

    # unscoped: 管理コマンドからテナントコンテキストの外で呼ぶため、company で明示的に絞る。
    workers = sort_workers_by_code(
        Worker.unscoped.filter(company=company, is_active=True).select_related("user", "position"),
    )
    return [(worker, legacy_access_for_worker(worker)) for worker in workers]


@dataclass
class SyncResult:
    created: int = 0
    updated: int = 0
    deleted: int = 0


def sync_app_access(company, plan, *, apply: bool, user=None) -> SyncResult:
    """AppAccess を plan と同じ状態にする。apply=False なら件数を数えるだけで書き込まない。

    足りない行を作り、承認フラグを合わせ、plan に無い行（退職者の行を含む）を消す。
    切り替え前に使う。切り替え後に流すと、画面で直した利用者リストを今の判定で上書きする。
    """
    wanted = {
        (worker.pk, key): can_approve
        for worker, access in plan
        for key, can_approve in access.items()
    }
    result = SyncResult()
    with transaction.atomic():
        # unscoped: legacy_access_plan と同じ理由。
        existing = {
            (row.worker_id, row.app_key): row
            for row in AppAccess.unscoped.filter(company=company)
        }
        for (worker_id, key), can_approve in wanted.items():
            row = existing.pop((worker_id, key), None)
            if row is None:
                result.created += 1
                if apply:
                    AppAccess.unscoped.create(
                        company=company, worker_id=worker_id, app_key=key,
                        can_approve=can_approve, created_by=user,
                    )
            elif row.can_approve != can_approve:
                result.updated += 1
                if apply:
                    row.can_approve = can_approve
                    row.save(update_fields=["can_approve", "updated_at"])
        for row in existing.values():
            result.deleted += 1
            if apply:
                row.delete()
    return result

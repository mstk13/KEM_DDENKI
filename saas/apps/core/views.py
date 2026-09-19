import datetime

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attendance.plans import parse_date
from apps.core.json_utils import json_for_script
from apps.permissions.decorators import settings_admin_required
from apps.permissions.services import has_module_permission
from apps.reports.models import DailyReport
from apps.schedules.services import (
    clip_gantt_tasks_to_today,
    get_active_sites_with_week_schedule,
    get_comparison_gantt_data,
)
from apps.sites.models import Site
from apps.workers.models import Worker

# ホームに並べる施工中の現場の上限。超えた分は現場一覧へ誘導する。
HOME_SITE_LIMIT = 10


@login_required
def dashboard(request):
    """ホーム（ADR-0032, ADR-0036）。

    施工中の現場と今週の工程（現場ごとにその日の参加者＝配置と出社予定）、
    工期管理と同じガントチャートを置く。

    GET パラメータ:
        date … 現場カードの参加者を見る日（YYYY-MM-DD）。省略・不正なら今日。
               今週の工程は date に関係なく今日を含む週のまま
    """
    company = request.user.company
    # USE_TZ=True なので now().date() だと UTC の日付になり、日本時間の
    # 0〜9時に前日扱いになる。現地の日付で揃える。
    today = timezone.localdate()
    members_date = parse_date(request.GET.get("date", ""))
    active_sites = Site.objects.filter(status=Site.Status.IN_PROGRESS).count()

    # 受注金額は原価と同じ扱い。現場詳細と同じ判定を通し、権限が無ければ
    # テンプレートで隠すだけでなくコンテキストにも載せない。
    can_view_costs = has_module_permission(request.user, "costs", "read")
    week = get_active_sites_with_week_schedule(
        company,
        today,
        limit=HOME_SITE_LIMIT,
        include_amounts=can_view_costs,
        members_date=members_date,
    )
    # 工期管理（schedules:list）を条件なしで開いたときと同じ中身。
    gantt = get_comparison_gantt_data(company)
    # ガントは当日から先だけを出す（ADR-0072）
    gantt_tasks = clip_gantt_tasks_to_today(gantt["tasks"], today)

    context = {
        "active_sites": active_sites,
        "today_reports": DailyReport.objects.filter(report_date=today).count(),
        "pending_reports": DailyReport.objects.filter(
            status=DailyReport.Status.SUBMITTED
        ).count(),
        "active_workers": Worker.objects.filter(is_active=True).count(),
        "can_view_costs": can_view_costs,
        "week_start": week["week_start"],
        "week_end": week["week_end"],
        "site_schedules": week["sites"],
        "more_sites": max(active_sites - len(week["sites"]), 0),
        "gantt_json": json_for_script(gantt_tasks),
        "gantt_tasks_exist": len(gantt_tasks) > 0,
        "members_date": members_date,
        "members_is_today": members_date == today,
        "members_prev_date": members_date - datetime.timedelta(days=1),
        "members_next_date": members_date + datetime.timedelta(days=1),
        "unmatched_plans": week["unmatched_plans"],
    }
    return render(request, "dashboard.html", context)


@login_required
@settings_admin_required
def audit_log(request):
    """全データの変更ログを閲覧する。simple_historyの全Historicalモデルを横断検索。"""
    # 検索パラメータ
    model_filter = request.GET.get("model", "")
    user_filter = request.GET.get("user", "")
    page = int(request.GET.get("page", 1))
    per_page = 50

    # Historical モデル一覧を取得
    historical_models = {}
    for model in apps.get_models():
        if model.__name__.startswith("Historical") and hasattr(model, "history_date"):
            label = model._meta.label.split(".")[-1].replace("Historical", "")
            historical_models[model._meta.label] = {
                "model": model,
                "display": label,
            }

    # 対象モデルの履歴を取得
    records = []
    if model_filter and model_filter in historical_models:
        # 特定モデルのみ
        target_models = {model_filter: historical_models[model_filter]}
    else:
        target_models = historical_models

    for info in target_models.values():
        qs = info["model"].objects.all()

        # テナント分離: company フィールドがある場合
        if hasattr(info["model"], "company_id"):
            qs = qs.filter(company=request.user.company)

        if user_filter:
            qs = qs.filter(history_user__username__icontains=user_filter)

        for rec in qs.order_by("-history_date")[:200]:
            records.append({
                "model_name": info["display"],
                "history_date": rec.history_date,
                "history_type": rec.get_history_type_display(),
                "history_user": getattr(rec, "history_user", None),
                "object_id": rec.pk,
                "object_str": str(rec),
            })

    # 日付順ソート
    records.sort(key=lambda x: x["history_date"], reverse=True)

    # ページネーション
    total = len(records)
    start = (page - 1) * per_page
    page_records = records[start:start + per_page]
    total_pages = (total + per_page - 1) // per_page

    model_choices = sorted(
        [(k, v["display"]) for k, v in historical_models.items()],
        key=lambda x: x[1],
    )

    return render(request, "core/audit_log.html", {
        "records": page_records,
        "model_choices": model_choices,
        "model_filter": model_filter,
        "user_filter": user_filter,
        "page": page,
        "total_pages": total_pages,
        "total": total,
    })


@login_required
@require_POST
def bulk_delete(request):
    """一覧で選んだものをまとめて消す（ADR-0098）。

    消せる対象は apps/core/bulk_delete.py の DELETABLE に書いた分だけ。
    会社で絞ったマネージャで引くので、他社の行は選んでも消えない。
    """
    from django.contrib import messages
    from django.db.models import ProtectedError
    from django.shortcuts import redirect
    from django.utils.http import url_has_allowed_host_and_scheme

    from apps.core.bulk_delete import DELETABLE

    spec = DELETABLE.get(request.POST.get("key", ""))
    back = request.POST.get("next", "")
    if not (back and url_has_allowed_host_and_scheme(
        back, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    )):
        back = ""

    if spec is None:
        messages.error(request, "この画面ではまとめて削除できません。")
        return redirect(back or "dashboard")

    # 画面によっては元から別名のチェックボックスがある（日報の一括承認など）
    raw = request.POST.getlist("ids") or request.POST.getlist("report_ids")
    ids = [pk for pk in raw if pk.isdigit()]
    if not ids:
        messages.warning(request, "削除するものが選ばれていません。")
        return redirect(back or spec.redirect)

    deleted, skipped, protected = 0, [], []
    for obj in spec.model().objects.filter(pk__in=ids):
        name = spec.name_of(obj)
        if spec.can_delete and not spec.can_delete(request.user, obj):
            skipped.append(name)
            continue
        try:
            obj.delete()
        except ProtectedError:
            protected.append(name)
            continue
        deleted += 1

    if deleted:
        messages.success(request, f"{spec.label}を {deleted} 件削除しました。")
    if skipped:
        messages.warning(
            request, "削除できないため残しました: " + "、".join(skipped[:10]),
        )
    if protected:
        messages.warning(
            request,
            "ほかから使われているため削除できませんでした: " + "、".join(protected[:10]),
        )
    return redirect(back or spec.redirect)

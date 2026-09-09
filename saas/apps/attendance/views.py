import datetime
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attendance.forms import (
    AttendEntryFormSet,
    AttendReportForm,
    AttendSettingsForm,
)
from apps.attendance.models import (
    AttendEntry,
    AttendPlan,
    AttendReport,
    AttendSettings,
)
from apps.attendance.plans import (
    FILL_TARGET_DATES,
    FILL_TARGETS,
    build_day_sheet,
    build_day_timeline,
    build_plan_board,
    fill_days,
    parse_clock,
    parse_date,
    parse_month,
)
from apps.attendance.utils import calc_attendance
from apps.core.json_utils import json_for_script
from apps.workers.models import Worker


@login_required
def report_list(request):
    qs = AttendReport.objects.order_by("-report_date")

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    site = request.GET.get("site", "").strip()
    status = request.GET.get("status", "").strip()

    if date_from:
        qs = qs.filter(report_date__gte=date_from)
    if date_to:
        qs = qs.filter(report_date__lte=date_to)
    if site:
        qs = qs.filter(site_name__icontains=site)
    if status:
        qs = qs.filter(status=status)

    return render(request, "attendance/report_list.html", {
        "reports": qs,
        "date_from": date_from,
        "date_to": date_to,
        "site": site,
        "status": status,
        "status_choices": AttendReport.Status.choices,
    })


@login_required
def report_create(request):
    settings_dict = AttendSettings.get_settings_dict(request.user.company)
    if request.method == "POST":
        form = AttendReportForm(request.POST)
        formset = AttendEntryFormSet(request.POST, prefix="entries")
        if form.is_valid() and formset.is_valid():
            report = form.save(commit=False)
            report.company = request.user.company
            report.created_by = request.user
            report.save()
            entries = formset.save(commit=False)
            for entry in entries:
                entry.report = report
                entry.company = request.user.company
                entry.created_by = request.user
                # 時間計算
                result = calc_attendance(
                    entry.start_time, entry.end_time,
                    entry.break_minutes, settings_dict,
                )
                entry.early_minutes = result["early"]
                entry.normal_minutes = result["normal"]
                entry.overtime_minutes = result["overtime"]
                entry.total_minutes = result["total"]
                entry.save()
            messages.success(request, "勤怠日報を登録しました。")
            return redirect("attendance:report_detail", pk=report.pk)
    else:
        form = AttendReportForm(initial={"report_date": datetime.date.today()})
        formset = AttendEntryFormSet(prefix="entries")
    return render(request, "attendance/report_form.html", {
        "form": form,
        "formset": formset,
        "is_edit": False,
    })


@login_required
def report_detail(request, pk):
    report = get_object_or_404(AttendReport, pk=pk)
    entries = report.entries.all()
    return render(request, "attendance/report_detail.html", {
        "report": report,
        "entries": entries,
    })


@login_required
def report_edit(request, pk):
    report = get_object_or_404(AttendReport, pk=pk)
    settings_dict = AttendSettings.get_settings_dict(request.user.company)
    if request.method == "POST":
        form = AttendReportForm(request.POST, instance=report)
        formset = AttendEntryFormSet(request.POST, prefix="entries", instance=report)
        if form.is_valid() and formset.is_valid():
            form.save()
            entries = formset.save(commit=False)
            for entry in entries:
                entry.report = report
                entry.company = request.user.company
                if not entry.pk:
                    entry.created_by = request.user
                result = calc_attendance(
                    entry.start_time, entry.end_time,
                    entry.break_minutes, settings_dict,
                )
                entry.early_minutes = result["early"]
                entry.normal_minutes = result["normal"]
                entry.overtime_minutes = result["overtime"]
                entry.total_minutes = result["total"]
                entry.save()
            for entry in formset.deleted_objects:
                entry.delete()
            messages.success(request, "勤怠日報を更新しました。")
            return redirect("attendance:report_detail", pk=report.pk)
    else:
        form = AttendReportForm(instance=report)
        formset = AttendEntryFormSet(prefix="entries", instance=report)
    return render(request, "attendance/report_form.html", {
        "form": form,
        "formset": formset,
        "is_edit": True,
    })


@login_required
def report_delete(request, pk):
    report = get_object_or_404(AttendReport, pk=pk)
    if request.method == "POST":
        report.delete()
        messages.success(request, "勤怠日報を削除しました。")
        return redirect("attendance:report_list")
    return render(request, "attendance/report_detail.html", {
        "report": report,
        "entries": report.entries.all(),
        "confirm_delete": True,
    })


@login_required
def entry_list(request):
    qs = AttendEntry.objects.select_related("report").order_by("-report__report_date")

    date_from = request.GET.get("date_from", "").strip()
    date_to = request.GET.get("date_to", "").strip()
    name = request.GET.get("name", "").strip()
    site = request.GET.get("site", "").strip()

    if date_from:
        qs = qs.filter(report__report_date__gte=date_from)
    if date_to:
        qs = qs.filter(report__report_date__lte=date_to)
    if name:
        qs = qs.filter(employee_name__icontains=name)
    if site:
        qs = qs.filter(report__site_name__icontains=site)

    return render(request, "attendance/entry_list.html", {
        "entries": qs,
        "date_from": date_from,
        "date_to": date_to,
        "name": name,
        "site": site,
    })


@login_required
def employee_record(request, pk):
    """個人別の勤怠集計。"""
    from apps.workers.models import Worker

    worker = get_object_or_404(Worker, pk=pk)
    month_str = request.GET.get("month", "").strip()
    if month_str:
        try:
            year, month = month_str.split("-")
            year, month = int(year), int(month)
        except (ValueError, TypeError):
            year, month = datetime.date.today().year, datetime.date.today().month
    else:
        year, month = datetime.date.today().year, datetime.date.today().month

    entries = AttendEntry.objects.filter(
        worker=worker,
        report__report_date__year=year,
        report__report_date__month=month,
    ).select_related("report").order_by("report__report_date")

    totals = entries.aggregate(
        total_early=Sum("early_minutes"),
        total_normal=Sum("normal_minutes"),
        total_overtime=Sum("overtime_minutes"),
        total_total=Sum("total_minutes"),
    )
    work_days = entries.count()

    # 日別データ(チャート用)
    daily_data = []
    for e in entries:
        daily_data.append({
            "date": e.report.report_date.strftime("%m/%d"),
            "normal": e.normal_minutes / 60,
            "overtime": e.overtime_minutes / 60,
            "early": e.early_minutes / 60,
        })

    return render(request, "attendance/employee_record.html", {
        "worker": worker,
        "entries": entries,
        "totals": totals,
        "work_days": work_days,
        "year": year,
        "month": month,
        "month_str": f"{year}-{month:02d}",
        "daily_data": daily_data,
    })


@login_required
def summary(request):
    """会社全体の勤怠サマリ。"""
    month_str = request.GET.get("month", "").strip()
    if month_str:
        try:
            year, month = month_str.split("-")
            year, month = int(year), int(month)
        except (ValueError, TypeError):
            year, month = datetime.date.today().year, datetime.date.today().month
    else:
        year, month = datetime.date.today().year, datetime.date.today().month

    entries = AttendEntry.objects.filter(
        report__report_date__year=year,
        report__report_date__month=month,
    ).select_related("report", "worker")

    # 従業員別集計
    emp_data = defaultdict(lambda: {
        "name": "",
        "worker_pk": None,
        "days": 0,
        "early": 0,
        "normal": 0,
        "overtime": 0,
        "total": 0,
    })

    for e in entries:
        key = e.employee_name
        emp_data[key]["name"] = e.employee_name
        if e.worker_id:
            emp_data[key]["worker_pk"] = e.worker_id
        emp_data[key]["days"] += 1
        emp_data[key]["early"] += e.early_minutes
        emp_data[key]["normal"] += e.normal_minutes
        emp_data[key]["overtime"] += e.overtime_minutes
        emp_data[key]["total"] += e.total_minutes

    employee_summary = sorted(emp_data.values(), key=lambda x: x["name"])

    # 全体合計
    grand_total = {
        "days": sum(e["days"] for e in employee_summary),
        "early": sum(e["early"] for e in employee_summary),
        "normal": sum(e["normal"] for e in employee_summary),
        "overtime": sum(e["overtime"] for e in employee_summary),
        "total": sum(e["total"] for e in employee_summary),
    }

    return render(request, "attendance/summary.html", {
        "employee_summary": employee_summary,
        "grand_total": grand_total,
        "year": year,
        "month": month,
        "month_str": f"{year}-{month:02d}",
    })


@login_required
def settings_view(request):
    company = request.user.company
    current = AttendSettings.get_settings_dict(company)

    if request.method == "POST":
        form = AttendSettingsForm(request.POST)
        if form.is_valid():
            for key in AttendSettings.DEFAULTS:
                val = form.cleaned_data.get(key, "")
                obj, created = AttendSettings.unscoped.update_or_create(
                    company=company,
                    key=key,
                    defaults={"value": val},
                )
                if created:
                    obj.created_by = request.user
                    obj.save()
            messages.success(request, "勤怠設定を更新しました。")
            return redirect("attendance:settings")
    else:
        form = AttendSettingsForm(initial=current)

    return render(request, "attendance/settings.html", {
        "form": form,
    })


# ---------------------------------------------------------------------------
# 出社予定（実績の勤怠日報とは別。先の予定を埋めて人繰りを見るための画面）
# ---------------------------------------------------------------------------


@login_required
def plan_board(request):
    """出社予定表。行＝作業員 × 列＝日の月グリッドで記入する。"""
    year, month = parse_month(request.GET.get("month", "").strip())
    board = build_plan_board(request.user.company, year, month)
    settings_dict = AttendSettings.get_settings_dict(request.user.company)

    # 表の下に出す24時間タイムラインの対象日。
    # 指定が無ければ、その月に今日が含まれるなら今日、含まれないなら1日。
    today = timezone.localdate()
    default_day = (
        today if (today.year, today.month) == (year, month)
        else datetime.date(year, month, 1)
    )
    timeline_day = parse_date(request.GET.get("day", ""))
    if not request.GET.get("day"):
        timeline_day = default_day
    timeline = build_day_timeline(
        request.user.company,
        timeline_day,
        parse_clock(settings_dict.get("standard_start"), datetime.time(8, 0)),
        parse_clock(settings_dict.get("standard_end"), datetime.time(17, 0)),
    )

    return render(request, "attendance/plan_board.html", {
        **board,
        "kind_choices": AttendPlan.Kind.choices,
        "kind_fields_json": json_for_script(AttendPlan.KIND_FIELDS),
        "fill_targets": FILL_TARGETS,
        "timeline": timeline,
        "working_labels": [
            label for value, label in AttendPlan.Kind.choices
            if value in AttendPlan.WORKING_KINDS
        ],
        # 所定時間。マスの時刻を空にしたときの目安として画面に出すだけで、
        # 予定には書き込まない（所定を変えても過去の予定は動かさない）。
        "standard_start": settings_dict.get("standard_start", ""),
        "standard_end": settings_dict.get("standard_end", ""),
    })


def _span_days(day, until_value, kind):
    """予定を入れる日を返す。出張のように期間で登録する区分だけ複数日になる。

    1日1行という持ち方は崩さない（崩すと出社人数の集計と月グリッドが成り立たない）。
    期間はここで日ごとに展開する。

    Raises:
        ValueError: 終了日が読めない／開始より前／上限日数を超える
    """
    fields = AttendPlan.KIND_FIELDS.get(kind, {})
    until_value = (until_value or "").strip()
    if not fields.get("span") or not until_value:
        return [day]

    until = datetime.date.fromisoformat(until_value)
    if until < day:
        raise ValueError("終了日が開始日より前です")
    if (until - day).days + 1 > AttendPlan.MAX_SPAN_DAYS:
        raise ValueError(f"期間が長すぎます（{AttendPlan.MAX_SPAN_DAYS}日まで）")
    return [
        day + datetime.timedelta(days=i) for i in range((until - day).days + 1)
    ]


def _parse_time(value: str):
    """入力された "HH:MM" を time にする。空なら None、読めなければ ValueError。"""
    value = (value or "").strip()
    if not value:
        return None
    return datetime.time.fromisoformat(value)


@login_required
@require_POST
def plan_set(request):
    """1マスぶんの予定を保存する。

    区分パレットで塗る操作（区分だけ）と、マスの詳細ダイアログ
    （区分・時刻・メモ）の両方から呼ぶ。

    POST:
        worker … 作業員PK
        date   … YYYY-MM-DD
        kind   … AttendPlan.Kind の値。空ならその日の予定を消す
        start_time, end_time … HH:MM。空なら所定どおり
        note   … 現場名などのメモ
    """
    worker_id = request.POST.get("worker", "").strip()
    if not worker_id.isdigit():
        return JsonResponse(
            {"ok": False, "error": "作業員が指定されていません"}, status=400,
        )
    # objects（テナント絞り込み済み）で引くので、他社の作業員は 404 になる
    worker = get_object_or_404(Worker, pk=int(worker_id))

    try:
        plan_date = datetime.date.fromisoformat(request.POST.get("date", ""))
    except ValueError:
        return JsonResponse({"ok": False, "error": "日付が不正です"}, status=400)

    kind = request.POST.get("kind", "").strip()

    # 区分が空＝その日の予定を消す。マスの「削除」もここに来る。
    if not kind:
        AttendPlan.objects.filter(worker=worker, plan_date=plan_date).delete()
        return JsonResponse({
            "ok": True, "kind": "", "label": "", "note": "",
            "start_time": "", "end_time": "", "time_label": "",
            "is_working": False,
        })

    if kind not in AttendPlan.Kind.values:
        return JsonResponse({"ok": False, "error": "区分が不正です"}, status=400)

    try:
        start_time = _parse_time(request.POST.get("start_time", ""))
        end_time = _parse_time(request.POST.get("end_time", ""))
    except ValueError:
        return JsonResponse({"ok": False, "error": "時刻が不正です"}, status=400)

    try:
        days = _span_days(plan_date, request.POST.get("until", ""), kind)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    values = {
        "kind": kind,
        "start_time": start_time,
        "end_time": end_time,
        "note": request.POST.get("note", "").strip()[:200],
    }
    plan = None
    for day in days:
        obj, created = AttendPlan.objects.get_or_create(
            company=request.user.company,
            worker=worker,
            plan_date=day,
            defaults={**values, "created_by": request.user},
        )
        if not created:
            for field, value in values.items():
                setattr(obj, field, value)
            obj.save(update_fields=[*values, "updated_at"])
        if day == plan_date:
            plan = obj

    return JsonResponse({
        "ok": True,
        "kind": plan.kind,
        "label": plan.get_kind_display(),
        "note": plan.note,
        "start_time": plan.start_time.strftime("%H:%M") if plan.start_time else "",
        "end_time": plan.end_time.strftime("%H:%M") if plan.end_time else "",
        "short": plan.short_label,
        "time_label": plan.time_label,
        "is_working": plan.is_working,
        # 出張などで後続の日にも入れた場合、画面を読み直させる
        "reload": len(days) > 1,
    })


@login_required
def plan_day(request):
    """1日ぶんの予定シート。その日の全員を縦に並べて一度に記入する。

    月グリッド（plan_board）は1人の1ヶ月を横に見る画面なので、
    「明日は誰がどこへ行くか」を全員ぶん埋めるには向きが合わない。
    同じ AttendPlan を、日を固定して全員ぶん編集する。

    GET  … date=YYYY-MM-DD（省略時は今日）
    POST … 作業員ごとに kind_<pk> / start_<pk> / end_<pk> / note_<pk>
           kind が空の行はその日の予定を消す
    """
    day = parse_date(request.GET.get("date") or request.POST.get("date", ""))
    back = f"{reverse('attendance:plan_day')}?date={day.isoformat()}"

    if request.method == "POST":
        # POST の作業員PKは信用せず、自社の在籍者だけを回す。
        # 他社のPKを混ぜられても触れないようにするため。
        workers = list(Worker.objects.filter(is_active=True))
        existing = {
            plan.worker_id: plan
            for plan in AttendPlan.objects.filter(
                worker__in=workers, plan_date=day,
            )
        }
        saved = 0
        removed = 0

        for worker in workers:
            kind = request.POST.get(f"kind_{worker.pk}", "").strip()
            plan = existing.get(worker.pk)

            if not kind:
                if plan:
                    plan.delete()
                    removed += 1
                continue

            if kind not in AttendPlan.Kind.values:
                messages.error(request, f"{worker.name} の区分が不正です")
                return redirect(back)

            try:
                start_time = _parse_time(request.POST.get(f"start_{worker.pk}", ""))
                end_time = _parse_time(request.POST.get(f"end_{worker.pk}", ""))
            except ValueError:
                messages.error(request, f"{worker.name} の時刻が不正です")
                return redirect(back)

            values = {
                "kind": kind,
                "start_time": start_time,
                "end_time": end_time,
                "note": request.POST.get(f"note_{worker.pk}", "").strip()[:200],
            }

            try:
                target_days = _span_days(
                    day, request.POST.get(f"until_{worker.pk}", ""), kind,
                )
            except ValueError as exc:
                messages.error(request, f"{worker.name}: {exc}")
                return redirect(back)

            for target in target_days:
                obj = plan if target == day else AttendPlan.objects.filter(
                    worker=worker, plan_date=target,
                ).first()
                if obj is None:
                    AttendPlan.objects.create(
                        company=request.user.company, worker=worker,
                        plan_date=target, created_by=request.user, **values,
                    )
                    saved += 1
                elif any(getattr(obj, field) != value
                         for field, value in values.items()):
                    for field, value in values.items():
                        setattr(obj, field, value)
                    obj.save(update_fields=[*values, "updated_at"])
                    saved += 1

        parts = []
        if saved:
            parts.append(f"{saved} 人を記入")
        if removed:
            parts.append(f"{removed} 人を削除")
        detail = "・".join(parts) if parts else "変更なし"
        messages.success(
            request, f"{day.month}月{day.day}日 の予定を保存しました（{detail}）",
        )
        return redirect(back)

    settings_dict = AttendSettings.get_settings_dict(request.user.company)
    sheet = build_day_sheet(request.user.company, day)
    return render(request, "attendance/plan_day.html", {
        **sheet,
        "kind_choices": AttendPlan.Kind.choices,
        "kind_fields_json": json_for_script(AttendPlan.KIND_FIELDS),
        # 行の色と出社人数を保存前に画面側で更新するため、稼働区分を渡す
        "working_kinds_json": json_for_script(list(AttendPlan.WORKING_KINDS)),
        "standard_start": settings_dict.get("standard_start", ""),
        "standard_end": settings_dict.get("standard_end", ""),
    })


@login_required
@require_POST
def plan_clear_day(request):
    """その日の予定を全員ぶん消す。休業日にしたときなど。

    POST:
        date  … YYYY-MM-DD
        month … 戻り先の月（YYYY-MM）
    """
    year, month = parse_month(request.POST.get("month", "").strip())
    month_str = f"{year}-{month:02d}"
    back = f"{reverse('attendance:plan_board')}?month={month_str}"

    try:
        plan_date = datetime.date.fromisoformat(request.POST.get("date", ""))
    except ValueError:
        messages.error(request, "日付が不正です")
        return redirect(back)

    removed = AttendPlan.objects.filter(plan_date=plan_date).delete()[0]
    messages.success(
        request,
        f"{plan_date.month}月{plan_date.day}日 の予定を {removed} 件消しました",
    )
    return redirect(back)


@login_required
@require_POST
def plan_fill(request):
    """月のうち条件に合う日をまとめて埋める。

    出社予定は「毎週火曜は現場」のように曜日で決まることが多い。
    まず曜日単位で埋めて、違う日だけマスを塗り替える使い方を想定している。

    POST:
        worker … 作業員PK。空なら在籍中の全員
        month  … YYYY-MM
        target … "weekday"（平日）/ "all"（毎日）/ "0"〜"6"（月〜日曜）
                 / "dates"（カレンダーで選んだ日。dates に日付を並べる）
        dates  … YYYY-MM-DD（複数可）。target が "dates" のときだけ使う
        kind   … 埋める区分。空なら対象日の予定を消す
        start_time, end_time … HH:MM。空なら所定どおり
        overwrite … "1" のとき既に入っている日も上書きする
    """
    year, month = parse_month(request.POST.get("month", "").strip())
    month_str = f"{year}-{month:02d}"
    back = f"{reverse('attendance:plan_board')}?month={month_str}"

    worker_id = request.POST.get("worker", "").strip()
    if worker_id:
        if not worker_id.isdigit():
            messages.error(request, "作業員が指定されていません")
            return redirect(back)
        workers = [get_object_or_404(Worker, pk=int(worker_id))]
        who = workers[0].name
    else:
        workers = list(Worker.objects.filter(is_active=True))
        who = "全員"

    target = request.POST.get("target", "weekday").strip()
    days = fill_days(year, month, target, request.POST.getlist("dates"))
    if target == FILL_TARGET_DATES:
        if not days:
            messages.error(request, "対象日をカレンダーから選んでください")
            return redirect(back)
        # 「9/3・9/10・9/24」のように選んだ日をそのまま見せる。
        # 多いときは数だけにして、メッセージが長くならないようにする。
        if len(days) <= 5:
            target_label = "・".join(f"{d.month}/{d.day}" for d in days)
        else:
            target_label = f"選んだ{len(days)}日"
    else:
        target_label = dict(FILL_TARGETS).get(target, "平日（月〜金）")
    kind = request.POST.get("kind", "").strip()

    if not kind:
        removed = AttendPlan.objects.filter(
            worker__in=workers, plan_date__in=days,
        ).delete()[0]
        messages.success(
            request, f"{who}の{target_label}の予定を {removed} 件消しました",
        )
        return redirect(back)

    if kind not in AttendPlan.Kind.values:
        messages.error(request, "区分が不正です")
        return redirect(back)

    try:
        start_time = _parse_time(request.POST.get("start_time", ""))
        end_time = _parse_time(request.POST.get("end_time", ""))
    except ValueError:
        messages.error(request, "時刻が不正です")
        return redirect(back)

    overwrite = bool(request.POST.get("overwrite"))
    existing = {
        (p.worker_id, p.plan_date): p
        for p in AttendPlan.objects.filter(worker__in=workers, plan_date__in=days)
    }
    filled = 0
    for worker in workers:
        for day in days:
            plan = existing.get((worker.pk, day))
            if plan is None:
                AttendPlan.objects.create(
                    company=request.user.company, worker=worker, plan_date=day,
                    kind=kind, start_time=start_time, end_time=end_time,
                    created_by=request.user,
                )
                filled += 1
            elif overwrite:
                plan.kind = kind
                plan.start_time = start_time
                plan.end_time = end_time
                plan.save(
                    update_fields=["kind", "start_time", "end_time", "updated_at"],
                )
                filled += 1

    label = dict(AttendPlan.Kind.choices)[kind]
    messages.success(
        request, f"{who}の{target_label} {filled} 件を「{label}」にしました",
    )
    return redirect(back)

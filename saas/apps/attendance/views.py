import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attendance.forms import AttendSettingsForm
from apps.attendance.models import AttendPlan, AttendSettings
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
    site_name_suggestions,
)
from apps.core.json_utils import json_for_script
from apps.workers.models import Worker


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
        # 「場所・メモ」の候補（登録済みの現場名）。候補にない行き先も入力できる（ADR-0037）
        "site_names": site_name_suggestions(request.user.company),
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
        # 「現場名・行先」の候補（登録済みの現場名）。候補にない行き先も入力できる（ADR-0037）
        "site_names": site_name_suggestions(request.user.company),
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

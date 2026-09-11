import datetime
import json
from collections import defaultdict
from itertools import zip_longest

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.attendance.entries import (
    MAX_ENTRIES_PER_DAY,
    EntryError,
    make_entry,
    parse_time,
    save_day_entries,
    validate_entries,
)
from apps.attendance.forms import AttendSettingsForm
from apps.attendance.models import AttendPlan, AttendSettings
from apps.attendance.plans import (
    FILL_TARGETS,
    build_day_sheet,
    build_day_timeline,
    build_plan_board,
    fill_days,
    parse_clock,
    parse_date,
    parse_month,
    site_name_suggestions,
    sort_plans,
    summarize_day,
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
        # ダイアログで1日を時間で分けて足せる予定の上限（ADR-0038）
        "max_entries": MAX_ENTRIES_PER_DAY,
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

    期間はここで日ごとに展開し、各日に同じ予定を入れる。出張は終日の区分なので、
    展開した日にあった他の予定は置き換わる（その日1件だけ、ADR-0038）。

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


def _worker_and_date(request):
    """POST の worker と date を読む。(作業員, 日付, エラーの応答) を返す。

    objects（テナント絞り込み済み）で引くので、他社の作業員は 404 になる。
    """
    worker_id = request.POST.get("worker", "").strip()
    if not worker_id.isdigit():
        error = JsonResponse({"ok": False, "error": "作業員が指定されていません"}, status=400)
        return None, None, error
    worker = get_object_or_404(Worker, pk=int(worker_id))

    try:
        plan_date = datetime.date.fromisoformat(request.POST.get("date", ""))
    except ValueError:
        return worker, None, JsonResponse({"ok": False, "error": "日付が不正です"}, status=400)
    return worker, plan_date, None


def _day_response(worker, plan_date, **extra) -> dict:
    """マス1つぶんを描き直すための応答（その人のその日の予定のまとめ）。"""
    summary = summarize_day(AttendPlan.objects.filter(worker=worker, plan_date=plan_date))
    summary.pop("entries_json")
    return {**summary, **extra}


def _save_entries(request, worker, plan_date, entries, days):
    """entries を days の各日に保存し、plan_date のマスの応答を返す。"""
    try:
        with transaction.atomic():
            for day in days:
                save_day_entries(request.user.company, request.user, worker, day, entries)
    except EntryError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    # 出張などで後続の日にも入れた場合、画面を読み直させる
    return JsonResponse(_day_response(worker, plan_date, ok=True, reload=len(days) > 1))


@login_required
@require_POST
def plan_set(request):
    """1マスぶんの予定を1件にして保存する。区分パレットで塗る操作から呼ぶ。

    その日に予定が2件以上ある（時間で分けてある）マスは塗り替えない。
    塗ると分けた予定を1件に潰してしまうため、409 とその日の予定を返し、
    画面はダイアログ（plan_entries）を開く。

    POST:
        worker … 作業員PK
        date   … YYYY-MM-DD
        kind   … AttendPlan.Kind の値。空ならその日の予定を消す
        start_time, end_time … HH:MM。空なら所定どおり
        note   … 現場名などのメモ
        until  … 出張の最終日（空ならその日だけ）
    """
    worker, plan_date, error = _worker_and_date(request)
    if error:
        return error

    if AttendPlan.objects.filter(worker=worker, plan_date=plan_date).count() > 1:
        return JsonResponse(
            _day_response(
                worker, plan_date, ok=False, multiple=True,
                error="この日は予定が複数あります。マスをダブルクリックして編集してください",
            ),
            status=409,
        )

    kind = request.POST.get("kind", "").strip()
    try:
        # 区分が空＝その日の予定を消す
        entries = [
            make_entry(
                kind,
                request.POST.get("start_time", ""),
                request.POST.get("end_time", ""),
                request.POST.get("note", ""),
            ),
        ] if kind else []
        days = _span_days(plan_date, request.POST.get("until", ""), kind)
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return _save_entries(request, worker, plan_date, entries, days)


@login_required
@require_POST
def plan_entries(request):
    """マスの詳細ダイアログから、1人1日ぶんの予定をまとめて保存する（ADR-0038）。

    「＋ 時間を分けて予定を追加」で足した予定も、ここで一緒に保存する。

    POST:
        worker  … 作業員PK
        date    … YYYY-MM-DD
        entries … JSON の配列 [{"id", "kind", "start_time", "end_time", "note"}, ...]。
                  その日の予定をこの並びに置き換える。空の配列ならその日の予定を消す。
                  区分が空の要素は無視する
        until   … 出張の最終日。予定が1件のときだけ使う
    """
    worker, plan_date, error = _worker_and_date(request)
    if error:
        return error

    try:
        items = json.loads(request.POST.get("entries", "[]"))
    except ValueError:
        items = None
    if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
        return JsonResponse({"ok": False, "error": "予定の形式が不正です"}, status=400)

    try:
        entries = [
            make_entry(
                item.get("kind"), item.get("start_time"), item.get("end_time"),
                item.get("note"), item.get("id"),
            )
            for item in items
            if str(item.get("kind") or "").strip()
        ]
        validate_entries(entries)
        days = (
            _span_days(plan_date, request.POST.get("until", ""), entries[0].kind)
            if len(entries) == 1 else [plan_date]
        )
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)

    return _save_entries(request, worker, plan_date, entries, days)


@login_required
def plan_day(request):
    """1日ぶんの予定シート。その日の全員を縦に並べて一度に記入する。

    月グリッド（plan_board）は1人の1ヶ月を横に見る画面なので、
    「明日は誰がどこへ行くか」を全員ぶん埋めるには向きが合わない。
    同じ AttendPlan を、日を固定して全員ぶん編集する。

    GET  … date=YYYY-MM-DD（省略時は今日）
    POST … 作業員ごとに id_<pk> / kind_<pk> / start_<pk> / end_<pk> / note_<pk> /
           until_<pk>。1日を時間で分けた人は同じ名前の欄が行の数だけ並ぶ（ADR-0038）。
           区分が空の行は保存しない。その人の行がすべて空ならその日の予定を消す
    """
    day = parse_date(request.GET.get("date") or request.POST.get("date", ""))
    back = f"{reverse('attendance:plan_day')}?date={day.isoformat()}"

    if request.method == "POST":
        # POST の作業員PKは信用せず、自社の在籍者だけを回す。
        # 他社のPKを混ぜられても触れないようにするため。
        workers = list(Worker.objects.filter(is_active=True))

        # 同じ名前の欄を getlist で行ごとに揃えて読む。
        # 先に全員ぶんを確かめ、1人でも不正なら誰も保存しない。
        planned = []
        for worker in workers:
            pk = worker.pk
            rows = zip_longest(
                request.POST.getlist(f"kind_{pk}"),
                request.POST.getlist(f"start_{pk}"),
                request.POST.getlist(f"end_{pk}"),
                request.POST.getlist(f"note_{pk}"),
                request.POST.getlist(f"id_{pk}"),
                request.POST.getlist(f"until_{pk}"),
                fillvalue="",
            )
            entries = []
            untils = []
            try:
                for kind, start, end, note, entry_id, until in rows:
                    if not kind.strip():
                        continue
                    entries.append(make_entry(kind, start, end, note, entry_id))
                    untils.append(until)
                validate_entries(entries)
                # 出張の最終日は、その人の予定が1件のときだけ効く
                target_days = (
                    _span_days(day, untils[0], entries[0].kind)
                    if len(entries) == 1 else [day]
                )
            except ValueError as exc:
                messages.error(request, f"{worker.name}: {exc}")
                return redirect(back)
            planned.append((worker, entries, target_days))

        saved = 0
        removed = 0
        with transaction.atomic():
            for worker, entries, target_days in planned:
                changed = False
                for target in target_days:
                    counts = save_day_entries(
                        request.user.company, request.user, worker, target, entries,
                    )
                    changed = changed or any(counts)
                if changed and entries:
                    saved += 1
                elif changed:
                    removed += 1

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
        # 1人に足せる予定の上限（ADR-0038）
        "max_entries": MAX_ENTRIES_PER_DAY,
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
        kind   … 埋める区分。空なら対象日の予定を消す
        start_time, end_time … HH:MM。空なら所定どおり
        overwrite … "1" のとき既に入っている日も上書きする
                    （時間で分けてあった日も1件にまとめ直す）
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
    days = fill_days(year, month, target)
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
        start_time = parse_time(request.POST.get("start_time", ""))
        end_time = parse_time(request.POST.get("end_time", ""))
    except ValueError:
        messages.error(request, "時刻が不正です")
        return redirect(back)

    overwrite = bool(request.POST.get("overwrite"))
    existing = defaultdict(list)
    for plan in AttendPlan.objects.filter(worker__in=workers, plan_date__in=days):
        existing[(plan.worker_id, plan.plan_date)].append(plan)

    filled = 0
    for worker in workers:
        for day in days:
            plans = sort_plans(existing.get((worker.pk, day), []))
            if not plans:
                AttendPlan.objects.create(
                    company=request.user.company, worker=worker, plan_date=day,
                    kind=kind, start_time=start_time, end_time=end_time,
                    created_by=request.user,
                )
                filled += 1
            elif overwrite:
                first, *rest = plans
                first.kind = kind
                first.start_time = start_time
                first.end_time = end_time
                first.save(
                    update_fields=["kind", "start_time", "end_time", "updated_at"],
                )
                # 時間で分けてあった日は1件にまとめ直す
                for plan in rest:
                    plan.delete()
                filled += 1

    label = dict(AttendPlan.Kind.choices)[kind]
    messages.success(
        request, f"{who}の{target_label} {filled} 件を「{label}」にしました",
    )
    return redirect(back)

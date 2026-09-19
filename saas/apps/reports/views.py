from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.permissions.services import can_approve_report, can_delete_report, can_edit_report
from apps.reports.duplicates import (
    day_breakdown,
    find_duplicate_reports,
    needs_confirmation,
)
from apps.reports.forms import DailyReportForm
from apps.reports.missing_alerts import missing_days_for_worker
from apps.reports.models import DailyReport, SafetyRecord
from apps.reports.services import (
    alert_safety_incomplete,
    approve_report,
    check_safety_completion,
    get_monthly_summary,
)


def _parse_list_month(value):
    """日報一覧の月指定 "YYYY-MM" を (年, 月) にする。空や読めない値は None（全期間）。

    勤怠の parse_month は読めないと今月にするが、一覧では「指定なし＝全期間」に
    したいので別に持つ（今月に絞ると先月以前の未承認が見えなくなる。ADR-0047）。
    """
    from datetime import date

    try:
        year, month = (int(part) for part in (value or "").split("-"))
        date(year, month, 1)
    except (ValueError, TypeError):
        return None
    return year, month


def _parse_list_date(value):
    """日報一覧の日付指定 "YYYY-MM-DD" を date にする。空や読めない値は None（絞らない）。"""
    from datetime import date

    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _date_label(day):
    """「2026年9月14日（月）」。"""
    weekdays = "月火水木金土日"
    return f"{day.year}年{day.month}月{day.day}日（{weekdays[day.weekday()]}）"


def _parse_pk(value):
    """URL の現場・作業員の指定を整数にする。空や読めない値は None（絞らない）。"""
    try:
        pk = int((value or "").strip())
    except ValueError:
        return None
    return pk if pk > 0 else None


def _filtered_reports(request):
    """一覧の絞り込み（状態・月または日付・現場・作業員）を当てた日報と、選ばれた条件を返す。

    一覧の画面と一覧の PDF で同じ条件を使うため共通にしている。
    日付と月の両方が指定されたら日付を優先し、月は外す（ADR-0060）。
    DailyReport.objects は自社の日報だけなので、他社の現場・作業員の番号を
    指定されても何も出ない。
    """
    reports = DailyReport.objects.select_related(
        "worker", "site", "work_type"
    ).order_by("-report_date", "-created_at")

    filters = {
        "status": request.GET.get("status", ""),
        # 月（指定なし・読めない値は全期間）
        "month": _parse_list_month(request.GET.get("month", "").strip()),
        # 日付（1 日だけ。指定があれば月より優先）
        "date": _parse_list_date(request.GET.get("date")),
        "site": _parse_pk(request.GET.get("site")),
        "worker": _parse_pk(request.GET.get("worker")),
    }
    if filters["date"]:
        filters["month"] = None
    if filters["status"]:
        reports = reports.filter(status=filters["status"])
    if filters["date"]:
        reports = reports.filter(report_date=filters["date"])
    if filters["month"]:
        year, month = filters["month"]
        reports = reports.filter(report_date__year=year, report_date__month=month)
    if filters["site"]:
        reports = reports.filter(site_id=filters["site"])
    if filters["worker"]:
        reports = reports.filter(worker_id=filters["worker"])
    return reports, filters


def _filter_query(filters, **overrides):
    """絞り込みを URL のクエリにする。overrides で一部を差し替える（month="" で外す）。"""
    from urllib.parse import urlencode

    values = {
        "month": f"{filters['month'][0]}-{filters['month'][1]:02d}" if filters["month"] else "",
        "date": filters["date"].isoformat() if filters.get("date") else "",
        "status": filters["status"],
        "site": filters["site"] or "",
        "worker": filters["worker"] or "",
    }
    values.update(overrides)
    return urlencode({k: v for k, v in values.items() if v})


def _filter_labels(filters):
    """選ばれた現場・作業員の名前（件数表示と PDF のファイル名に使う）。"""
    from apps.sites.models import Site
    from apps.workers.models import Worker

    site = Site.objects.filter(pk=filters["site"]).first() if filters["site"] else None
    worker = Worker.objects.filter(pk=filters["worker"]).first() if filters["worker"] else None
    return (site.name if site else ""), (worker.name if worker else "")


def _filter_choices():
    """現場・作業員の選択肢。自社の日報に出てくるものだけにする（ADR-0050）。

    登録済みの全現場を出すと完了した現場まで並び、選びにくくなるため。
    """
    from apps.sites.models import Site
    from apps.workers.models import Worker, sort_workers_by_code

    site_ids = DailyReport.objects.values_list("site_id", flat=True).distinct()
    worker_ids = DailyReport.objects.values_list("worker_id", flat=True).distinct()
    sites = list(Site.objects.filter(pk__in=site_ids).order_by("name"))
    workers = sort_workers_by_code(Worker.objects.filter(pk__in=worker_ids))
    return sites, workers


@login_required
def report_list(request):
    from django.utils import timezone

    from apps.attendance.plans import shift_month

    reports, filters = _filtered_reports(request)
    selected_month = ""
    prev_query = next_query = ""
    if filters["month"]:
        year, month = filters["month"]
        selected_month = f"{year}-{month:02d}"
        prev_query = _filter_query(filters, month=shift_month(year, month, -1))
        next_query = _filter_query(filters, month=shift_month(year, month, 1))
    # 日付を選んだときは前日・翌日で 1 日ずつ動かす（月をまたいでもよい。ADR-0060）
    from datetime import timedelta

    selected_date = filters["date"].isoformat() if filters["date"] else ""
    prev_day_query = next_day_query = ""
    if filters["date"]:
        one_day = timedelta(days=1)
        prev_day_query = _filter_query(filters, date=(filters["date"] - one_day).isoformat())
        next_day_query = _filter_query(filters, date=(filters["date"] + one_day).isoformat())
    today = timezone.localdate()
    this_month = f"{today.year}-{today.month:02d}"

    site_label, worker_label = _filter_labels(filters)
    month_label = (
        f"{int(selected_month[:4])}年{int(selected_month[5:])}月" if selected_month else ""
    )
    date_label = _date_label(filters["date"]) if filters["date"] else ""
    # 件数の見出し。「2026年9月・A社ビル・電工太郎の日報」のように選んだ条件を並べる
    scope_parts = (date_label or month_label or "すべての月", site_label, worker_label)
    scope_label = "・".join(x for x in scope_parts if x)

    # 削除ボタンを出すかどうかを行ごとに決める（承認済には出さない）。
    reports = list(reports)
    for r in reports:
        r.can_delete = can_delete_report(request.user, r)

    sites, workers = _filter_choices()
    return render(request, "reports/list.html", {
        "reports": reports,
        # 自分の日報が抜けている日を赤字で出す（ADR-0080）
        "my_missing_days": missing_days_for_worker(
            getattr(request.user, "worker_profile", None),
        ),
        "status_choices": DailyReport.Status.choices,
        "selected_status": filters["status"],
        "selected_month": selected_month,
        "selected_date": selected_date,
        "today": today.isoformat(),
        "selected_site": filters["site"],
        "selected_worker": filters["worker"],
        "site_choices": sites,
        "worker_choices": workers,
        "month_label": month_label,
        "scope_label": scope_label,
        "this_month": this_month,
        # 前月・翌月・今月・すべての月・PDF のリンクは、他の絞り込みを引き継ぐ
        # （& はテンプレートで &amp; にエスケープされる）
        "prev_query": prev_query,
        "next_query": next_query,
        "prev_day_query": prev_day_query,
        "next_day_query": next_day_query,
        # 月に切り替えるリンクは日付を外し、日付に切り替えるリンクは月を外す
        "this_month_query": _filter_query(filters, month=this_month, date=""),
        "today_query": _filter_query(filters, date=today.isoformat(), month=""),
        "all_months_query": _filter_query(filters, month="", date=""),
        "clear_date_query": _filter_query(filters, date=""),
        # 現場・作業員を外すときは期間（月・日付）だけ残す
        "clear_site_worker_query": _filter_query(filters, site="", worker="", status=""),
        "list_pdf_query": _filter_query(filters),
        "can_approve": can_approve_report(request.user),
        "submitted_count": DailyReport.objects.filter(
            status=DailyReport.Status.SUBMITTED
        ).count(),
    })


# 一覧の PDF に入れる日報の上限。全期間のまま押すと数千ページになり、
# サーバーの応答が返らなくなるため。超えたら月などで絞ってもらう（ADR-0049）。
REPORT_PDF_MAX = 300


def _pdf_response(pdf_bytes, filename):
    from django.http import HttpResponse
    from django.utils.http import content_disposition_header

    response = HttpResponse(pdf_bytes, content_type="application/pdf")
    # inline: ブラウザで開いてから保存・印刷できるようにする。日本語のファイル名は
    # filename*（RFC 5987）で送る（そのまま入れるとブラウザによって文字化けする）。
    response["Content-Disposition"] = content_disposition_header(False, filename)
    return response


def _report_prefetch(queryset):
    return queryset.select_related(
        "company", "worker", "site__customer", "work_type", "process",
        "partner", "created_by", "approved_by",
    )


def _safe_filename(text):
    """ファイル名に使えない文字（スラッシュ・バックスラッシュ・コロン・* ? " < > |）を _ にする。
    """
    return text.translate(str.maketrans('\\/:*?"<>|', "_________"))


@login_required
def report_pdf(request, pk):
    """日報の PDF。原本の様式は「1 現場 × 1 日」なので、この日報と同じ日・同じ現場の
    日報を 1 枚にまとめて出す（ADR-0049、ADR-0053）。"""
    from apps.reports.pdf import generate_reports_pdf

    report = get_object_or_404(DailyReport.objects.select_related("site"), pk=pk)
    same_sheet = _report_prefetch(
        DailyReport.objects.filter(site_id=report.site_id, report_date=report.report_date)
    ).order_by("pk")
    filename = _safe_filename(f"日報_{report.report_date:%Y-%m-%d}_{report.site.name}.pdf")
    return _pdf_response(generate_reports_pdf(list(same_sheet)), filename)


@login_required
def report_list_pdf(request):
    """一覧の絞り込み（状態・月・現場・作業員）のまま、同じ日・同じ現場ごとに 1 枚の PDF にする。
    """
    from apps.reports.pdf import generate_reports_pdf

    reports, filters = _filtered_reports(request)
    query = _filter_query(filters)
    back = reverse("reports:list") + (f"?{query}" if query else "")

    count = reports.count()
    if not count:
        messages.warning(request, "PDF にする日報がありません。")
        return redirect(back)
    if count > REPORT_PDF_MAX:
        messages.error(
            request,
            f"日報が {count} 件あり、一度に PDF にできる {REPORT_PDF_MAX} 件を超えています。"
            "月・現場・作業員などで絞ってから出してください。",
        )
        return redirect(back)

    # 印刷して綴じる用途なので、PDF の中は日付の古い順・現場名順に並べる
    # （同じ日・同じ現場の日報は generate_reports_pdf が 1 枚にまとめる）
    reports = _report_prefetch(reports).order_by("report_date", "site__name", "site_id", "pk")
    month = filters["month"]
    site_label, worker_label = _filter_labels(filters)
    if filters["date"]:
        period = filters["date"].isoformat()
    else:
        period = f"{month[0]}-{month[1]:02d}" if month else "全期間"
    parts = [period, site_label, worker_label]
    label = _safe_filename("_".join(p for p in parts if p))
    return _pdf_response(generate_reports_pdf(list(reports)), f"日報_{label}.pdf")


def _submit_action(request):
    """押されたボタン。重複の確認画面から送り直したときは hidden から受ける（ADR-0079）。"""
    return request.POST.get("action") or request.POST.get("duplicate_action", "")


def _report_form_context(company):
    """日報フォームの候補一覧と、現場→発注先の対応表を返す。"""
    from apps.core.json_utils import json_for_script
    from apps.masters.models import WorkType
    from apps.sites.models import Site

    sites = list(
        Site.unscoped.filter(company=company)
        .select_related("customer")
        .order_by("name")
    )
    return {
        "site_names": [s.name for s in sites],
        "weather_choices": [label for _v, label in DailyReport.Weather.choices],
        "worktype_names": list(
            WorkType.unscoped.filter(company=company, is_active=True)
            .order_by("name")
            .values_list("name", flat=True)
        ),
        # 現場名を入れたら発注先を自動で埋めるための対応表
        "site_orderer_json": json_for_script(
            {s.name: (str(s.customer) if s.customer else "") for s in sites}
        ),
    }


@login_required
def report_detail(request, pk):
    """日報の詳細（一覧の行をタップして開く。ADR-0054）。"""
    report = get_object_or_404(
        DailyReport.objects.select_related(
            "worker", "site__customer", "work_type", "process", "partner",
            "created_by", "approved_by",
        ),
        pk=pk,
    )
    def _hours(value):
        # 「10.5」「8」のように余計な 0 を付けない（PDF と同じ書き方）
        return None if value is None else f"{value.normalize():f}"

    work, regular, overtime = report.hours_breakdown()
    materials = [
        {
            "name": m.material.name if m.material_id else m.material_name,
            "quantity": m.quantity_used.normalize() if m.quantity_used is not None else None,
            "unit": m.unit,
            "maker": m.maker,
            "model_number": m.model_number,
            "note": m.note,
        }
        for m in report.materials_used.select_related("material").order_by("pk")
    ]
    back_url = _back_url(request)
    return render(request, "reports/detail.html", {
        "report": report,
        "work_hours": _hours(work),
        "regular_hours": _hours(regular),
        "overtime_hours": _hours(overtime),
        # 開始・終了が無く作業時間だけの日報は、通常・残業を作業時間から出していることを添える
        "hours_derived": not (report.start_time and report.end_time) and work is not None,
        "materials": materials,
        "back_url": back_url,
        # 月次サマリから開いたときは戻るボタンの行き先に合わせた名前にする
        "back_label": (
            "月次サマリに戻る"
            if back_url.startswith(reverse("reports:monthly_summary")) else "一覧に戻る"
        ),
        "can_approve": (
            can_approve_report(request.user)
            and report.status == DailyReport.Status.SUBMITTED
        ),
        "can_delete": can_delete_report(request.user, report),
    })


@login_required
def report_create(request):
    """日報を書く。役職・社員番号に関係なく全員が同じ形式（ADR-0043）。"""
    # ログインした人の作業員。基本は自分の日報を書く画面にし、
    # 「作業員の日報をまとめて書く」を押したときだけ他の人の一覧を出す。
    profile = getattr(request.user, "worker_profile", None)
    if request.method == "POST":
        form = DailyReportForm(
            request.POST, company=request.user.company, self_worker=profile,
        )
        if form.is_valid():
            # 同じ日・同じ人の日報が既にあれば、いったん止めて選んでもらう（ADR-0079）
            # 同じ現場の日報が既にあれば、いったん止めて選んでもらう（ADR-0079）。
            # 別の現場だけなら止めない。1日2現場は普通にある（ADR-0100）
            duplicates = find_duplicate_reports(
                request.user.company,
                list(form.cleaned_data.get("workers") or []),
                form.cleaned_data.get("report_date"),
                site_name=form.cleaned_data.get("site", ""),
            )
            if needs_confirmation(duplicates) and request.POST.get("confirm_duplicate") != "1":
                return render(request, "reports/form.html", {
                    "form": form,
                    "duplicates": duplicates,
                    "duplicate_action": request.POST.get("action", ""),
                    **_report_form_context(request.user.company),
                })
            status = (
                DailyReport.Status.SUBMITTED
                if _submit_action(request) == "submit"
                else None
            )
            saved, skipped = form.save_reports(
                company=request.user.company, user=request.user, status=status,
            )
            messages.success(request, f"{len(saved)}件の日報を保存しました。")
            # 1日を現場ごとに分けて入れたときは、その日の内訳を出す（ADR-0100）。
            # 分けた結果がそのとおり入ったかを、一覧を開かずに確かめられるように
            for line in day_breakdown(request.user.company, saved):
                messages.info(request, line)
            if skipped:
                names = "、".join(str(w) for w in skipped)
                messages.warning(
                    request,
                    f"{names} は同じ現場・日付・工種の日報が既にあるため作成しませんでした。",
                )
            return redirect("reports:list")
    else:
        form = DailyReportForm(company=request.user.company, self_worker=profile)
    ctx = {
        "form": form,
        "my_missing_days": missing_days_for_worker(profile),
        **_report_form_context(request.user.company),
    }
    return render(request, "reports/form.html", ctx)


def _back_url(request):
    """編集後に戻る先（next）。月次サマリなど、日報を開いた元の画面に戻すために使う。

    GET では ?next=、POST ではフォームの hidden から受ける。
    同じホスト内の URL だけ許す（外部サイトへ飛ばされないように）。
    """
    from django.utils.http import url_has_allowed_host_and_scheme

    value = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if value and url_has_allowed_host_and_scheme(
        value, allowed_hosts={request.get_host()}, require_https=request.is_secure(),
    ):
        return value
    return ""


@login_required
def report_edit(request, pk):
    report = get_object_or_404(DailyReport, pk=pk)
    # 他人の日報を直せるのは社長・IT・事務員だけ（ADR-0102）。
    # 以前は pk さえ分かれば誰でも他人の日報を直せた。
    if not can_edit_report(request.user, report):
        raise PermissionDenied("他人の日報を直せるのは社長・IT・事務員のみです。")
    back_url = _back_url(request)
    if request.method == "POST":
        form = DailyReportForm(
            request.POST, instance=report, company=request.user.company,
        )
        if form.is_valid():
            duplicates = find_duplicate_reports(
                request.user.company,
                list(form.cleaned_data.get("workers") or []),
                form.cleaned_data.get("report_date"),
                site_name=form.cleaned_data.get("site", ""),
                exclude_pk=report.pk,
            )
            if needs_confirmation(duplicates) and request.POST.get("confirm_duplicate") != "1":
                return render(request, "reports/form.html", {
                    "form": form,
                    "duplicates": duplicates,
                    "duplicate_action": request.POST.get("action", ""),
                    "can_delete": can_delete_report(request.user, report),
                    "back_url": back_url,
                    **_report_form_context(request.user.company),
                })
            status = (
                DailyReport.Status.SUBMITTED
                if _submit_action(request) == "submit"
                else None
            )
            saved, skipped = form.save_reports(
                company=request.user.company, user=request.user, status=status,
            )
            messages.success(request, "日報を更新しました。")
            # 編集で足した作業員の日報（saved の先頭はこの日報）
            if saved[1:]:
                names = "、".join(str(r.worker) for r in saved[1:])
                messages.success(request, f"{names} の日報を同じ内容で作成しました。")
            if skipped:
                names = "、".join(str(w) for w in skipped)
                messages.warning(
                    request,
                    f"{names} は同じ現場・日付・工種の日報が既にあるため作成しませんでした。",
                )
            if form.propagated:
                names = "、".join(str(r.worker) for r in form.propagated)
                messages.success(request, f"一緒に作った {names} の日報にも反映しました。")
            if form.propagate_skipped:
                names = "、".join(str(w) for w in form.propagate_skipped)
                messages.warning(
                    request,
                    f"{names} の日報は同じ現場・日付・工種の日報が既にあるため"
                    "反映できませんでした。",
                )
            return redirect(back_url or "reports:list")
    else:
        form = DailyReportForm(instance=report, company=request.user.company)
    ctx = {
        "form": form,
        "can_delete": can_delete_report(request.user, report),
        # 月次サマリなどから開いたときは、保存・戻るでその画面（同じ作業員が開いた状態）に戻す
        "back_url": back_url,
        **_report_form_context(request.user.company),
    }
    return render(request, "reports/form.html", ctx)


@login_required
def report_delete(request, pk):
    """日報を削除する。GET は確認画面、POST で削除する。

    自分の日報は消せる。他人の日報は社長・IT・事務員だけ（ADR-0102）。
    承認済の日報は労務費を計上済みのため、誰であっても削除できない。
    """
    report = get_object_or_404(
        DailyReport.objects.select_related("worker", "site", "work_type"), pk=pk,
    )
    if not can_delete_report(request.user, report):
        # 断られる理由は2つある。どちらで止まったのかが分かる文面にする。
        if report.status == DailyReport.Status.APPROVED:
            raise PermissionDenied("承認済の日報は削除できません。")
        raise PermissionDenied("他人の日報を消せるのは社長・IT・事務員のみです。")

    if request.method == "POST":
        label = f"{report.report_date} {report.worker} の日報"
        report.delete()
        messages.success(request, f"{label}を削除しました。")
        return redirect("reports:list")

    return render(request, "reports/delete_confirm.html", {"report": report})


@login_required
def report_approve(request, pk):
    if not can_approve_report(request.user):
        raise PermissionDenied("日報を承認できるのは社長とITのみです。")

    report = get_object_or_404(DailyReport, pk=pk)
    if report.status == DailyReport.Status.SUBMITTED:
        approve_report(report, approved_by=request.user)
        messages.success(
            request,
            f"{report.worker} の日報を承認し、労務費を計上しました。",
        )
    else:
        messages.info(request, "提出済の日報のみ承認できます。")
    return redirect("reports:list")


@login_required
def report_approve_bulk(request):
    """提出済の日報をまとめて承認する。"""
    if not can_approve_report(request.user):
        raise PermissionDenied("日報を承認できるのは社長とITのみです。")

    if request.method != "POST":
        return redirect("reports:list")

    pks = request.POST.getlist("report_ids")
    reports = DailyReport.objects.filter(
        pk__in=pks, status=DailyReport.Status.SUBMITTED,
    )

    approved = 0
    for report in reports:
        approve_report(report, approved_by=request.user)
        approved += 1

    if approved:
        messages.success(request, f"{approved}件の日報を承認し、労務費を計上しました。")
    else:
        messages.info(request, "承認できる日報が選択されていません。")
    return redirect("reports:list")


@login_required
def safety_check(request):
    """安全書類チェック画面。"""
    from datetime import date

    from apps.sites.models import Site

    # "active" という状態は Site.Status に存在せず、常に空になっていた。
    # 稼働中とみなせる状態（受注済・施工中）を対象にする。
    sites = Site.objects.filter(
        status__in=[Site.Status.ORDERED, Site.Status.IN_PROGRESS]
    ).order_by("name")
    selected_site_id = request.GET.get("site")
    check_date = request.GET.get("date", str(date.today()))

    result = None
    selected_site = None
    if selected_site_id:
        selected_site = get_object_or_404(Site, pk=selected_site_id)
        result = check_safety_completion(selected_site, check_date)

    # 一括アラート送信
    if request.method == "POST" and selected_site:
        alert_safety_incomplete(
            request.user.company, selected_site, check_date,
        )
        messages.success(request, "未記入者にアラートを送信しました。")
        return redirect(f"/reports/safety/?site={selected_site_id}&date={check_date}")

    return render(request, "reports/safety_check.html", {
        "sites": sites,
        "selected_site": selected_site,
        "check_date": check_date,
        "result": result,
    })


@login_required
def safety_complete(request, pk):
    """安全書類を記入済みにする。"""
    from django.utils import timezone

    record = get_object_or_404(SafetyRecord, pk=pk)
    record.completed = True
    record.completed_at = timezone.now()
    record.save()
    messages.success(
        request, f"{record.worker.name}の{record.template.name}を記入済みにしました。"
    )

    return redirect(
        f"/reports/safety/?site={record.template.site_id}&date={record.record_date}"
    )


@login_required
def monthly_summary(request):
    """月次サマリ画面。

    作業員一覧と同じ社員番号順で作業員ごとの勤怠集計を出し、
    氏名をタップするとその月の承認済の日報一覧が開く（各行から日報の画面へ）。
    """
    from datetime import date

    year = int(request.GET.get("year", date.today().year))
    month = int(request.GET.get("month", date.today().month))

    summary = get_monthly_summary(request.user.company, year, month)

    # 各日報へのリンクに next を付け、日報の保存・戻るで「この月・この作業員を開いた
    # 状態」の月次サマリに戻れるようにする（#worker-<pk> で該当の行が開く）。
    from urllib.parse import urlencode

    from django.urls import reverse

    base = f"{reverse('reports:monthly_summary')}?year={year}&month={month}"
    for row in summary:
        back = f"{base}#worker-{row['worker'].pk}"
        for report in row["reports"]:
            # 月次サマリからは編集ではなく日報の詳細を開く（詳細から編集・戻るで同じ場所に戻る）
            report.detail_url = (
                reverse("reports:detail", args=[report.pk]) + "?" + urlencode({"next": back})
            )

    return render(request, "reports/monthly_summary.html", {
        "summary": summary,
        "year": year,
        "month": month,
    })

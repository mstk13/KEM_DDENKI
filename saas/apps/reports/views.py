from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.permissions.services import can_approve_report, can_delete_report
from apps.reports.forms import DailyReportForm
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


def _parse_pk(value):
    """URL の現場・作業員の指定を整数にする。空や読めない値は None（絞らない）。"""
    try:
        pk = int((value or "").strip())
    except ValueError:
        return None
    return pk if pk > 0 else None


def _filtered_reports(request):
    """一覧の絞り込み（状態・月・現場・作業員）を当てた日報と、選ばれた条件を返す。

    一覧の画面と一覧の PDF で同じ条件を使うため共通にしている。
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
        "site": _parse_pk(request.GET.get("site")),
        "worker": _parse_pk(request.GET.get("worker")),
    }
    if filters["status"]:
        reports = reports.filter(status=filters["status"])
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
    today = timezone.localdate()
    this_month = f"{today.year}-{today.month:02d}"

    site_label, worker_label = _filter_labels(filters)
    month_label = (
        f"{int(selected_month[:4])}年{int(selected_month[5:])}月" if selected_month else ""
    )
    # 件数の見出し。「2026年9月・A社ビル・電工太郎の日報」のように選んだ条件を並べる
    scope_parts = (month_label or "すべての月", site_label, worker_label)
    scope_label = "・".join(x for x in scope_parts if x)

    # 削除ボタンを出すかどうかを行ごとに決める（承認済には出さない）。
    reports = list(reports)
    for r in reports:
        r.can_delete = can_delete_report(request.user, r)

    sites, workers = _filter_choices()
    return render(request, "reports/list.html", {
        "reports": reports,
        "status_choices": DailyReport.Status.choices,
        "selected_status": filters["status"],
        "selected_month": selected_month,
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
        "this_month_query": _filter_query(filters, month=this_month),
        "all_months_query": _filter_query(filters, month=""),
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


@login_required
def report_pdf(request, pk):
    """日報 1 件を PDF で出す（ADR-0049）。"""
    from apps.reports.pdf import generate_reports_pdf

    report = get_object_or_404(_report_prefetch(DailyReport.objects.all()), pk=pk)
    filename = f"日報_{report.report_date:%Y-%m-%d}_{report.worker}.pdf"
    return _pdf_response(generate_reports_pdf([report]), filename)


@login_required
def report_list_pdf(request):
    """一覧の絞り込み（状態・月・現場・作業員）のまま、日報を 1 件 1 ページで PDF にする。"""
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

    # 印刷して綴じる用途なので、PDF の中は日付の古い順に並べる
    reports = _report_prefetch(reports).order_by("report_date", "worker__employee_code", "pk")
    month = filters["month"]
    site_label, worker_label = _filter_labels(filters)
    parts = [f"{month[0]}-{month[1]:02d}" if month else "全期間", site_label, worker_label]
    # ファイル名に使えない文字（/ \ など）は _ にする
    label = "_".join(p for p in parts if p).translate(str.maketrans('\\/:*?"<>|', "_________"))
    return _pdf_response(generate_reports_pdf(list(reports)), f"日報_{label}.pdf")


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
            status = (
                DailyReport.Status.SUBMITTED
                if request.POST.get("action") == "submit"
                else None
            )
            saved, skipped = form.save_reports(
                company=request.user.company, user=request.user, status=status,
            )
            messages.success(request, f"{len(saved)}件の日報を保存しました。")
            if skipped:
                names = "、".join(str(w) for w in skipped)
                messages.warning(
                    request,
                    f"{names} は同じ現場・日付・工種の日報が既にあるため作成しませんでした。",
                )
            return redirect("reports:list")
    else:
        form = DailyReportForm(company=request.user.company, self_worker=profile)
    ctx = {"form": form, **_report_form_context(request.user.company)}
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
    back_url = _back_url(request)
    if request.method == "POST":
        form = DailyReportForm(
            request.POST, instance=report, company=request.user.company,
        )
        if form.is_valid():
            status = (
                DailyReport.Status.SUBMITTED
                if request.POST.get("action") == "submit"
                else None
            )
            form.save_reports(
                company=request.user.company, user=request.user, status=status,
            )
            messages.success(request, "日報を更新しました。")
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

    ログインしていれば誰でも削除できる。
    承認済の日報は労務費を計上済みのため削除できない。
    """
    report = get_object_or_404(
        DailyReport.objects.select_related("worker", "site", "work_type"), pk=pk,
    )
    if not can_delete_report(request.user, report):
        raise PermissionDenied("承認済の日報は削除できません。")

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
            report.edit_url = (
                reverse("reports:edit", args=[report.pk]) + "?" + urlencode({"next": back})
            )

    return render(request, "reports/monthly_summary.html", {
        "summary": summary,
        "year": year,
        "month": month,
    })

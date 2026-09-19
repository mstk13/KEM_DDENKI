"""作業日報集計の画面（ADR-0104）。

- 集計表（作業員 1 人・1 か月）と PDF（1 人分・全員分）… 月次サマリを見られる人なら誰でも
- 1 日分を直す・日報の内容に戻す・集計から外す … can_edit_tally の人
- 時間の区切りの設定・直せる人の付け外し … 社長・管理者
"""

from datetime import date
from functools import wraps
from urllib.parse import urlencode

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from apps.reports.models import WorkTallyEditor, WorkTallyEntry, WorkTallySettings
from apps.reports.tally_pdf import generate_tally_pdf, reiwa_month
from apps.reports.views import _pdf_response
from apps.reports.work_tally import (
    build_sheet,
    can_edit_tally,
    can_manage_tally_editors,
    get_tally_settings,
    report_row,
    vehicle_candidates,
    workers_with_tally,
)
from apps.workers.models import Worker, sort_workers_by_code


def _year_month(request):
    today = date.today()
    try:
        year = int(request.GET.get("year", today.year))
        month = int(request.GET.get("month", today.month))
        date(year, month, 1)
    except ValueError:
        return today.year, today.month
    return year, month


def _worker(request, pk):
    # 自社の作業員だけ（他社の作業員の番号を指定されたら 404）
    return get_object_or_404(Worker.unscoped, pk=pk, company=request.user.company)


def _sheet_url(worker, year, month):
    query = urlencode({"year": year, "month": month})
    return f"{reverse('reports:tally_sheet', args=[worker.pk])}?{query}"


def _day(year, month, day):
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise Http404("日付が正しくありません") from exc


def _require(check):
    """check(user) が偽なら 403。"""
    def decorator(view):
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not check(request.user):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorator


# ---------------------------------------------------------------------------
# 集計表・PDF
# ---------------------------------------------------------------------------


@login_required
def tally_sheet(request, worker_pk):
    worker = _worker(request, worker_pk)
    year, month = _year_month(request)
    sheet = build_sheet(request.user.company, worker, year, month)
    back = f"{reverse('reports:monthly_summary')}?{urlencode({'year': year, 'month': month})}"
    return render(request, "reports/tally_sheet.html", {
        "sheet": sheet,
        "worker": worker,
        "year": year,
        "month": month,
        "month_label": reiwa_month(year, month),
        "can_edit": can_edit_tally(request.user),
        "back_url": f"{back}#worker-{worker.pk}",
    })


@login_required
def tally_pdf(request, worker_pk):
    worker = _worker(request, worker_pk)
    year, month = _year_month(request)
    sheet = build_sheet(request.user.company, worker, year, month)
    return _pdf_response(
        generate_tally_pdf([sheet]), f"作業日報集計_{year}年{month}月_{worker.name}.pdf",
    )


@login_required
def tally_pdf_all(request):
    year, month = _year_month(request)
    company = request.user.company
    settings = get_tally_settings(company)
    sheets = [
        build_sheet(company, worker, year, month, settings)
        for worker in workers_with_tally(company, year, month)
    ]
    if not sheets:
        messages.info(request, f"{year}年{month}月は集計表に載せる日がありません。")
        return redirect(f"{reverse('reports:monthly_summary')}?year={year}&month={month}")
    return _pdf_response(generate_tally_pdf(sheets), f"作業日報集計_{year}年{month}月_全員.pdf")


# ---------------------------------------------------------------------------
# 1 日分を直す
# ---------------------------------------------------------------------------


class TallyEntryForm(forms.Form):
    start_time = forms.TimeField(
        label="始業", required=False,
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}, format="%H:%M"),
    )
    end_time = forms.TimeField(
        label="終業", required=False,
        help_text="終業が始業より早いときは、翌日にまたがる勤務として計算します。",
        widget=forms.TimeInput(attrs={"type": "time", "class": "form-control"}, format="%H:%M"),
    )
    work_description = forms.CharField(
        label="作業内容", required=False,
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )
    materials = forms.CharField(
        label="使用材料", required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
    )
    vehicle = forms.CharField(
        label="車両", required=False, max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "list": "tally-vehicles"}),
    )
    site_names = forms.CharField(
        label="現場名", required=False, max_length=300,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

    def clean(self):
        data = super().clean()
        if bool(data.get("start_time")) != bool(data.get("end_time")):
            raise forms.ValidationError("始業と終業は両方入れるか、両方空けてください。")
        return data


FORM_FIELDS = tuple(TallyEntryForm.base_fields)


def _row_initial(row):
    return {
        "start_time": row.start,
        "end_time": row.end,
        "work_description": row.work_description,
        "materials": row.materials,
        "vehicle": row.vehicle,
        "site_names": row.site_names,
    }


@login_required
@_require(can_edit_tally)
def tally_entry_edit(request, worker_pk, year, month, day):
    worker = _worker(request, worker_pk)
    company = request.user.company
    work_date = _day(year, month, day)
    entry = WorkTallyEntry.unscoped.filter(
        company=company, worker=worker, work_date=work_date,
    ).first()
    from_reports = report_row(company, worker, work_date)
    initial = _row_initial(from_reports)
    if entry:
        initial = {name: getattr(entry, name) for name in FORM_FIELDS}

    if request.method == "POST":
        form = TallyEntryForm(request.POST, initial=initial)
        if form.is_valid():
            values = dict(form.cleaned_data, excluded=False, updated_by=request.user)
            WorkTallyEntry.unscoped.update_or_create(
                company=company, worker=worker, work_date=work_date,
                defaults=values, create_defaults={**values, "created_by": request.user},
            )
            messages.success(request, f"{worker.name}さんの{month}月{day}日を直しました。")
            return redirect(_sheet_url(worker, year, month))
    else:
        form = TallyEntryForm(initial=initial)

    return render(request, "reports/tally_entry_form.html", {
        "form": form,
        "worker": worker,
        "work_date": work_date,
        "weekday": from_reports.weekday,
        "entry": entry,
        "from_reports": from_reports,
        "vehicles": vehicle_candidates(company),
        "sheet_url": _sheet_url(worker, year, month),
    })


@login_required
@_require(can_edit_tally)
@require_POST
def tally_entry_reset(request, worker_pk, year, month, day):
    """手直しを消し、日報から作った行に戻す（外した日も戻る）。"""
    worker = _worker(request, worker_pk)
    work_date = _day(year, month, day)
    WorkTallyEntry.unscoped.filter(
        company=request.user.company, worker=worker, work_date=work_date,
    ).delete()
    messages.success(request, f"{month}月{day}日を日報の内容に戻しました。")
    return redirect(_sheet_url(worker, year, month))


@login_required
@_require(can_edit_tally)
@require_POST
def tally_entry_exclude(request, worker_pk, year, month, day):
    """その日を集計表から外す（行は残して薄く出す。PDF と合計には入れない）。"""
    worker = _worker(request, worker_pk)
    company = request.user.company
    work_date = _day(year, month, day)
    entry = WorkTallyEntry.unscoped.filter(
        company=company, worker=worker, work_date=work_date,
    ).first()
    if entry is None:
        row = report_row(company, worker, work_date)
        entry = WorkTallyEntry(
            company=company, worker=worker, work_date=work_date, created_by=request.user,
            **_row_initial(row),
        )
    entry.excluded = True
    entry.updated_by = request.user
    entry.save()
    messages.success(request, f"{month}月{day}日を集計から外しました。")
    return redirect(_sheet_url(worker, year, month))


@login_required
@_require(can_edit_tally)
def tally_add_day(request, worker_pk):
    """日報の無い日を足す。日付を選んで、その日を直す画面へ。"""
    worker = _worker(request, worker_pk)
    try:
        picked = date.fromisoformat(request.GET.get("date", ""))
    except ValueError:
        messages.error(request, "足す日を選んでください。")
        year, month = _year_month(request)
        return redirect(_sheet_url(worker, year, month))
    return redirect(
        "reports:tally_entry_edit", worker.pk, picked.year, picked.month, picked.day,
    )


# ---------------------------------------------------------------------------
# 設定・直せる人
# ---------------------------------------------------------------------------


class TallySettingsForm(forms.ModelForm):
    class Meta:
        model = WorkTallySettings
        fields = (
            "regular_start", "regular_end", "night_start",
            "break1_start", "break1_end", "break2_start", "break2_end",
            "break3_start", "break3_end",
        )
        widgets = {
            name: forms.TimeInput(attrs={"type": "time", "class": "form-control"}, format="%H:%M")
            for name in fields
        }

    def clean(self):
        data = super().clean()
        if (
            data.get("regular_start") and data.get("regular_end") and data.get("night_start")
            and not data["regular_start"] < data["regular_end"] <= data["night_start"]
        ):
            raise forms.ValidationError(
                "所定開始 < 所定終了 ≦ 深夜開始 になるように入れてください。",
            )
        for no in (1, 2, 3):
            start, end = data.get(f"break{no}_start"), data.get(f"break{no}_end")
            if bool(start) != bool(end):
                raise forms.ValidationError(
                    f"休憩{no}は開始と終了を両方入れるか、両方空けてください。",
                )
            if start and end and start >= end:
                raise forms.ValidationError(f"休憩{no}は終了を開始より後にしてください。")
        return data


@login_required
@_require(can_manage_tally_editors)
def tally_settings(request):
    company = request.user.company
    instance = get_tally_settings(company)
    if request.method == "POST":
        form = TallySettingsForm(request.POST, instance=instance)
        if form.is_valid():
            saved = form.save(commit=False)
            saved.company = company
            if saved.pk is None:
                saved.created_by = request.user
            saved.save()
            messages.success(request, "集計表の時間の区切りを保存しました。")
            return redirect("reports:tally_settings")
    else:
        form = TallySettingsForm(instance=instance)
    return render(request, "reports/tally_settings.html", {"form": form})


@login_required
@_require(can_manage_tally_editors)
def tally_editors(request):
    company = request.user.company
    granted = {
        grant.worker_id: grant
        for grant in WorkTallyEditor.unscoped.filter(company=company).select_related("granted_by")
    }
    workers = sort_workers_by_code(Worker.unscoped.filter(company=company, is_active=True))
    rows = []
    for worker in workers:
        code = worker.employee_code or ""
        rows.append({
            "worker": worker,
            "grant": granted.get(worker.pk),
            # 社長・管理者は付けなくても直せる（外せない）
            "always": code.startswith("Y") or (worker.position and worker.position.name == "社長"),
        })
    return render(request, "reports/tally_editors.html", {"rows": rows})


@login_required
@_require(can_manage_tally_editors)
@require_POST
def tally_editor_grant(request, worker_pk):
    worker = _worker(request, worker_pk)
    WorkTallyEditor.unscoped.get_or_create(
        company=request.user.company, worker=worker,
        defaults={"granted_by": request.user, "created_by": request.user},
    )
    messages.success(request, f"{worker.name}さんが集計表を直せるようにしました。")
    return redirect("reports:tally_editors")


@login_required
@_require(can_manage_tally_editors)
@require_POST
def tally_editor_revoke(request, worker_pk):
    worker = _worker(request, worker_pk)
    WorkTallyEditor.unscoped.filter(company=request.user.company, worker=worker).delete()
    messages.success(request, f"{worker.name}さんの集計表を直す権限を外しました。")
    return redirect("reports:tally_editors")

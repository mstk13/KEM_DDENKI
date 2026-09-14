"""現場の安全書類（KY用紙・安全作業確認書）の画面（ADR-0061）。

使える人は、ほかの現場の画面と同じ（ログインした同じ会社の人）。
ただし安全作業確認書は住所・緊急連絡先・健康の値を含むので、見て書けるのは
その作業員について can_view_worker_private が通る人（管理者・事務員・Developer・本人）だけ。
"""

import datetime
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.offline.decorators import offline_resendable
from apps.permissions.services import can_view_worker_private
from apps.safety import pdf
from apps.safety.formats import KY_CHECK_POINTS, KY_NOTES, SAFETY_RULES, SHOCK_RULES
from apps.safety.forms import (
    EntryConfirmationForm,
    KyParticipantForm,
    KySheetForm,
    KySignoffForm,
)
from apps.safety.models import EntryConfirmation, KyParticipant, KySheet
from apps.safety.services import (
    entry_initial,
    ky_initial,
    members_on_day,
    workers_without_entry,
)
from apps.sites.models import Site
from apps.workers.models import Worker

# KY用紙のサインの欄: URL の kind → 画面の名前・サインの項目・文を書く項目
SIGNOFFS = {
    "guidance": {
        "label": "指導事項",
        "signer": "現場代理人または代務者",
        "signature": "guidance_signature",
        "text": "guidance",
    },
    "confirm": {
        "label": "確認",
        "signer": "現場代理人または代務者",
        "signature": "confirm_signature",
        "text": None,
    },
    "completion": {
        "label": "作業完了報告",
        "signer": "作業責任者",
        "signature": "completion_signature",
        "text": None,
    },
    "patrol": {
        "label": "現場巡視指導記録",
        "signer": "現場代理人または代務者",
        "signature": "patrol_signature",
        "text": "patrol_record",
    },
}


def _pdf_response(content, filename):
    response = HttpResponse(content, content_type="application/pdf")
    response["Content-Disposition"] = (
        f"inline; filename=\"safety.pdf\"; filename*=UTF-8''{quote(filename)}"
    )
    return response


def _parse_day(value):
    try:
        return datetime.date.fromisoformat(value or "")
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 現場の安全書類
# ---------------------------------------------------------------------------


@login_required
def site_safety(request, site_pk):
    """現場の安全書類。今日の KY 用紙の記入状況・これまでの用紙・安全作業確認書。"""
    site = get_object_or_404(Site, pk=site_pk)
    # 別の日の KY 用紙を開く（?day=2026-09-15）
    day = _parse_day(request.GET.get("day"))
    if day is not None:
        return redirect("safety:ky_sheet", site_pk=site.pk, day=day)

    today = timezone.localdate()
    members = members_on_day(site, today)
    today_sheet = KySheet.objects.filter(site=site, work_date=today).first()
    signed_ids = (
        set(today_sheet.participants.values_list("worker_id", flat=True)) if today_sheet else set()
    )
    confirmations = list(
        EntryConfirmation.objects.filter(site=site)
        .select_related("worker")
        .order_by("worker__name")
    )
    own = getattr(request.user, "worker_profile", None)
    return render(
        request,
        "safety/site_safety.html",
        {
            "site": site,
            "today": today,
            "today_sheet": today_sheet,
            "members": [{"worker": w, "signed": w.pk in signed_ids} for w in members],
            "sheets": (
                KySheet.objects.filter(site=site)
                .prefetch_related("participants")
                .order_by("-work_date")[:30]
            ),
            "confirmations": [
                {"confirmation": c, "can_view": can_view_worker_private(request.user, c.worker)}
                for c in confirmations
            ],
            "members_without_entry": [
                {"worker": w, "can_write": can_view_worker_private(request.user, w)}
                for w in workers_without_entry(site, members)
            ],
            "own_worker": own,
            "own_confirmation": next(
                (c for c in confirmations if own is not None and c.worker_id == own.pk),
                None,
            ),
        },
    )


# ---------------------------------------------------------------------------
# KY用紙
# ---------------------------------------------------------------------------


def _get_or_create_sheet(site, day, user):
    """その日の KY 用紙。無ければ最初の値で作る（同時に作られても1枚にする）。"""
    initial = ky_initial(site, day)
    defaults = {k: v for k, v in initial.items() if k != "risks"}
    defaults["risks"] = initial["risks"]
    # unscoped: 現場の会社で明示的に絞る（一意制約も会社・現場・日）
    sheet, _created = KySheet.unscoped.get_or_create(
        company=site.company,
        site=site,
        work_date=day,
        defaults={**defaults, "created_by": user},
    )
    return sheet


@login_required
@offline_resendable
def ky_sheet(request, site_pk, day):
    """KY用紙の上半分（作業責任者が書くところ）と、参加者の一覧・サイン。"""
    site = get_object_or_404(Site, pk=site_pk)
    sheet = KySheet.objects.filter(site=site, work_date=day).first()

    if request.method == "POST":
        instance = sheet or KySheet(
            company=site.company,
            site=site,
            work_date=day,
            created_by=request.user,
        )
        form = KySheetForm(request.POST, instance=instance)
        if form.is_valid():
            try:
                with transaction.atomic():
                    form.save()
            except IntegrityError:
                # 同じ日の用紙を別の人が先に作った。作られた用紙に書き直してもらう
                messages.warning(
                    request,
                    "同じ日の KY 用紙がほかの人に作られていました。内容を確かめてください。",
                )
                return redirect("safety:ky_sheet", site_pk=site.pk, day=day)
            messages.success(request, f"{day.month}月{day.day}日の KY 用紙を保存しました。")
            return redirect("safety:ky_sheet", site_pk=site.pk, day=day)
    else:
        form = KySheetForm(instance=sheet, initial=None if sheet else ky_initial(site, day))

    participants = list(sheet.participants.select_related("worker")) if sheet else []
    signed = {p.worker_id for p in participants}
    return render(
        request,
        "safety/ky_sheet.html",
        {
            "site": site,
            "day": day,
            "sheet": sheet,
            "form": form,
            "participants": participants,
            "unsigned_members": [w for w in members_on_day(site, day) if w.pk not in signed],
            "check_points": KY_CHECK_POINTS,
            "notes": KY_NOTES,
            "signoffs": [
                {
                    "kind": kind,
                    **spec,
                    "signed": bool(sheet and getattr(sheet, spec["signature"])),
                    "signature_value": getattr(sheet, spec["signature"]) if sheet else "",
                    "text_value": getattr(sheet, spec["text"]) if sheet and spec["text"] else "",
                }
                for kind, spec in SIGNOFFS.items()
            ],
        },
    )


@login_required
@offline_resendable
def ky_sign(request, site_pk, day):
    """KY用紙の自分の行（氏名の自筆サイン・健康状態・検電器）を書く。同じ人は書き直しで上書き。"""
    site = get_object_or_404(Site, pk=site_pk)
    own = getattr(request.user, "worker_profile", None)

    if request.method == "POST":
        form = KyParticipantForm(request.POST, company=site.company)
        if form.is_valid():
            data = form.cleaned_data
            with transaction.atomic():
                sheet = _get_or_create_sheet(site, day, request.user)
                participant = KyParticipant.unscoped.filter(
                    sheet=sheet, worker=data["worker"]
                ).first() or KyParticipant(
                    company=site.company,
                    sheet=sheet,
                    worker=data["worker"],
                    created_by=request.user,
                )
                participant.health = data["health"]
                participant.health_note = data["health_note"]
                participant.tester = data["tester"]
                participant.signature = data["signature"]
                participant.signed_at = timezone.now()
                participant.save()
            messages.success(request, f"{data['worker'].name} さんの行を記入しました。")
            return redirect("safety:ky_sheet", site_pk=site.pk, day=day)
    else:
        worker_pk = request.GET.get("worker", "")
        initial_worker = None
        if worker_pk.isdigit():
            initial_worker = Worker.unscoped.filter(
                company=site.company,
                pk=int(worker_pk),
                is_active=True,
            ).first()
        if initial_worker is None and own is not None and own.company_id == site.company_id:
            initial_worker = own
        form = KyParticipantForm(company=site.company, initial={"worker": initial_worker})

    return render(request, "safety/ky_sign.html", {"site": site, "day": day, "form": form})


@login_required
def ky_signoff(request, pk, kind):
    """指導事項・確認・作業完了報告・現場巡視指導記録のサインを書く。"""
    sheet = get_object_or_404(KySheet.objects.select_related("site"), pk=pk)
    spec = SIGNOFFS.get(kind)
    if spec is None:
        raise Http404("サインの欄がありません。")
    text_label = (
        "指導事項" if kind == "guidance" else ("現場巡視指導記録" if spec["text"] else None)
    )
    signature_label = f"{spec['signer']}のサイン"

    if request.method == "POST":
        form = KySignoffForm(
            request.POST,
            text_label=text_label,
            signature_label=signature_label,
        )
        if form.is_valid():
            setattr(sheet, spec["signature"], form.cleaned_data["signature"])
            if spec["text"]:
                setattr(sheet, spec["text"], form.cleaned_data["text"])
            sheet.save()
            messages.success(request, f"「{spec['label']}」のサインを記入しました。")
            return redirect("safety:ky_sheet", site_pk=sheet.site_id, day=sheet.work_date)
    else:
        initial = {"signature": getattr(sheet, spec["signature"])}
        if spec["text"]:
            initial["text"] = getattr(sheet, spec["text"])
        form = KySignoffForm(
            initial=initial,
            text_label=text_label,
            signature_label=signature_label,
        )

    return render(
        request,
        "safety/ky_signoff.html",
        {
            "sheet": sheet,
            "site": sheet.site,
            "spec": spec,
            "form": form,
        },
    )


@login_required
def ky_participant_delete(request, pk):
    """間違えて書いた参加者の行を消す。"""
    participant = get_object_or_404(
        KyParticipant.objects.select_related("sheet", "worker"),
        pk=pk,
    )
    sheet = participant.sheet
    if request.method == "POST":
        name = participant.worker.name
        participant.delete()
        messages.success(request, f"{name} さんの行を消しました。")
    return redirect("safety:ky_sheet", site_pk=sheet.site_id, day=sheet.work_date)


@login_required
def ky_pdf(request, pk):
    sheet = get_object_or_404(KySheet.objects.select_related("site", "company"), pk=pk)
    content = pdf.generate_ky_pdf(sheet)
    return _pdf_response(content, f"KY用紙_{sheet.work_date:%Y%m%d}_{sheet.site.name}.pdf")


# ---------------------------------------------------------------------------
# 安全作業確認書
# ---------------------------------------------------------------------------


def _require_private(request, worker):
    if not can_view_worker_private(request.user, worker):
        raise PermissionDenied(
            "安全作業確認書は、管理者・事務員・本人だけが見て書けます（住所や健康の値を含むため）。",
        )


@login_required
@offline_resendable
def entry_create(request, site_pk):
    """安全作業確認書を書く。?worker= が無ければ自分のぶん。すでにあれば直す画面へ。"""
    site = get_object_or_404(Site, pk=site_pk)
    worker_pk = request.GET.get("worker", "")
    if worker_pk.isdigit():
        worker = get_object_or_404(Worker, pk=int(worker_pk))
    else:
        worker = getattr(request.user, "worker_profile", None)
        if worker is None or worker.company_id != site.company_id:
            messages.info(request, "書く作業員を、一覧の「書く」から選んでください。")
            return redirect("safety:site", site_pk=site.pk)
    _require_private(request, worker)

    existing = EntryConfirmation.objects.filter(site=site, worker=worker).first()
    if existing is not None:
        messages.info(
            request, f"{worker.name} さんの安全作業確認書はもうあります。直すときはこちらから。"
        )
        return redirect("safety:entry_edit", pk=existing.pk)

    if request.method == "POST":
        form = EntryConfirmationForm(
            request.POST,
            instance=EntryConfirmation(
                company=site.company,
                site=site,
                worker=worker,
                created_by=request.user,
            ),
        )
        if form.is_valid():
            try:
                with transaction.atomic():
                    confirmation = form.save()
            except IntegrityError:
                existing = EntryConfirmation.objects.filter(site=site, worker=worker).first()
                messages.info(request, "ほかの端末から先に登録されていました。")
                return redirect("safety:entry_edit", pk=existing.pk)
            messages.success(request, f"{worker.name} さんの安全作業確認書を登録しました。")
            return redirect("safety:entry_detail", pk=confirmation.pk)
    else:
        form = EntryConfirmationForm(initial=entry_initial(site, worker, timezone.localdate()))

    return render(
        request,
        "safety/entry_form.html",
        {
            "site": site,
            "worker": worker,
            "form": form,
            "confirmation": None,
            "shock_rules": SHOCK_RULES,
            "safety_rules": SAFETY_RULES,
        },
    )


@login_required
@offline_resendable
def entry_edit(request, pk):
    confirmation = get_object_or_404(
        EntryConfirmation.objects.select_related("site", "worker"),
        pk=pk,
    )
    _require_private(request, confirmation.worker)
    if request.method == "POST":
        form = EntryConfirmationForm(request.POST, instance=confirmation)
        if form.is_valid():
            form.save()
            messages.success(request, "安全作業確認書を更新しました。")
            return redirect("safety:entry_detail", pk=confirmation.pk)
    else:
        form = EntryConfirmationForm(instance=confirmation)
    return render(
        request,
        "safety/entry_form.html",
        {
            "site": confirmation.site,
            "worker": confirmation.worker,
            "form": form,
            "confirmation": confirmation,
            "shock_rules": SHOCK_RULES,
            "safety_rules": SAFETY_RULES,
        },
    )


@login_required
def entry_detail(request, pk):
    confirmation = get_object_or_404(
        EntryConfirmation.objects.select_related("site", "worker"),
        pk=pk,
    )
    _require_private(request, confirmation.worker)
    return render(
        request,
        "safety/entry_detail.html",
        {
            "confirmation": confirmation,
            "site": confirmation.site,
            "worker": confirmation.worker,
        },
    )


@login_required
def entry_pdf(request, pk):
    confirmation = get_object_or_404(
        EntryConfirmation.objects.select_related("site", "worker", "company"),
        pk=pk,
    )
    _require_private(request, confirmation.worker)
    content = pdf.generate_entry_pdf(confirmation)
    return _pdf_response(
        content,
        f"安全作業確認書_{confirmation.site.name}_{confirmation.worker.name}.pdf",
    )

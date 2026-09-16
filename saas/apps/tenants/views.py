"""自社情報の画面（ADR-0071）。

会社そのものの書類（経審・許可証・証明書など）をしまい、AI で中身を読み取って出す。
中身に売上や評点が入るので、見られるのは社長・管理者（Y）・事務員・Developer だけ。
"""

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.bids.models import ConstructionLicense
from apps.core.documents import content_type_for
from apps.permissions.services import can_view_company_documents
from apps.tenants import company_document_llm
from apps.tenants.company_documents import (
    document_groups,
    mark_confirmed,
    next_display_order,
    renewal_documents,
    save_company_document,
)
from apps.tenants.forms import CompanyDocumentEditForm, CompanyDocumentForm
from apps.tenants.models import CompanyDocument, CompanyDocumentType


def _require_access(user):
    """見られない人は 403。書類に売上・評点・個人の情報が入るため。"""
    if not can_view_company_documents(user):
        raise PermissionDenied("自社情報を見る権限がありません。")


@login_required
def company_document_list(request):
    """自社情報。書類の一覧と、建設業許可（ADR-0064）のまとめ。"""
    _require_access(request.user)
    company = request.user.company
    # unscoped: 会社を明示して絞る（自社情報は request.user の会社そのもの）
    licenses = ConstructionLicense.unscoped.filter(company=company).order_by(
        "renewed", "valid_until", "trade",
    )
    return render(request, "tenants/company_documents.html", {
        "groups": document_groups(company),
        "renewals": renewal_documents(company),
        "licenses": licenses,
        "today": timezone.localdate(),
    })


@login_required
def company_document_create(request):
    """書類を1件登録する。中身を確認したチェックが要る。"""
    _require_access(request.user)
    company = request.user.company

    if request.method == "POST":
        form = CompanyDocumentForm(request.POST, request.FILES, company=company)
        if form.is_valid():
            data = form.cleaned_data
            doc_type = data["doc_type"]
            with transaction.atomic():
                if doc_type is None:
                    doc_type = CompanyDocumentType.unscoped.create(
                        company=company,
                        name=data["new_name"],
                        has_renewal=data["has_renewal"],
                        display_order=next_display_order(company),
                        created_by=request.user,
                    )
                document = save_company_document(
                    company,
                    doc_type=doc_type,
                    name=doc_type.name,
                    uploaded=data["file"],
                    kind=form.file_kind,
                    user=request.user,
                    issued_on=data["issued_on"],
                    renewal_on=data["renewal_on"],
                    memo=data["memo"],
                    confirmed=True,
                    confirmed_by=request.user,
                    confirmed_at=timezone.now(),
                )
            messages.success(
                request,
                f"「{document.name}」を登録しました。"
                "「AI で読み取る」を押すと、中身の要点を出せます。",
            )
            return redirect("tenants:company_document_detail", pk=document.pk)
    else:
        form = CompanyDocumentForm(
            company=company, initial={"doc_type": request.GET.get("type")},
        )

    return render(request, "tenants/company_document_form.html", {"form": form})


@login_required
def company_document_detail(request, pk):
    """書類1件。AI が読み取った中身と、日付・メモの直し。"""
    _require_access(request.user)
    document = get_object_or_404(
        CompanyDocument.objects.select_related("doc_type", "confirmed_by", "created_by"),
        pk=pk,
    )
    if request.method == "POST":
        form = CompanyDocumentEditForm(request.POST, instance=document)
        if form.is_valid():
            form.save()
            messages.success(request, f"「{document.name}」を保存しました。")
            return redirect("tenants:company_document_detail", pk=document.pk)
    else:
        form = CompanyDocumentEditForm(instance=document)

    return render(request, "tenants/company_document_detail.html", {
        "document": document,
        "form": form,
        "ai_available": company_document_llm.is_available(),
    })


@login_required
@require_POST
def company_document_analyze(request, pk):
    """AI に書類を読ませ、要点と更新日を出す。日付が空なら読み取った日を入れる。"""
    _require_access(request.user)
    document = get_object_or_404(CompanyDocument.objects.select_related("doc_type"), pk=pk)
    try:
        data = document.file.read()
    except FileNotFoundError as exc:
        raise Http404("ファイルが見つかりません。") from exc
    finally:
        document.file.close()

    result = company_document_llm.analyze(document, data, user=request.user)
    if result is None:
        messages.error(
            request,
            "AI で読み取れませんでした。しばらくしてからもう一度お試しください"
            "（月の上限に達している場合は、翌月まで使えません）。",
        )
        return redirect("tenants:company_document_detail", pk=document.pk)

    fields = ["ai_summary", "ai_fields", "ai_checked_at", "updated_at"]
    document.ai_summary = result["summary"]
    document.ai_fields = result["fields"]
    document.ai_checked_at = timezone.now()
    filled = []
    if result["issued_on"] and not document.issued_on:
        document.issued_on = result["issued_on"]
        fields.append("issued_on")
        filled.append("発行日")
    if result["renewal_on"] and not document.renewal_on:
        document.renewal_on = result["renewal_on"]
        fields.append("renewal_on")
        filled.append("更新日")
    document.save(update_fields=fields)

    message = "AI で読み取りました。中身を確かめてください。"
    if filled:
        # AI の読み取りをそのまま確定させない。人が見て直せるよう知らせに出す
        message += (
            f"（{'・'.join(filled)}に読み取った日付を入れました。違っていれば直してください）"
        )
    messages.success(request, message)
    return redirect("tenants:company_document_detail", pk=document.pk)


@login_required
@require_POST
def company_document_confirm(request, pk):
    """あとから「中身を確認した」を付ける（AI の読み取りを見てから確かめたとき）。"""
    _require_access(request.user)
    document = get_object_or_404(CompanyDocument.objects, pk=pk)
    mark_confirmed(document, request.user)
    messages.success(request, f"「{document.name}」を確認済みにしました。")
    return redirect("tenants:company_document_detail", pk=document.pk)


@login_required
def company_document_file(request, pk):
    """書類のファイルを返す。PDF は画面で開き、Excel はダウンロードにする。"""
    _require_access(request.user)
    document = get_object_or_404(CompanyDocument.objects, pk=pk)
    field = document.file
    try:
        handle = field.storage.open(field.name, "rb")
    except FileNotFoundError as exc:
        raise Http404("ファイルが見つかりません。") from exc
    response = FileResponse(
        handle,
        as_attachment=document.kind != CompanyDocument.Kind.PDF,
        filename=document.original_filename or Path(field.name).name,
        content_type=content_type_for(field.name),
    )
    # 社外に出せない中身なので、共有のキャッシュには置かせない
    response["Cache-Control"] = "private, no-cache"
    return response


@login_required
def company_document_delete(request, pk):
    """書類を消す。保存したファイルも消える。"""
    _require_access(request.user)
    document = get_object_or_404(CompanyDocument.objects.select_related("doc_type"), pk=pk)
    if request.method == "POST":
        name = document.name
        with transaction.atomic():
            document.delete()
        messages.success(request, f"「{name}」を削除しました。")
        return redirect("tenants:company_document_list")
    return render(request, "tenants/company_document_confirm_delete.html", {
        "document": document,
    })

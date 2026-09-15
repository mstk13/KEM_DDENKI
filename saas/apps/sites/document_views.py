"""現場の提出書類の画面（ADR-0065）。URL は現場と同じ sites の名前空間（sites/urls.py）。

見られるのは、現場と同じく同じ会社のログインした人。ファイルも会社をまたいでは開けない
（CompanyScopedManager で引くので、他社の書類は 404 になる）。
"""

from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.sites.document_forms import SiteDocumentAddForm, SiteDocumentForm, SiteDocumentUploadForm
from apps.sites.documents import (
    add_site_document,
    content_type_for,
    document_progress,
    ensure_site_documents,
    grouped_documents,
    save_document_files,
)
from apps.sites.models import Site, SiteDocument, SiteDocumentFile


def _render_list(request, site, add_form):
    return render(request, "sites/documents/list.html", {
        "site": site,
        "groups": grouped_documents(site),
        "progress": document_progress(site),
        "add_form": add_form,
    })


@login_required
def site_document_list(request, pk):
    """現場の提出書類のリスト。初めて開いたときに会社の最初のリストを写す。"""
    site = get_object_or_404(Site, pk=pk)
    ensure_site_documents(site)
    return _render_list(request, site, SiteDocumentAddForm(site=site))


@login_required
@require_POST
def site_document_add(request, pk):
    """リストに無い書類を名前を付けて足す。"""
    site = get_object_or_404(Site, pk=pk)
    ensure_site_documents(site)
    form = SiteDocumentAddForm(request.POST, site=site)
    if not form.is_valid():
        return _render_list(request, site, form)
    data = form.cleaned_data
    document = add_site_document(
        site,
        name=data["name"],
        phase=data["phase"],
        user=request.user,
        add_to_company_list=data["add_to_company_list"],
    )
    message = f"書類「{document.name}」を足しました。"
    if data["add_to_company_list"]:
        message += "次の現場からも最初のリストに入ります。"
    messages.success(request, message)
    return redirect("sites:document_detail", pk=document.pk)


@login_required
def site_document_detail(request, pk):
    """書類1件: ファイル（PDF・Excel）の登録と、提出の状況。"""
    document = get_object_or_404(SiteDocument.objects.select_related("site"), pk=pk)
    # 入力に誤りがあったときも、見出しには保存してある名前を出す
    document_name = document.name
    status_form = SiteDocumentForm(instance=document)
    upload_form = SiteDocumentUploadForm()

    if request.method == "POST":
        if "upload" in request.POST:
            upload_form = SiteDocumentUploadForm(request.POST, request.FILES)
            if upload_form.is_valid():
                created = save_document_files(
                    document,
                    upload_form.cleaned_data["files"],
                    note=upload_form.cleaned_data["note"],
                    user=request.user,
                )
                messages.success(
                    request, f"「{document.name}」にファイルを {len(created)} 件登録しました。"
                )
                return redirect("sites:document_detail", pk=document.pk)
        else:
            status_form = SiteDocumentForm(request.POST, instance=document)
            if status_form.is_valid():
                status_form.save()
                messages.success(request, f"「{status_form.instance.name}」の状況を保存しました。")
                return redirect("sites:document_detail", pk=document.pk)

    return render(request, "sites/documents/detail.html", {
        "site": document.site,
        "document": document,
        "document_name": document_name,
        "files": document.files.select_related("created_by").order_by("-created_at", "-pk"),
        "status_form": status_form,
        "upload_form": upload_form,
    })


@login_required
def site_document_delete(request, pk):
    """足した書類を消す。置いたファイルも消える。最初のリストの書類は消さず「不要」にしてもらう。"""
    document = get_object_or_404(SiteDocument.objects.select_related("site"), pk=pk)
    site = document.site
    if not document.is_custom:
        messages.error(
            request,
            "最初のリストの書類は削除できません。この現場で要らない書類は、状況を「不要」にしてください。",
        )
        return redirect("sites:document_detail", pk=document.pk)
    if request.method == "POST":
        name = document.name
        with transaction.atomic():
            document.delete()
        messages.success(request, f"書類「{name}」を削除しました。")
        return redirect("sites:document_list", pk=site.pk)
    return render(request, "sites/documents/confirm_delete.html", {
        "site": site,
        "document": document,
        "file_count": document.files.count(),
    })


@login_required
def site_document_file(request, pk):
    """置いたファイルを返す。PDF は画面で開き、Excel はダウンロードにする。"""
    item = get_object_or_404(SiteDocumentFile, pk=pk)
    field = item.file
    try:
        handle = field.storage.open(field.name, "rb")
    except FileNotFoundError as exc:
        raise Http404("ファイルが見つかりません。") from exc
    response = FileResponse(
        handle,
        as_attachment=item.kind != SiteDocumentFile.Kind.PDF,
        filename=item.original_filename or Path(field.name).name,
        content_type=content_type_for(field.name),
    )
    # 書類は差し替わるので端末に長く控えさせない。共有のキャッシュにも置かせない
    response["Cache-Control"] = "private, no-cache"
    return response


@login_required
def site_document_file_delete(request, pk):
    """置いたファイルを消す。保存したファイルも消える（models.delete_site_document_file）。"""
    item = get_object_or_404(SiteDocumentFile.objects.select_related("document__site"), pk=pk)
    document = item.document
    if request.method == "POST":
        with transaction.atomic():
            item.delete()
        messages.success(request, f"ファイル「{item.original_filename}」を削除しました。")
        return redirect("sites:document_detail", pk=document.pk)
    return render(request, "sites/documents/file_confirm_delete.html", {
        "site": document.site,
        "document": document,
        "item": item,
    })

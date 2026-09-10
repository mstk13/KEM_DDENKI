import datetime
import json
import tempfile
from pathlib import Path

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.bids.forms import (
    BidCostForm,
    BidProjectForm,
    QualificationForm,
    UnifiedQualificationForm,
    UnitPriceForm,
)
from apps.bids.gantt import KINDS, KNOWN_STAGES, build_bid_gantt
from apps.bids.models import (
    BidProject,
    BidScheduleRule,
    Qualification,
    SkippedBid,
    UnifiedQualification,
    UnitPrice,
)
from apps.bids.qualification import check_qualifications_for_projects
from apps.bids.services import get_dashboard_stats, mark_as_won, start_estimation
from apps.core.json_utils import json_for_script


def _project_list_queryset(request, *, use_get=True):
    """案件一覧の絞り込み・並び順を適用したクエリを返す。

    一覧画面と、詳細画面の「前の案件／次の案件」で同じ並びを使うための共通部分。
    use_get=False のときは GET を見ず、セッションに保存した絞り込みだけを使う
    （詳細画面から呼ぶときにセッションを書き換えないため）。

    Returns:
        (queryset, {"q": str, "status": str, "region": str, "sort": str})
    """
    from django.utils import timezone
    now = timezone.now()
    qs = BidProject.objects.order_by("-created_at")

    # 入札期限切れかつ未確定の案件を除外（確定済みは表示）
    settled = [BidProject.Status.BID, BidProject.Status.WON, BidProject.Status.LOST]
    qs = qs.exclude(
        Q(deadline__lt=now) & ~Q(status__in=settled)
    )
    # 期限不明（deadline NULL）で取得から60日以上経過した案件も除外
    cutoff = now - datetime.timedelta(days=60)
    qs = qs.exclude(
        Q(deadline__isnull=True) & Q(created_at__lt=cutoff) & ~Q(status__in=settled)
    )

    # 検索フィルタ: GETパラメータがあればセッションに保存、なければセッションから復元
    if use_get and "reset" in request.GET:
        request.session.pop("bid_filter_q", None)
        request.session.pop("bid_filter_status", None)
        request.session.pop("bid_filter_region", None)
        q, status, region = "", "", ""
    elif use_get and request.GET:
        q = request.GET.get("q", "").strip()
        status = request.GET.get("status", "").strip()
        region = request.GET.get("region", "").strip()
        request.session["bid_filter_q"] = q
        request.session["bid_filter_status"] = status
        request.session["bid_filter_region"] = region
    else:
        q = request.session.get("bid_filter_q", "")
        status = request.session.get("bid_filter_status", "")
        region = request.session.get("bid_filter_region", "")

    if q:
        qs = qs.filter(Q(title__icontains=q) | Q(client__icontains=q))
    if status:
        qs = qs.filter(status=status)
    if region:
        qs = qs.filter(region__icontains=region)

    # ソート
    if use_get:
        sort = request.GET.get("sort", "").strip()
        if sort:
            request.session["bid_sort"] = sort
        elif not request.GET or "reset" in request.GET:
            request.session.pop("bid_sort", None)
            sort = ""
        else:
            sort = request.session.get("bid_sort", "")
    else:
        sort = request.session.get("bid_sort", "")

    SORT_MAP = {
        "deadline": "deadline",
        "-deadline": "-deadline",
        "category": "category",
        "-category": "-category",
        "announced": "announced_on",
        "-announced": "-announced_on",
        "created": "created_at",
        "-created": "-created_at",
    }
    order_field = SORT_MAP.get(sort)
    if order_field:
        qs = qs.order_by(order_field, "-created_at")
    else:
        # デフォルト: 公告日の新しい順（nullは末尾）
        from django.db.models import F
        qs = qs.order_by(F("announced_on").desc(nulls_last=True), "-created_at")

    return qs, {"q": q, "status": status, "region": region, "sort": sort}


def _neighbor_projects(request, project):
    """詳細画面の「前の案件／次の案件」。一覧と同じ絞り込み・並び順で隣を探す。

    一覧に出ない案件（期限切れなど）を開いているときは全件を登録順で辿る。
    """
    qs, _ = _project_list_queryset(request, use_get=False)
    pks = list(qs.values_list("pk", flat=True))
    if project.pk not in pks:
        pks = list(BidProject.objects.order_by("-created_at").values_list("pk", flat=True))
    if project.pk not in pks:
        return None, None
    i = pks.index(project.pk)
    prev_pk = pks[i - 1] if i > 0 else None
    next_pk = pks[i + 1] if i + 1 < len(pks) else None
    return prev_pk, next_pk


@login_required
def project_list(request):
    qs, filters = _project_list_queryset(request)
    q, status, region, sort = (
        filters["q"], filters["status"], filters["region"], filters["sort"],
    )

    # 一覧の資格バッジ用。資格マスタは1回だけ読む
    projects = list(qs)
    checks = check_qualifications_for_projects(projects, request.user.company)
    for project in projects:
        project.qual_check = checks[project.pk]

    return render(request, "bids/project_list.html", {
        "projects": projects,
        "q": q,
        "status": status,
        "region": region,
        "sort": sort,
        "status_choices": BidProject.Status.choices,
    })


@login_required
def project_detail(request, pk):
    project = get_object_or_404(BidProject, pk=pk)
    cost = getattr(project, "cost", None)
    competitors = project.competitors.all()
    qual_check = check_qualifications_for_projects(
        [project], request.user.company,
    )[project.pk]
    prev_pk, next_pk = _neighbor_projects(request, project)
    # 公告の別表から取った手続き日程を、公告→開札の流れとして図に起こす
    gantt = build_bid_gantt(project)
    return render(request, "bids/project_detail.html", {
        "project": project,
        "cost": cost,
        "competitors": competitors,
        "qual_check": qual_check,
        "prev_pk": prev_pk,
        "next_pk": next_pk,
        "gantt": gantt,
        "gantt_json": json_for_script(gantt["tasks"]),
        "kind_choices": BidScheduleRule.Kind.choices,
        "has_overrides": bool(project.schedule_overrides),
    })


@login_required
def project_delete(request, pk):
    """案件を削除する（POST のみ。画面側で確認ダイアログを出す）。

    原価・競合の記録は一緒に消える。見積（estimation）側の紐づけは外れるだけで残る。
    """
    project = get_object_or_404(BidProject, pk=pk)
    if request.method != "POST":
        return redirect("bids:project_detail", pk=pk)
    title = project.title
    project.delete()
    messages.success(request, f"案件「{title[:40]}」を削除しました。")
    return redirect("bids:project_list")


@login_required
def project_create(request):
    if request.method == "POST":
        form = BidProjectForm(request.POST)
        cost_form = BidCostForm(request.POST, prefix="cost")
        if form.is_valid() and cost_form.is_valid():
            project = form.save(commit=False)
            project.company = request.user.company
            project.created_by = request.user
            project.save()
            cost = cost_form.save(commit=False)
            cost.project = project
            cost.company = request.user.company
            cost.created_by = request.user
            cost.save()
            return redirect("bids:project_detail", pk=project.pk)
    else:
        form = BidProjectForm()
        cost_form = BidCostForm(prefix="cost")
    return render(request, "bids/project_form.html", {
        "form": form,
        "cost_form": cost_form,
    })


@login_required
def project_edit(request, pk):
    project = get_object_or_404(BidProject, pk=pk)
    cost = getattr(project, "cost", None)
    if request.method == "POST":
        form = BidProjectForm(request.POST, instance=project)
        cost_form = BidCostForm(request.POST, prefix="cost", instance=cost)
        if form.is_valid() and cost_form.is_valid():
            form.save()
            cost_obj = cost_form.save(commit=False)
            cost_obj.project = project
            cost_obj.company = request.user.company
            if not cost_obj.pk:
                cost_obj.created_by = request.user
            cost_obj.save()
            return redirect("bids:project_detail", pk=project.pk)
    else:
        form = BidProjectForm(instance=project)
        cost_form = BidCostForm(prefix="cost", instance=cost)
    return render(request, "bids/project_form.html", {
        "form": form,
        "cost_form": cost_form,
    })


@login_required
@require_POST
def schedule_override(request, pk):
    """ガントチャート上の手直し（扱い・日付）を、その案件だけの設定として保存する。

    バーのドラッグと、設定パネルの選択から呼ぶ。公告から読んだ bid_schedule は
    触らず差分だけ別に持つので、fetch_announcements で取り直しても消えない。

    POST:
        label     … 公告の項目ラベル（設定のキー）
        kind      … deadline / period / hidden / auto（auto は既定に戻す）
        start,end … YYYY-MM-DD。ドラッグで動かした位置
        reset     … その項目の手直しを消す
        reset_all … 案件の手直しを全部消す
    """
    project = get_object_or_404(BidProject, pk=pk)
    overrides = dict(project.schedule_overrides or {})

    if request.POST.get("reset_all"):
        overrides = {}
    else:
        label = request.POST.get("label", "").strip()
        if not label:
            return JsonResponse(
                {"ok": False, "error": "項目が指定されていません"}, status=400,
            )
        if request.POST.get("reset"):
            overrides.pop(label, None)
        else:
            entry = dict(overrides.get(label) or {})
            kind = request.POST.get("kind", "")
            if kind in KINDS:
                entry["kind"] = kind
            elif kind == "auto":
                # 会社の既定・自動判定に戻す。日付の手直しはそのまま残す。
                entry.pop("kind", None)

            for key in ("start", "end"):
                value = request.POST.get(key, "").strip()
                if not value:
                    continue
                try:
                    datetime.date.fromisoformat(value)
                except ValueError:
                    return JsonResponse(
                        {"ok": False, "error": f"{key} の日付が不正です"}, status=400,
                    )
                entry[key] = value

            # 中身が空になったら項目ごと消す。「手直しあり」の印を残さないため。
            if entry:
                overrides[label] = entry
            else:
                overrides.pop(label, None)

    project.schedule_overrides = overrides
    project.save(update_fields=["schedule_overrides", "updated_at"])
    return JsonResponse({"ok": True})


@login_required
def schedule_rule_list(request):
    """会社共通の既定。段階ごとに締切／期間／図に出さないを選ぶ。

    ここで決めた扱いが全案件のガントチャートに効く。
    案件ごとの例外は詳細画面（schedule_override）で上書きする。
    """
    company = request.user.company

    if request.method == "POST":
        stages = request.POST.getlist("stage")
        kinds = request.POST.getlist("kind")
        for stage, kind in zip(stages, kinds, strict=False):
            stage = stage.strip()
            if not stage:
                continue
            if kind not in KINDS:
                # 「自動判定にまかせる」＝既定を持たない
                BidScheduleRule.objects.filter(stage=stage).delete()
                continue
            rule, created = BidScheduleRule.objects.get_or_create(
                company=company, stage=stage,
                defaults={"kind": kind, "created_by": request.user},
            )
            if not created and rule.kind != kind:
                rule.kind = kind
                rule.save(update_fields=["kind", "updated_at"])
        messages.success(request, "手続きの扱いを保存しました")
        return redirect("bids:schedule_rule_list")

    current = {rule.stage: rule.kind for rule in BidScheduleRule.objects.all()}
    # 公告に出てくる段階（既知）＋ 過去に設定した段階
    stages = KNOWN_STAGES + [s for s in sorted(current) if s not in KNOWN_STAGES]
    return render(request, "bids/schedule_rules.html", {
        "rows": [{"stage": s, "kind": current.get(s, "")} for s in stages],
        "kind_choices": BidScheduleRule.Kind.choices,
    })


@login_required
def bid_start_estimation(request, pk):
    """案件を検討中にし、見積中の現場を用意する（登録済みならそれを使う）。"""
    if request.method != "POST":
        return redirect("bids:project_detail", pk=pk)

    project = get_object_or_404(BidProject, pk=pk)
    site, created = start_estimation(project, created_by=request.user)
    if created:
        messages.success(request, f"現場「{site.name}」を見積中として登録しました。")
    else:
        messages.info(request, f"現場「{site.name}」は登録済みです。")
    return redirect("bids:project_list")


@login_required
def qualification_list(request):
    qs = Qualification.objects.all()
    today = datetime.date.today()
    alert_2month = today + datetime.timedelta(days=60)
    alert_1month = today + datetime.timedelta(days=30)
    alert_2week = today + datetime.timedelta(days=14)
    return render(request, "bids/qualification_list.html", {
        "qualifications": qs,
        "unified_qualifications": UnifiedQualification.objects.all(),
        "today": today,
        "alert_2month": alert_2month,
        "alert_1month": alert_1month,
        "alert_2week": alert_2week,
    })


@login_required
def qualification_import(request):
    """Excel/PDFから入札参加資格を一括インポート。"""
    preview = None
    filename = ""

    if request.method == "POST":
        # 確定インポート
        if "confirm_import" in request.POST:
            import json

            records = json.loads(request.POST.get("records_json", "[]"))
            replace_all = request.POST.get("replace_all") == "1"

            if replace_all:
                Qualification.objects.all().delete()

            count = 0
            for rec in records:
                Qualification.objects.create(
                    company=request.user.company,
                    created_by=request.user,
                    issuer=rec.get("issuer") or "不明",
                    category=rec.get("category") or "",
                    grade=rec.get("grade") or "",
                    keisin_score=rec.get("keisin_score"),
                    total_score=rec.get("total_score"),
                    vendor_number=rec.get("vendor_number") or "",
                    valid_from=rec.get("valid_from") or None,
                    valid_until=rec.get("valid_until") or None,
                    application_type=rec.get("application_type") or "",
                    application_method=rec.get("application_method") or "",
                )
                count += 1

            action = "置換" if replace_all else "追加"
            messages.success(request, f"{count}件の資格を{action}インポートしました。")
            return redirect("bids:qualification_list")

        # ファイルアップロード → プレビュー
        uploaded = request.FILES.get("file")
        if uploaded:
            from apps.bids.importer import import_excel, import_pdf

            suffix = Path(uploaded.name).suffix.lower()
            filename = uploaded.name

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                for chunk in uploaded.chunks():
                    tmp.write(chunk)
                tmp_path = tmp.name

            try:
                if suffix in (".xlsx", ".xls"):
                    preview = import_excel(tmp_path)
                elif suffix == ".pdf":
                    preview = import_pdf(tmp_path)
                else:
                    messages.error(request, "Excel(.xlsx) または PDF(.pdf) のみ対応しています。")
            except Exception as e:
                messages.error(request, f"ファイル読み込みエラー: {e}")
            finally:
                Path(tmp_path).unlink(missing_ok=True)

    import json
    return render(request, "bids/qualification_import.html", {
        "preview": preview,
        "preview_json": json.dumps(preview, ensure_ascii=False) if preview else "[]",
        "filename": filename,
        "count": len(preview) if preview else 0,
    })


@login_required
def qualification_create(request):
    if request.method == "POST":
        form = QualificationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            return redirect("bids:qualification_list")
    else:
        form = QualificationForm()
    return render(request, "bids/qualification_form.html", {"form": form})


@login_required
def qualification_edit(request, pk):
    obj = get_object_or_404(Qualification, pk=pk)
    if request.method == "POST":
        form = QualificationForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect("bids:qualification_list")
    else:
        form = QualificationForm(instance=obj)
    return render(request, "bids/qualification_form.html", {"form": form})


@login_required
def qualification_delete(request, pk):
    obj = get_object_or_404(Qualification, pk=pk)
    if request.method == "POST":
        name = f"{obj.issuer} / {obj.category}"
        obj.delete()
        messages.success(request, f"資格「{name}」を削除しました。")
    return redirect("bids:qualification_list")


@login_required
def skipped_list(request):
    """資格判定で見送った案件の一覧。理由を開いて公告と照らせるようにする。"""
    from apps.bids.models import ScrapeTarget

    qs = SkippedBid.objects.select_related("target")
    verdict = request.GET.get("verdict", "")
    if verdict in SkippedBid.Verdict.values:
        qs = qs.filter(verdict=verdict)
    target_id = request.GET.get("target", "")
    if target_id.isdigit():
        qs = qs.filter(target_id=int(target_id))

    # 期限が近い順。期限不明は末尾
    from django.db.models import F

    qs = qs.order_by(F("deadline").asc(nulls_last=True), "-last_seen_at")

    # 公告が求める資格の隣に、自社の関係する資格を並べる（資格マスタは1回だけ読む）
    from apps.bids.qualification import related_qualifications

    # unscoped: company を明示指定
    qualifications = list(Qualification.unscoped.filter(company=request.user.company))
    skipped = list(qs)
    for item in skipped:
        item.ours = related_qualifications(
            item.required_issuer_type, item.required_category, qualifications,
        )

    return render(request, "bids/skipped_list.html", {
        "skipped": skipped,
        "verdict": verdict,
        "target_id": target_id,
        "verdict_choices": SkippedBid.Verdict.choices,
        "targets": ScrapeTarget.objects.filter(only_eligible=True).order_by("name"),
        "ineligible_count": SkippedBid.objects.filter(
            verdict=SkippedBid.Verdict.INELIGIBLE
        ).count(),
        "unknown_count": SkippedBid.objects.filter(
            verdict=SkippedBid.Verdict.UNKNOWN
        ).count(),
    })


@login_required
def skipped_delete(request, pk):
    """確認済みの見送り案件を一覧から消す。次の取り込みで再び見送られれば戻る。"""
    obj = get_object_or_404(SkippedBid, pk=pk)
    if request.method == "POST":
        obj.delete()
        messages.success(request, f"見送り案件「{obj.title[:30]}」を一覧から消しました。")
    return redirect("bids:skipped_list")


@login_required
def unified_qualification_create(request):
    if request.method == "POST":
        form = UnifiedQualificationForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            return redirect("bids:qualification_list")
    else:
        form = UnifiedQualificationForm()
    return render(request, "bids/unified_qualification_form.html", {"form": form})


@login_required
def unified_qualification_edit(request, pk):
    obj = get_object_or_404(UnifiedQualification, pk=pk)
    if request.method == "POST":
        form = UnifiedQualificationForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect("bids:qualification_list")
    else:
        form = UnifiedQualificationForm(instance=obj)
    return render(request, "bids/unified_qualification_form.html", {"form": form})


@login_required
def unified_qualification_delete(request, pk):
    obj = get_object_or_404(UnifiedQualification, pk=pk)
    if request.method == "POST":
        name = obj.agency
        obj.delete()
        messages.success(request, f"全省庁統一資格「{name}」を削除しました。")
    return redirect("bids:qualification_list")


@login_required
def unit_price_list(request):
    qs = UnitPrice.objects.all()
    return render(request, "bids/unit_price_list.html", {"unit_prices": qs})


@login_required
def unit_price_create(request):
    if request.method == "POST":
        form = UnitPriceForm(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.company = request.user.company
            obj.created_by = request.user
            obj.save()
            return redirect("bids:unit_price_list")
    else:
        form = UnitPriceForm()
    return render(request, "bids/unit_price_form.html", {"form": form})


@login_required
def unit_price_edit(request, pk):
    obj = get_object_or_404(UnitPrice, pk=pk)
    if request.method == "POST":
        form = UnitPriceForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            return redirect("bids:unit_price_list")
    else:
        form = UnitPriceForm(instance=obj)
    return render(request, "bids/unit_price_form.html", {"form": form})


@login_required
def bid_dashboard(request):
    """入札ダッシュボード。受注率・月別件数・地域別分布。"""
    stats = get_dashboard_stats(request.user.company)
    return render(request, "bids/dashboard.html", {
        "stats": stats,
        "by_month_json": json.dumps(stats["by_month"], ensure_ascii=False),
    })


@login_required
def bid_mark_won(request, pk):
    """案件を落札にし、現場を受注済にする（登録済みの現場があればそれを使う）。"""
    if request.method != "POST":
        return redirect("bids:project_detail", pk=pk)

    project = get_object_or_404(BidProject, pk=pk)
    site, created = mark_as_won(project, created_by=request.user)
    if created:
        messages.success(request, f"落札しました。現場「{site.name}」を自動作成しました。")
    else:
        messages.success(request, f"落札しました。登録済みの現場「{site.name}」に反映しました。")
    return redirect("bids:project_detail", pk=pk)


# ---------------------------------------------------------------------------
# スクレイピングターゲット管理
# ---------------------------------------------------------------------------


@login_required
def scrape_target_list(request):
    """スクレイピング対象の一覧。"""
    from apps.bids.models import ScrapeTarget

    targets = ScrapeTarget.objects.order_by("-is_active", "name")
    return render(request, "bids/scrape_target_list.html", {
        "targets": targets,
    })


@login_required
def scrape_target_create(request):
    """スクレイピング対象の追加。"""
    from apps.bids.forms import ScrapeTargetForm

    if request.method == "POST":
        form = ScrapeTargetForm(request.POST)
        if form.is_valid():
            target = form.save(commit=False)
            target.company = request.user.company
            target.created_by = request.user
            target.save()
            messages.success(request, f"スクレイピング対象「{target.name}」を追加しました。")
            return redirect("bids:scrape_target_list")
    else:
        form = ScrapeTargetForm()
    return render(request, "bids/scrape_target_form.html", {
        "form": form, "is_new": True,
    })


@login_required
def scrape_target_edit(request, pk):
    """スクレイピング対象の編集。"""
    from apps.bids.forms import ScrapeTargetForm
    from apps.bids.models import ScrapeTarget

    target = get_object_or_404(ScrapeTarget, pk=pk)
    if request.method == "POST":
        form = ScrapeTargetForm(request.POST, instance=target)
        if form.is_valid():
            form.save()
            messages.success(request, f"「{target.name}」を更新しました。")
            return redirect("bids:scrape_target_list")
    else:
        form = ScrapeTargetForm(instance=target)
    return render(request, "bids/scrape_target_form.html", {
        "form": form, "is_new": False, "target": target,
    })


@login_required
def scrape_run(request, pk):
    """手動でスクレイピングを実行する。"""
    from apps.bids.models import ScrapeTarget
    from apps.bids.services import run_scrape

    if request.method != "POST":
        return redirect("bids:scrape_target_list")

    target = get_object_or_404(ScrapeTarget, pk=pk)
    result = run_scrape(target, request.user.company)

    if result["errors"]:
        messages.warning(
            request,
            f"「{target.name}」: 新規{result['new']}件, エラー{len(result['errors'])}件",
        )
    else:
        messages.success(
            request,
            f"「{target.name}」: 新規{result['new']}件取得, "
            f"既存{result.get('updated', 0)}件を補完, "
            f"公告{result.get('outlined', 0)}件から工事概要・参加要件を取得 "
            f"(スキップ{result['skipped']}件, 対象外{result.get('excluded', 0)}件)",
        )
    return redirect("bids:scrape_target_list")


@login_required
def scrape_run_all(request):
    """全ターゲットを一括スクレイピング。"""
    from apps.bids.services import run_all_scrapes

    if request.method != "POST":
        return redirect("bids:scrape_target_list")

    result = run_all_scrapes(request.user.company)
    messages.success(
        request,
        f"一括取得完了: {result['targets_processed']}サイト処理, "
        f"新規{result['total_new']}件",
    )
    return redirect("bids:scrape_target_list")

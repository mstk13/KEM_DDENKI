"""現場の提出書類（ADR-0065）。

- 会社ごとに「最初の書類リスト」（DocumentTemplate）を持つ。1件も無ければ既定の書類を入れる
- 現場の書類の一覧を初めて開いたときに、そのときの最初のリストを現場へ写す（SiteDocument）。
  あとで会社のリストを変えても、写し済みの現場は変わらない（次に開く現場から変わる）
- リストに無い書類は、名前を付けて現場に足せる。次の現場からも最初のリストに入れることもできる
- 書類ごとに PDF と Excel のファイルを何件でも置ける（SiteDocumentFile）。差し替え前の版も残る
- 受け付けるのは PDF（.pdf）と Excel（.xlsx・.xls）だけ。拡張子と中身の先頭の形の両方で確かめる
"""

import zipfile
from pathlib import Path

from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q

from apps.sites.models import DocumentPhase, DocumentTemplate, SiteDocument, SiteDocumentFile

# 1件の大きさと、一度に登録できる件数。完成図書などスキャンした PDF は大きくなるので広めにとる
MAX_DOCUMENT_FILE_MB = 50
MAX_DOCUMENT_FILES_PER_UPLOAD = 10

# 最初の書類リストの既定。会社の Excel「現場ごとの書類一覧.xlsx」のシートと
# 「別紙添付目次」から作った（プロダクトオーナー確認 2026-09-15）。
# 会社ごとの行として入れるので、あとから管理画面で変えられる
DEFAULT_DOCUMENTS = (
    (
        DocumentPhase.START,
        (
            "施工計画書",
            "工事工程表",
            "施工体制台帳",
            "作業員名簿",
            "施工体系図",
            "緊急連絡先",
            "工事使用材料届",
            "承諾図（御承諾用図面）",
            "納入仕様書",
        ),
    ),
    (
        DocumentPhase.DURING,
        (
            "安全作業確認書（新規入場者）",
            "KY用紙",
            "安全パトロール記録",
            "施工チェックシート",
            "危険作業安全チェックシート",
        ),
    ),
    (
        DocumentPhase.COMPLETION,
        (
            "絶縁抵抗・絶縁耐力・接地抵抗 測定記録",
            "絶縁・電圧測定記録",
            "社内検査書",
            "工事写真",
            "施工図",
            "産業廃棄物処理",
            "完成図書",
        ),
    ),
    (
        DocumentPhase.OTHER,
        (
            "技能講習証明書・資格証の写し",
            "建設業許可証・労災保険関係成立票",
            "登録内容確認書（工事実績）",
        ),
    ),
)

# 拡張子ごとの種類と、開くときの Content-Type
FILE_TYPES = {
    ".pdf": (SiteDocumentFile.Kind.PDF, "application/pdf"),
    ".xlsx": (
        SiteDocumentFile.Kind.EXCEL,
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ),
    ".xls": (SiteDocumentFile.Kind.EXCEL, "application/vnd.ms-excel"),
}
# ファイルを選ぶ画面で、PDF と Excel だけを出す
ACCEPT_ATTR = ",".join([*FILE_TYPES, *(content_type for _, content_type in FILE_TYPES.values())])

# .xls（と、パスワード付きの .xlsx）の入れ物の先頭
_OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


class UnsupportedDocumentFile(ValueError):
    """PDF・Excel ではないファイル。"""


def _read_head(uploaded, size: int) -> bytes:
    uploaded.seek(0)
    try:
        return uploaded.read(size)
    finally:
        uploaded.seek(0)


def _is_xlsx_zip(uploaded) -> bool:
    uploaded.seek(0)
    try:
        with zipfile.ZipFile(uploaded) as archive:
            names = archive.namelist()
    except (zipfile.BadZipFile, OSError, ValueError):
        return False
    finally:
        uploaded.seek(0)
    return "[Content_Types].xml" in names and any(name.startswith("xl/") for name in names)


def detect_file_kind(uploaded) -> str:
    """PDF か Excel かを返す。どちらでもなければ UnsupportedDocumentFile。

    拡張子だけ変えたファイル（写真や Word を .pdf にしたもの）を通さないよう、中身の先頭も見る。
    """
    suffix = Path(uploaded.name or "").suffix.lower()
    if suffix not in FILE_TYPES:
        raise UnsupportedDocumentFile(
            "PDF（.pdf）か Excel（.xlsx・.xls）のファイルを選んでください"
        )
    head = _read_head(uploaded, 1024)
    if suffix == ".pdf":
        # PDF の印は先頭 1024 バイトのどこかにあればよい（規格上、前に余計なものが付くことがある）
        matches = b"%PDF-" in head
    elif suffix == ".xls":
        matches = head.startswith(_OLE_MAGIC)
    else:
        # パスワード付きの .xlsx は ZIP ではなく、.xls と同じ入れ物になる
        matches = head.startswith(_OLE_MAGIC) or _is_xlsx_zip(uploaded)
    if not matches:
        raise UnsupportedDocumentFile(
            "中身が PDF・Excel ではありません（拡張子だけ変えたファイルは登録できません）"
        )
    return FILE_TYPES[suffix][0]


def content_type_for(name: str) -> str:
    entry = FILE_TYPES.get(Path(name).suffix.lower())
    return entry[1] if entry else "application/octet-stream"


def ensure_default_templates(company) -> None:
    """会社に最初の書類リストが1件も無ければ、既定の書類を入れる。

    外した（is_active=False）書類も「ある」に数える。全部外した会社に既定を戻さないため。
    現場の会社で絞るので、テナントの文脈に頼らない unscoped を使う（以下も同じ）。
    """
    if DocumentTemplate.unscoped.filter(company=company).exists():
        return
    order = 0
    for phase, names in DEFAULT_DOCUMENTS:
        for name in names:
            order += 10
            DocumentTemplate.unscoped.get_or_create(
                company=company,
                name=name,
                defaults={"phase": phase, "display_order": order},
            )


def ensure_site_documents(site) -> None:
    """現場の書類の一覧を初めて開いたときに、会社の最初のリストを写す。

    写すのは1回だけ。最初のリストの書類は消せない（「不要」にする）ので、
    1件でもあれば写し済みとみなせる。
    """
    if SiteDocument.unscoped.filter(site=site).exists():
        return
    ensure_default_templates(site.company)
    templates = DocumentTemplate.unscoped.filter(
        company=site.company, is_active=True
    ).order_by("display_order", "pk")
    for template in templates:
        # 同時に2人が初めて開いても、同じ名前は1件にする（get_or_create が重なりを吸収する）
        SiteDocument.unscoped.get_or_create(
            site=site,
            name=template.name,
            defaults={
                "company": site.company,
                "template": template,
                "phase": template.phase,
                "display_order": template.display_order,
            },
        )


def site_documents(site):
    """現場の書類。並び順どおりで、ファイルを新しい順に file_list に持つ。"""
    return (
        SiteDocument.unscoped.filter(site=site)
        .prefetch_related(
            Prefetch(
                "files",
                queryset=SiteDocumentFile.unscoped.order_by("-created_at", "-pk"),
                to_attr="file_list",
            )
        )
        .order_by("display_order", "pk")
    )


def grouped_documents(site) -> list[dict]:
    """時期（着工時・施工中・完成時・その他）ごとに分ける。"""
    by_phase = {value: [] for value in DocumentPhase.values}
    for document in site_documents(site):
        by_phase.setdefault(document.phase, []).append(document)
    return [
        {"value": value, "label": label, "documents": by_phase[value]}
        for value, label in DocumentPhase.choices
    ]


def document_progress(site) -> dict:
    """状況ごとの数。「不要」にした書類は total に入れない。"""
    status = SiteDocument.Status
    return SiteDocument.unscoped.filter(site=site).aggregate(
        total=Count("pk", filter=~Q(status=status.NOT_REQUIRED)),
        submitted=Count("pk", filter=Q(status=status.SUBMITTED)),
        prepared=Count("pk", filter=Q(status=status.PREPARED)),
        not_started=Count("pk", filter=Q(status=status.NOT_STARTED)),
        not_required=Count("pk", filter=Q(status=status.NOT_REQUIRED)),
    )


def pending_documents(site, limit: int = 5):
    """まだ提出していない書類（未作成・作成済み）を並び順に。現場詳細で名前を出す。"""
    status = SiteDocument.Status
    return list(
        SiteDocument.unscoped.filter(site=site, status__in=[status.NOT_STARTED, status.PREPARED])
        .order_by("display_order", "pk")[:limit]
    )


def normalize_name(name: str) -> str:
    """書類名の前後の空白を落とし、続いた空白を1つにする（同じ名前を見分けるため）。"""
    return " ".join((name or "").split())


def add_site_document(site, *, name, phase, user=None, add_to_company_list=False):
    """リストに無い書類を現場に足す。

    add_to_company_list なら会社の最初のリストにも入れる（外してあった同じ名前の書類は戻す）。
    足した書類はどちらの場合も、この現場では消せる（is_custom）。
    """
    name = normalize_name(name)
    with transaction.atomic():
        template = None
        if add_to_company_list:
            template = DocumentTemplate.unscoped.filter(company=site.company, name=name).first()
            if template is None:
                last = DocumentTemplate.unscoped.filter(company=site.company).aggregate(
                    last=Max("display_order")
                )["last"]
                template = DocumentTemplate.unscoped.create(
                    company=site.company,
                    name=name,
                    phase=phase,
                    display_order=(last or 0) + 10,
                    created_by=user,
                )
            elif not template.is_active:
                template.is_active = True
                template.phase = phase
                template.save(update_fields=["is_active", "phase", "updated_at"])
        last = SiteDocument.unscoped.filter(site=site).aggregate(last=Max("display_order"))["last"]
        return SiteDocument.unscoped.create(
            company=site.company,
            site=site,
            template=template,
            name=name,
            phase=phase,
            display_order=(last or 0) + 10,
            is_custom=True,
            created_by=user,
        )


def save_document_files(document, uploads, *, note="", user=None) -> list:
    """ファイルを書類に置く。uploads は (ファイル, 種類) の組。

    書類が「未作成」なら「作成済み」にする（ファイルを置いた = 作った、とみなす）。
    何件かのうち途中で失敗したら、どれも登録しない。
    """
    with transaction.atomic():
        created = [
            SiteDocumentFile.unscoped.create(
                company=document.company,
                document=document,
                file=uploaded,
                kind=kind,
                original_filename=Path(uploaded.name).name[:255],
                size=uploaded.size or 0,
                note=note,
                created_by=user,
            )
            for uploaded, kind in uploads
        ]
        if created and document.status == SiteDocument.Status.NOT_STARTED:
            document.status = SiteDocument.Status.PREPARED
            document.save(update_fields=["status", "updated_at"])
    return created

"""入札参加資格の登録内容を原本（入札案件参加資格.pdf）と照らし合わせ、違いを直す（ADR-0063）。

使い方:
    python manage.py verify_qualifications
        違いを出すだけ（何も変えない）
    python manage.py verify_qualifications --apply
        違いを直し、足りない資格を登録する
    python manage.py verify_qualifications --apply --delete-extra
        原本に無い行・重複も消す

発注機関は括弧・空白の違い、業種区分は末尾の「工事」の有無を同じとみなして行を突き合わせる
（資格の判定と同じ正規化）。突き合わせた行の項目は原本と 1 文字でも違えば直す。
"""

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.bids import qualification_source as src
from apps.bids.models import Qualification, UnifiedQualification
from apps.bids.qualification import normalize_category, normalize_issuer
from apps.tenants.models import Company

CHANGE_REASON = f"原本（{src.SOURCE_NAME}）と照合して修正"

# 照らし合わせる項目（発注機関は突き合わせに使うので直さない）
QUALIFICATION_FIELDS = [
    ("category", "業種区分"),
    ("grade", "等級"),
    ("keisin_score", "経審点"),
    ("total_score", "総合点"),
    ("vendor_number", "業者番号"),
    ("valid_from", "有効開始日"),
    ("valid_until", "有効期限"),
    ("application_type", "申請種別"),
    ("memo", "メモ"),
]


def row_key(issuer, category):
    return (normalize_issuer(issuer), normalize_category(category))


def _blank_as_empty(value):
    return "" if value is None else value


def _show(value):
    if value is None or value == "":
        return "（空欄）"
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _items(text):
    return {p.strip() for p in re.split(r"[/／、，,\n]", text or "") if p.strip()}


def _describe(row):
    return (
        f"等級 {_show(row['grade'])}・経審 {_show(row['keisin_score'])}・"
        f"総合 {_show(row['total_score'])}・業者番号 {_show(row['vendor_number'])}・"
        f"{_show(row['valid_from'])}～{_show(row['valid_until'])}"
    )


class Command(BaseCommand):
    help = "入札参加資格の登録内容を原本と照らし合わせ、違いを直す"

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply", action="store_true", help="違いを直し、足りない資格を登録する",
        )
        parser.add_argument(
            "--delete-extra", action="store_true",
            help="（--apply と一緒に）原本に無い行・重複した行を消す",
        )
        parser.add_argument(
            "--company", type=int, default=None, help="対象の会社ID（省略時は最初の会社）",
        )

    def handle(self, *args, **options):
        if options["company"]:
            company = Company.objects.filter(pk=options["company"]).first()
        else:
            # 単一テナント運用を想定し、最初の会社を見る（ほかの資格コマンドと同じ）
            company = Company.objects.first()
        if not company:
            raise CommandError("会社データがありません。")
        apply = options["apply"]
        delete_extra = options["delete_extra"]
        if delete_extra and not apply:
            raise CommandError("--delete-extra は --apply と一緒に指定してください。")

        self.changes = []  # (対象, 項目, 修正前, 修正後)
        with transaction.atomic():
            extra = self._check_qualifications(company, apply, delete_extra)
            unified_count = self._check_unified(company, apply)
        self._report(company, apply, delete_extra, extra, unified_count)

    # 資格を直接触るのは管理コマンドで、会社を明示して絞るため unscoped を使う
    def _check_qualifications(self, company, apply, delete_extra):
        registered = {}
        for q in Qualification.unscoped.filter(company=company).order_by("pk"):
            registered.setdefault(row_key(q.issuer, q.category), []).append(q)

        extra = []
        for row in src.ALL_ROWS:
            found = registered.pop(row_key(row["issuer"], row["category"]), [])
            if not found:
                self.changes.append((
                    f"{row['issuer']} / {row['category']}", "（行の追加）", "（未登録）",
                    _describe(row),
                ))
                if apply:
                    q = Qualification(company=company, **row)
                    q._change_reason = CHANGE_REASON
                    q.save()
                continue

            q, duplicates = found[0], found[1:]
            extra += [(d, "重複") for d in duplicates]
            label = f"{q.issuer} / {q.category}（id={q.pk}）"
            dirty = False
            for field, name in QUALIFICATION_FIELDS:
                if field not in row:
                    continue
                before, after = getattr(q, field), row[field]
                if _blank_as_empty(before) != _blank_as_empty(after):
                    self.changes.append((label, name, _show(before), _show(after)))
                    setattr(q, field, after)
                    dirty = True
            if dirty and apply:
                q._change_reason = CHANGE_REASON
                q.save()

        for rest in registered.values():
            extra += [(q, "原本に無い") for q in rest]
        if apply and delete_extra:
            for q, _why in extra:
                q._change_reason = CHANGE_REASON
                q.delete()
        return extra

    def _check_unified(self, company, apply):
        agencies = list(
            UnifiedQualification.unscoped.filter(company=company).order_by("sort_order", "pk")
        )
        for u in agencies:
            label = f"全省庁統一資格（省庁別） {u.agency}（id={u.pk}）"
            dirty = False
            for field, expected in src.UNIFIED_AGENCY_VALUES:
                name = UnifiedQualification._meta.get_field(field).verbose_name
                before = getattr(u, field)
                if field.endswith("_items"):
                    after = "/".join(expected)
                    same = _items(before) == set(expected)
                else:
                    after = expected
                    same = _blank_as_empty(before) == _blank_as_empty(expected)
                if not same:
                    self.changes.append((label, name, _show(before), _show(after)))
                    setattr(u, field, after)
                    dirty = True
            if dirty and apply:
                u._change_reason = CHANGE_REASON
                u.save()
        return len(agencies)

    def _report(self, company, apply, delete_extra, extra, unified_count):
        write = self.stdout.write
        write(f"会社: {company.name} / 原本: {src.SOURCE_NAME}")
        write(
            f"原本の行: 入札参加資格 {len(src.ALL_ROWS)} 行 / "
            f"登録されている全省庁統一資格（省庁別）: {unified_count} 機関"
        )
        write("直しました" if apply else "確認だけです（何も変えていません。直すときは --apply）")
        write("")
        if self.changes:
            write(f"■ 違い {len(self.changes)} 件（対象 | 項目 | 修正前 → 修正後）")
            for target, item, before, after in self.changes:
                write(f"- {target} | {item} | {before} → {after}")
        else:
            write("■ 違いはありません")
        if extra:
            state = (
                "（消しました）" if apply and delete_extra
                else "（残しています。消すときは --apply --delete-extra）"
            )
            write("")
            write(f"■ 原本に無い・重複した登録 {len(extra)} 件{state}")
            for q, why in extra:
                write(
                    f"- [{why}] {q.issuer} / {q.category}（id={q.pk}） 等級 {_show(q.grade)}・"
                    f"経審 {_show(q.keisin_score)}・総合 {_show(q.total_score)}・"
                    f"業者番号 {_show(q.vendor_number)}"
                )
        write("")
        write("■ 原本で判断が要った箇所")
        for note in src.NOTES:
            write(f"- {note}")

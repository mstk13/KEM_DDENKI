"""二重に登録された現場を、片方に寄せる（ADR-0084）。

日報・原価・材料・工期・安全書類など、現場にぶら下がる行（22 種類）の
参照をまとめて付け替える。寄せたほうの現場は**消さない**。
`merged_into` を立てて残し、付け替えた行の id を候補に記録しておく。
間違えたときに取り消せるようにするため。

日報のように「現場・作業員・日付・工種」で一意になる行は、
付け替えると相手側とぶつかることがある（同じ日に両方の名前で書いていた場合）。
ぶつかった行は動かさずに残し、報告に出す。人が中身を見て決める。
"""

from __future__ import annotations

from django.db import IntegrityError, transaction
from django.utils import timezone


def _relations(Site):
    """現場を参照している関連（履歴テーブルは除く）。"""
    found = []
    for relation in Site._meta.get_fields():
        if not (relation.auto_created and not relation.concrete):
            continue
        model = relation.related_model
        if model is None or model._meta.label.startswith("sites.Historical"):
            continue
        if model._meta.label in ("sites.SiteMergeCandidate",):
            continue
        found.append((model, relation.field.name))
    return found


def merge_sites(primary, duplicate, *, user=None, candidate=None):
    """duplicate の行を primary に付け替え、duplicate を統合済みにする。

    Returns:
        {
          "moved": {"reports.DailyReport": 3, ...},   … 付け替えた件数
          "conflicts": [(モデル名, 件数)],             … ぶつかって動かせなかった行
          "moved_rows": {"reports.DailyReport": [1, 2]},  … 取り消し用
        }
    """
    if primary.pk == duplicate.pk:
        raise ValueError("同じ現場は統合できません。")
    if primary.company_id != duplicate.company_id:
        raise ValueError("会社が違う現場は統合できません。")

    from apps.sites.models import Site

    moved, conflicts, moved_rows = {}, [], {}

    with transaction.atomic():
        for model, field_name in _relations(Site):
            label = model._meta.label
            rows = list(
                model._base_manager.filter(**{field_name: duplicate})
                .values_list("pk", flat=True),
            )
            if not rows:
                continue

            ok = []
            for pk in rows:
                try:
                    with transaction.atomic():
                        model._base_manager.filter(pk=pk).update(
                            **{field_name: primary},
                        )
                except IntegrityError:
                    # 付け替えると相手側とぶつかる行（同じ日・同じ人の日報など）
                    continue
                ok.append(pk)

            if ok:
                moved[label] = len(ok)
                moved_rows[label] = ok
            if len(ok) < len(rows):
                conflicts.append((label, len(rows) - len(ok)))

        duplicate.merged_into = primary
        duplicate.merged_at = timezone.now()
        duplicate.save(update_fields=["merged_into", "merged_at", "updated_at"])

        if candidate is not None:
            from apps.sites.models import SiteMergeCandidate

            candidate.state = SiteMergeCandidate.State.MERGED
            candidate.primary = primary
            candidate.duplicate = duplicate
            candidate.decided_by = user
            candidate.decided_at = timezone.now()
            candidate.moved_rows = moved_rows
            candidate.save()

    return {"moved": moved, "conflicts": conflicts, "moved_rows": moved_rows}


def undo_merge(candidate, *, user=None):
    """統合を取り消す。記録した行だけを元の現場へ戻す。

    Returns:
        {"restored": {"reports.DailyReport": 3, ...}}
    """
    from django.apps import apps as django_apps

    from apps.sites.models import Site, SiteMergeCandidate

    duplicate = candidate.duplicate
    restored = {}

    with transaction.atomic():
        for label, pks in (candidate.moved_rows or {}).items():
            model = django_apps.get_model(label)
            field_name = next(
                name for _m, name in _relations(Site)
                if _m._meta.label == label
            )
            count = 0
            for pk in pks:
                try:
                    with transaction.atomic():
                        count += model._base_manager.filter(pk=pk).update(
                            **{field_name: duplicate},
                        )
                except IntegrityError:
                    continue
            if count:
                restored[label] = count

        duplicate.merged_into = None
        duplicate.merged_at = None
        duplicate.save(update_fields=["merged_into", "merged_at", "updated_at"])

        candidate.state = SiteMergeCandidate.State.PENDING
        candidate.decided_by = user
        candidate.decided_at = timezone.now()
        candidate.moved_rows = {}
        candidate.save()

    return {"restored": restored}

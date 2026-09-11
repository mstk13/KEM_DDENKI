"""出社予定を1日に複数件入れるときの検証と保存（ADR-0038）。

AttendPlan の1件は「1日の中の1つの予定（区分・行き先・時間帯）」。
午前は A 現場、午後は B 現場のように1日を時間で分けるときは2件にする。

分けた予定が読める形になるよう、次を守らせる。

  * 出張・有休・休み（時刻を持たない区分＝終日）は、その日1件だけ
  * 2件以上ある日は、どの予定にも開始・終了時刻を入れる
    （空欄は「所定どおり」なので、空欄同士は必ず重なってしまう）
  * 時間帯を重ねない。終了が開始以前の予定（夜間工事）は 24:00 までとして判定する

保存は「その人のその日の予定を、渡した並びに置き換える」。id が合う行は更新し、
id の無い予定には余っている行を使い回し、残った行は消す。使い回すのは、
区分を塗り替えるたびに行を作り直すと、変更履歴（simple-history）が
「削除と追加」になって追えなくなるため。
"""
from __future__ import annotations

import datetime
from dataclasses import dataclass
from itertools import pairwise

from django.db import transaction

from apps.attendance.models import AttendPlan, format_time_range

# 1人1日に入れられる予定の上限。「追加」を押し続けた入力や
# 壊れた送信で行を大量に作らないための歯止め。
MAX_ENTRIES_PER_DAY = 8

MINUTES_PER_DAY = 24 * 60


class EntryError(ValueError):
    """保存できない予定。メッセージはそのまま画面に出す。"""


@dataclass
class Entry:
    """保存前の予定1件。"""

    kind: str
    start_time: datetime.time | None = None
    end_time: datetime.time | None = None
    note: str = ""
    pk: int | None = None

    def values(self) -> dict:
        return {
            "kind": self.kind,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "note": self.note,
        }

    @property
    def minutes(self) -> tuple[int, int]:
        """0:00 からの (開始, 終了) の分。終了が開始以前なら 24:00 まで。"""
        start = self.start_time.hour * 60 + self.start_time.minute
        end = self.end_time.hour * 60 + self.end_time.minute
        if end <= start:
            end = MINUTES_PER_DAY
        return start, end

    @property
    def time_label(self) -> str:
        return format_time_range(self.start_time, self.end_time)


def parse_time(value) -> datetime.time | None:
    """入力された "HH:MM" を time にする。空なら None、読めなければ EntryError。"""
    value = str(value or "").strip()
    if not value:
        return None
    try:
        return datetime.time.fromisoformat(value)
    except ValueError:
        raise EntryError("時刻が不正です") from None


def make_entry(kind, start="", end="", note="", pk="") -> Entry:
    """画面から来た値を Entry にする。区分が不正・時刻が読めなければ EntryError。

    時刻を持たない区分（出張・有休・休み）に付いてきた時刻は捨てる。
    """
    kind = str(kind or "").strip()
    if kind not in AttendPlan.Kind.values:
        raise EntryError("区分が不正です")
    start_time = parse_time(start)
    end_time = parse_time(end)
    if not AttendPlan.KIND_FIELDS[kind]["time"]:
        start_time = end_time = None
    pk = str(pk or "").strip()
    return Entry(
        kind=kind,
        start_time=start_time,
        end_time=end_time,
        note=str(note or "").strip()[:200],
        pk=int(pk) if pk.isdigit() else None,
    )


def validate_entries(entries: list[Entry]) -> None:
    """1人1日ぶんの予定の組み合わせを確かめる。保存できなければ EntryError。"""
    if len(entries) > MAX_ENTRIES_PER_DAY:
        raise EntryError(f"1日に入れられる予定は {MAX_ENTRIES_PER_DAY} 件までです")
    if len(entries) < 2:
        return

    labels = dict(AttendPlan.Kind.choices)
    for entry in entries:
        if entry.kind in AttendPlan.ALL_DAY_KINDS:
            raise EntryError(
                f"{labels[entry.kind]}はその日1件だけにしてください"
                "（他の予定と同じ日には入れられません）"
            )
        if entry.start_time is None or entry.end_time is None:
            raise EntryError(
                "予定を2件以上に分けるときは、それぞれ開始・終了時刻を入れてください"
            )

    ordered = sorted(entries, key=lambda entry: entry.minutes)
    for before, after in pairwise(ordered):
        if after.minutes[0] < before.minutes[1]:
            raise EntryError(
                f"{before.time_label} と {after.time_label} の時間が重なっています"
            )


def save_day_entries(company, user, worker, day, entries: list[Entry]) -> tuple[int, int, int]:
    """worker の day の予定を entries に置き換える。(作成, 更新, 削除) の件数を返す。

    検証に通らなければ何も変えずに EntryError。entries が空ならその日の予定を消す。
    """
    validate_entries(entries)

    with transaction.atomic():
        # unscoped: plans.py と同じく company を引数で受けて明示的に絞る。
        existing = list(
            AttendPlan.unscoped.filter(company=company, worker=worker, plan_date=day)
            .order_by("start_time", "pk")
        )
        by_pk = {plan.pk: plan for plan in existing}
        targets = [by_pk.pop(entry.pk, None) for entry in entries]
        # id の無い予定（または別の日・別の人の id を持つ予定）には、余っている行を前から使う
        spare = [plan for plan in existing if plan.pk in by_pk]

        created = updated = 0
        for entry, plan in zip(entries, targets, strict=True):
            if plan is None and spare:
                plan = spare.pop(0)
            values = entry.values()
            if plan is None:
                AttendPlan.unscoped.create(
                    company=company, worker=worker, plan_date=day,
                    created_by=user, **values,
                )
                created += 1
            elif any(getattr(plan, field) != value for field, value in values.items()):
                for field, value in values.items():
                    setattr(plan, field, value)
                plan.save(update_fields=[*values, "updated_at"])
                updated += 1

        for plan in spare:
            plan.delete()

    return created, updated, len(spare)

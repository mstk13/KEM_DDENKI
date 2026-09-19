"""1件のデータについて「誰が・いつ・何を」直したかを組み立てる（ADR-0102 改訂）。

日報は現場ごとに複数人ぶんをまとめて登録・修正できる（ADR-0056）。その使い方を
残すため、他人の日報も直せるようにしてある。**抑止は権限ではなくログで行う**ので、
「誰がいつ何を直したか」がその画面ですぐ読めないと意味がない。

/audit-log/ は全モデルを横断して探す画面で、1件の履歴を追うには向かない。
こちらは1件ぶんを、直前の版との差分付きで出す。

simple-history の `diff_against` を使う。項目名は画面の言葉（verbose_name）に直し、
選択肢のある項目は表示用の値にする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class FieldChange:
    """1項目ぶんの変化。"""

    label: str
    old: str
    new: str


@dataclass
class ChangeEntry:
    """履歴1件（＝1回の保存）。"""

    at: Any
    who: str
    kind: str
    changes: list[FieldChange] = field(default_factory=list)
    is_first: bool = False


# 画面に出しても意味が無い、または他の項目から分かる項目。
_HIDDEN_FIELDS = frozenset({"id", "company", "created_at", "updated_at"})


def _display(instance, name: str) -> str:
    """項目の値を、画面の言葉にして返す。"""
    getter = getattr(instance, f"get_{name}_display", None)
    value = getter() if callable(getter) else getattr(instance, name, None)
    if value is None or value == "":
        return "（空）"
    return str(value)


def _label(model, name: str) -> str:
    try:
        return str(model._meta.get_field(name).verbose_name)
    except Exception:
        # 履歴にしか無い項目など。名前をそのまま出す
        return name


def build_change_log(instance, *, limit: int = 20) -> list[ChangeEntry]:
    """そのデータの変更履歴を新しい順に返す。

    Args:
        instance: simple-history の付いたモデルのインスタンス
        limit: 何回ぶんまで出すか。古い分は切る（画面が長くなりすぎないように）
    """
    history = getattr(instance, "history", None)
    if history is None:
        return []

    records = list(history.all()[: limit + 1])
    model = type(instance)
    entries: list[ChangeEntry] = []

    for index, record in enumerate(records[:limit]):
        who = str(record.history_user) if record.history_user_id else "（記録なし）"
        entry = ChangeEntry(
            at=record.history_date,
            who=who,
            kind=record.get_history_type_display(),
        )

        previous = records[index + 1] if index + 1 < len(records) else None
        if previous is None:
            # 最初の登録。何と比べる版も無いので、差分は出さない
            entry.is_first = True
        else:
            try:
                delta = record.diff_against(previous)
            except Exception:
                delta = None
            if delta is not None:
                for change in delta.changes:
                    if change.field in _HIDDEN_FIELDS:
                        continue
                    entry.changes.append(
                        FieldChange(
                            label=_label(model, change.field),
                            old=_display(previous, change.field),
                            new=_display(record, change.field),
                        )
                    )
        entries.append(entry)

    return entries

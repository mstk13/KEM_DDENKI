"""案件資料の PDF から、入札までの日程を読み取る（ADR-0080）。

積算案件に付けた公告PDFを読み、「申請書の提出期限」「入札書の受領期限」
「開札の日時」といった手続きの期限を取り出す。取り出した日程は画面に出し、
人が確かめてから積算工程（EstimationPhase）に取り込む。

## 読み方の順番

1. **文字から読む**（`bids.announcement.extract_bid_schedule`）
   入札側に既にある決定論的な抽出をそのまま使う。同じ形の公告を
   2通りに読むと結果が食い違うので、実装は1つに保つ。
2. **AI に読ませる**（`bids.announcement_llm`）
   1 で取れないとき、または文字が (cid:NNN) に化けているときだけ。
   発注機関によっては PDF のフォントに ToUnicode が無く、
   pdfplumber では中身が取り出せない（announcement_llm の冒頭に経緯）。

AI を最初から使わないのは、費用と速さのため。文字で読めるものは
1件 0 円・1秒で済み、AI に投げると1件あたり数十円かかる。

## 読み取った値をそのまま工程にしない

AI も文字からの抽出も読み違える。読み取った日程は資料に貯めておき
（`EstimationDocument.ai_schedule`）、画面で見てから「工程に取り込む」を
押したときだけ `EstimationPhase` を作る。自社書類の AI 読み取り
（ADR-0071）と同じ考え方。
"""
from __future__ import annotations

import datetime
import logging

from django.utils import timezone

# 資料から起こした工程の色。公告から取り込んだ工程（ADR-0076）と揃える
from apps.estimation.services.from_bid import _DEFAULT_COLOR, _STAGE_COLORS

logger = logging.getLogger(__name__)


class ScheduleReadError(Exception):
    """日程を読み取れなかったとき。画面にそのまま出せる文言を持つ。"""


def _file_bytes(document) -> bytes:
    """保存したファイルの中身を読む。"""
    field = document.file
    with field.storage.open(field.name, "rb") as handle:
        return handle.read()


def read_schedule(document, user=None) -> dict:
    """資料の PDF から日程を読み取り、資料に書き戻す。

    Returns:
        {"schedule": [...], "source": "text" | "ai", "summary": str}

    Raises:
        ScheduleReadError: PDF でない、中身が読めない、AI が使えない など
    """
    from apps.bids.announcement import extract_bid_schedule, extract_text, has_no_text_layer

    if not document.is_pdf:
        raise ScheduleReadError(
            "日程を読み取れるのは PDF だけです。Excel は工程を手で入れてください。",
        )

    try:
        data = _file_bytes(document)
    except FileNotFoundError as exc:
        raise ScheduleReadError("ファイルが見つかりません。") from exc

    text = extract_text(data)

    # --- 1. 文字から読む ---
    if not has_no_text_layer(data, text):
        schedule = extract_bid_schedule(text)
        if schedule:
            return _store(document, schedule, source="text", summary="")

    # --- 2. AI に読ませる ---
    result = _read_with_ai(document, data, user=user)
    if result is None:
        raise ScheduleReadError(
            "日程を読み取れませんでした。"
            "公告の別表が無い、または AI での読み取りが使えない状態です。"
            "工程は「+ 工程追加」から手で入れてください。",
        )
    return result


def _read_with_ai(document, data: bytes, user=None) -> dict | None:
    """Claude に PDF を読ませて日程を取り出す。使えなければ None。"""
    from apps.bids import announcement_llm

    if not announcement_llm.is_available():
        return None

    parsed = announcement_llm.extract_with_llm(data, document.company, user=user)
    if not parsed:
        return None

    # announcement_llm は工事概要・参加要件を返す。そこから起こした本文を
    # もう一度 extract_bid_schedule に通す。日付の読み方を1か所に保つため。
    from apps.bids.announcement import extract_bid_schedule

    body = "\n".join(
        str(value) for value in parsed.values() if isinstance(value, str) and value
    )
    schedule = extract_bid_schedule(body)
    if not schedule:
        return None
    return _store(
        document, schedule, source="ai", summary=parsed.get("work_outline", "") or "",
    )


def _store(document, schedule, *, source: str, summary: str) -> dict:
    """読み取った日程を資料に書き戻す。"""
    document.ai_schedule = schedule
    document.ai_summary = summary
    document.ai_checked_at = timezone.now()
    document.save(update_fields=[
        "ai_schedule", "ai_summary", "ai_checked_at", "updated_at",
    ])
    return {"schedule": schedule, "source": source, "summary": summary}


def _parse_datetime(value: str):
    """"2026-10-27T17:00" を日付にする。読めなければ None。"""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value).date()
    except ValueError:
        return None


def schedule_rows(document) -> list[dict]:
    """画面に出す行。日付を読めたものだけを、期限の早い順に並べる。"""
    rows = []
    for item in document.ai_schedule or []:
        end = _parse_datetime(item.get("datetime", ""))
        if not end:
            continue
        rows.append({
            "label": item.get("label", ""),
            "end": end,
            "start": _parse_datetime(item.get("start", "")),
            "detail": item.get("detail", "") or "",
        })
    rows.sort(key=lambda row: row["end"])
    return rows


def import_as_phases(document, created_by=None) -> int:
    """読み取った日程を積算工程として取り込む。

    公告からの取り込み（from_bid.import_phases_from_bid）と同じく、
    同じ項目名の工程が既にあれば飛ばす。読み取り直しても、
    手で直した日付が上書きされない。

    Returns:
        新しく作った工程の件数
    """
    from apps.estimation.models import EstimationPhase

    project = document.project
    existing = set(
        # unscoped: project から辿るので会社は絞り込み済み
        EstimationPhase.unscoped.filter(project=project)
        .exclude(source_label="")
        .values_list("source_label", flat=True)
    )
    rows = schedule_rows(document)
    if not rows:
        return 0

    # 締切だけが並ぶので、ひとつ前の締切を始点にしてバーに引き延ばす
    # （入札側の bids.gantt と同じ読み方）。先頭は前日から。
    last = rows[0]["end"] - datetime.timedelta(days=1)
    created = 0
    for idx, row in enumerate(rows):
        label = row["label"]
        if not label or label in existing:
            last = row["end"]
            continue
        start = row["start"] or last
        if start > row["end"]:
            start = row["end"] - datetime.timedelta(days=1)
        stage = _stage_of(label)
        EstimationPhase.unscoped.create(  # unscoped: company を明示指定
            company=project.company,
            project=project,
            created_by=created_by,
            name=stage,
            source_label=label,
            start_date=start,
            end_date=row["end"],
            sort_order=idx * 10,
            color=_STAGE_COLORS.get(stage, _DEFAULT_COLOR),
            memo=row["detail"],
            progress=0,
        )
        existing.add(label)
        last = row["end"]
        created += 1
    return created


def _stage_of(label: str) -> str:
    """公告の項目名を段階名にする。入札側の言い換えをそのまま使う。"""
    from apps.bids.gantt import _stage_of as bid_stage_of

    return bid_stage_of(label)

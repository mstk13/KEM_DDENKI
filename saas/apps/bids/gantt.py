"""入札公告のスケジュールを「受注までの流れ」のガントチャートに変換する。

公告PDFの別表（announcement.extract_bid_schedule が BidProject.bid_schedule に
入れたもの）は、ほとんどの項目が締切の日時しか持たない。

    ① 配置予定技術者の専任期間      専任を要しない
    ② 入札説明書等の交付期間        令和8年9月4日から同年11月10日まで
    ③ 申請書、技術資料及び技術提案書の提出期限   令和8年9月17日 正午
    ④ 見積等の提出期限              該当なし
    ⑤ 入札書の受領期限              令和8年10月27日 17時
    ⑥ 開札の日時及び場所            令和8年11月11日 15時

締切を点として置くだけでは「いつまでに何を出すか」は分かるが「流れ」にならない。
そこで締切を終点、ひとつ前の締切（先頭は公告日）を始点としてバーに引き延ばす。
バーの長さ＝その手続きに使える期間、進捗＝経過した割合、という読み方になる。

項目の扱いは3種類あり、次の順で決まる。

    1. BidProject.schedule_overrides … この案件だけの手直し（画面で変更）
    2. BidScheduleRule              … 会社共通の既定（画面で変更）
    3. 自動判定                      … 公告に開始日があれば期間、無ければ締切

    締切 (deadline) … 公告から開札までの一本道に入れる。矢印で繋ぐ
    期間 (period)   … 交付期間のように他と並走する窓口。鎖には入れない
    非表示 (hidden) … 図に出さない

描画は apps/schedules と同じ frappe-gantt 0.6.1。バーはドラッグで動かせて、
動かした結果は schedule_overrides に入る（公告を取り直しても消えない）。
"""
from __future__ import annotations

import datetime

from django.utils import timezone

# 別表のラベルを受注までの段階に対応づける。
# 公告の書き方は発注機関ごとに違うので、完全一致ではなく含まれる語で判定する。
# 前方から順に見て最初に当たったものを採用する。
_STAGE_RULES = [
    (("交付", "説明書"), "入札説明書の入手"),
    (("申請書", "技術資料", "技術提案", "参加表明"), "参加申請"),
    (("見積",), "見積提出"),
    (("質問", "質疑"), "質問受付"),
    (("入札書", "入札の締切", "入札締切", "入札期限"), "入札書提出"),
    (("開札", "落札"), "開札・落札者決定"),
    (("専任",), "配置技術者の専任"),
]

# 会社共通の既定を設定する画面に並べる段階。_STAGE_RULES と同じ順。
KNOWN_STAGES = [stage for _words, stage in _STAGE_RULES]

# 扱いの選択肢。BidScheduleRule.Kind と同じ値を使う。
DEADLINE = "deadline"
PERIOD = "period"
HIDDEN = "hidden"
KINDS = (DEADLINE, PERIOD, HIDDEN)

_OPENING_WORDS = ("開札", "落札")


def _stage_of(label: str) -> str:
    """項目ラベルから受注までの段階名を返す。判定できなければラベルをそのまま使う。"""
    for words, stage in _STAGE_RULES:
        if any(w in label for w in words):
            return stage
    return label


def _company_rules(project) -> dict[str, str]:
    """会社共通の既定を {段階: 扱い} で返す。"""
    from apps.bids.models import BidScheduleRule

    # unscoped: この関数はリクエスト外（管理コマンド・将来のAPI）からも呼べるよう、
    # 案件の company で明示的に絞る。apps/schedules/services.py と同じ方針。
    return {
        rule.stage: rule.kind
        for rule in BidScheduleRule.unscoped.filter(company_id=project.company_id)
    }


def _resolve_kind(event: dict, override: dict, rules: dict[str, str]) -> str:
    """項目の扱いを決める。案件の手直し → 会社の既定 → 自動判定 の順。"""
    kind = override.get("kind") or rules.get(event["stage"])
    if kind in KINDS:
        return kind
    # 公告に開始日が書いてある項目は、窓口が開いている間ずっと続く期間とみなす。
    return PERIOD if event["start"] else DEADLINE


def _parse(value: str | None) -> datetime.datetime | None:
    """別表の ISO 文字列を aware datetime にする。

    公告に時刻が書いていない項目は "2026-09-17" のように日付だけで入っている。
    その場合はその日の終わり（23:59）とみなす。締切なので日中に切り上げると
    「もう過ぎた」と誤表示するため。
    """
    if not value:
        return None
    try:
        dt = datetime.datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.hour == 0 and dt.minute == 0 and "T" not in value:
        dt = dt.replace(hour=23, minute=59)
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def _move_to_day(day: str, keep_time_from: datetime.datetime | None,
                 default_time: datetime.time) -> datetime.datetime | None:
    """手直しの日付（YYYY-MM-DD）を datetime にする。時刻は元の値を残す。

    ドラッグで動かせるのは日単位なので、「正午必着」「17時」といった
    公告に書かれた時刻まで一緒に失わないようにする。
    """
    try:
        d = datetime.date.fromisoformat(day)
    except (ValueError, TypeError):
        return None
    t = timezone.localtime(keep_time_from).time() if keep_time_from else default_time
    return timezone.make_aware(
        datetime.datetime.combine(d, t), timezone.get_current_timezone(),
    )


def _origin(project, events: list[dict]) -> datetime.datetime:
    """流れの起点。公告日 → 別表にある最も早い開始日 → 案件を取得した日、の順。"""
    tz = timezone.get_current_timezone()
    if project.announced_on:
        return timezone.make_aware(
            datetime.datetime.combine(project.announced_on, datetime.time(0, 0)), tz,
        )
    starts = [e["start"] for e in events if e["start"]]
    if starts:
        return min(starts)
    return project.created_at


def _state(start: datetime.datetime, end: datetime.datetime,
           now: datetime.datetime) -> str:
    """バーの状態。done（締切済）/ active（進行中）/ upcoming（これから）。"""
    if now >= end:
        return "done"
    if now >= start:
        return "active"
    return "upcoming"


def _collect_events(project) -> list[dict]:
    """別表・入札期限・開札日から、日時の付いた項目を集める。"""
    events = []
    for item in project.bid_schedule or []:
        end = _parse(item.get("datetime"))
        if not end:
            continue
        events.append({
            "label": item.get("label", ""),
            "start": _parse(item.get("start")),
            "end": end,
            "detail": item.get("detail", ""),
        })

    # 別表を読めていない案件（スクレイピングだけで拾ったもの）は
    # 入札期限しか分かっていない。それでも1本は引けるようにする。
    if not events and project.deadline:
        events.append({
            "label": "入札期限",
            "start": None,
            "end": timezone.localtime(project.deadline),
            "detail": "公告PDFから別表を読み取れていません",
        })

    # 開札日はモデル側にも別に入っている。別表から取れていなければ補う。
    if project.opening_on and not any(
        any(w in e["label"] for w in _OPENING_WORDS) for e in events
    ):
        events.append({
            "label": "開札",
            "start": None,
            "end": timezone.make_aware(
                datetime.datetime.combine(project.opening_on, datetime.time(23, 59)),
                timezone.get_current_timezone(),
            ),
            "detail": "",
        })
    return events


def _annotate(events: list[dict], project) -> list[dict]:
    """各項目に段階・扱いを付け、案件ごとの手直し（扱い・日付）を反映する。"""
    overrides = project.schedule_overrides or {}
    rules = _company_rules(project)

    for event in events:
        override = overrides.get(event["label"]) or {}
        event["stage"] = _stage_of(event["label"])
        event["kind"] = _resolve_kind(event, override, rules)
        event["overridden"] = bool(override)

        if override.get("end"):
            moved = _move_to_day(override["end"], event["end"], datetime.time(23, 59))
            if moved:
                event["end"] = moved
        if override.get("start"):
            moved = _move_to_day(override["start"], event["start"], datetime.time(0, 0))
            if moved:
                event["start"] = moved
    return events


def _empty() -> dict:
    return {"tasks": [], "rows": [], "hidden": [], "origin": None,
            "goal": None, "next": None}


def build_bid_gantt(project) -> dict:
    """入札案件の手続きスケジュールをガントチャート用データにする。

    Returns:
        {
          "tasks": [...],      # frappe-gantt に渡す JSON
          "rows": [...],       # 一覧・設定パネル用（段階名・日時・扱い・状態）
          "hidden": [...],     # 「図に出さない」にした項目（設定パネルで戻せる）
          "origin": datetime,  # 流れの起点（公告日）
          "goal": datetime | None,  # 開札日時
          "next": dict | None,      # 次に来る締切（rows の1つ）
        }
        日程が1件も無ければ tasks / rows は空。
    """
    now = timezone.localtime()

    # --- 1. 別表の項目を集めて、扱いと手直しを当てる ---
    events = _annotate(_collect_events(project), project)
    if not events:
        return _empty()

    hidden = [
        {"stage": e["stage"], "label": e["label"], "kind": HIDDEN,
         "end": e["end"], "overridden": e["overridden"]}
        for e in events if e["kind"] == HIDDEN
    ]
    events = [e for e in events if e["kind"] != HIDDEN]
    if not events:
        return {**_empty(), "hidden": hidden}

    events.sort(key=lambda e: e["end"])

    # --- 2. 締切をバーに引き延ばす ---
    #
    # 締切だけが一本道になる。期間（交付期間など）は他と並走しているだけなので
    # 鎖に入れない。混ぜると、期間の締切に引きずられて後続バーの始点がずれる。
    origin = _origin(project, events)
    cursor = origin  # 直前の締切。期間項目では進めない。
    prepared = []
    previous_deadline_id = ""

    for idx, event in enumerate(events):
        is_period = event["kind"] == PERIOD
        start = event["start"] or cursor
        end = event["end"]
        if start > end:
            # 別表の並びが日付順でない、または手直しで前後した場合。
            # 潰れたバーは読めないので1日分にする。
            start = end - datetime.timedelta(days=1)

        task_id = f"bid-{idx}"
        prepared.append({
            "id": task_id,
            "event": event,
            "start": start,
            "end": end,
            "is_period": is_period,
            # 矢印は締切どうしだけ繋ぐ。期間バーは前の手続きの完了を待たない。
            "dependencies": "" if is_period else previous_deadline_id,
        })

        if not is_period:
            previous_deadline_id = task_id
            cursor = end

    # 表示は開始が早い順。長い期間バーが上に来て、その下を締切が流れる。
    prepared.sort(key=lambda r: (r["start"], r["end"]))

    # --- 3. 描画用に整える ---
    rows = []
    tasks = []
    for step, item in enumerate(prepared, start=1):
        event = item["event"]
        start, end = item["start"], item["end"]
        state = _state(start, end, now)

        # 経過率。frappe-gantt は progress をバーの塗りに使うので、
        # 「この手続きに使える期間のうちどこまで来たか」がそのまま出る。
        span = (end - start).total_seconds()
        elapsed = (now - start).total_seconds()
        progress = 100 if state == "done" else (
            0 if span <= 0 else max(0, min(100, int(elapsed / span * 100)))
        )

        is_goal = any(w in event["label"] for w in _OPENING_WORDS)
        css = "bar-bid-goal" if is_goal else f"bar-bid-{state}"
        if item["is_period"]:
            css += " bar-bid-period"
        if event["overridden"]:
            css += " bar-bid-edited"

        tasks.append({
            "id": item["id"],
            "name": event["stage"],
            # frappe-gantt は日単位。同日開始・終了だと幅0になるので1日ずらす。
            "start": start.date().isoformat(),
            "end": max(
                end.date(), start.date() + datetime.timedelta(days=1),
            ).isoformat(),
            "progress": progress,
            "custom_class": css,
            "dependencies": item["dependencies"],
            # popup とドラッグ保存に使う。
            # frappe-gantt はタスクの独自キーをそのまま持ち回る。
            "_label": event["label"],
            "_deadline": timezone.localtime(end).strftime("%Y/%m/%d %H:%M"),
            "_detail": event["detail"],
            "_edited": event["overridden"],
        })

        rows.append({
            "step": step,
            "stage": event["stage"],
            "label": event["label"],
            "kind": event["kind"],
            "start": start,
            "end": end,
            "has_own_start": bool(event["start"]),
            "detail": event["detail"],
            "state": state,
            "days_left": (end.date() - now.date()).days,
            "is_goal": is_goal,
            "overridden": event["overridden"],
        })

    goal = next((r["end"] for r in reversed(rows) if r["is_goal"]), None)
    # 次にやること。締切を過ぎていない最初の項目（表示順ではなく締切順）。
    next_row = next(
        (r for r in sorted(rows, key=lambda r: r["end"]) if r["state"] != "done"),
        None,
    )
    return {
        "tasks": tasks,
        "rows": rows,
        "hidden": hidden,
        "origin": origin,
        "goal": goal,
        "next": next_row,
    }

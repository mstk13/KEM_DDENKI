"""勤怠時間の計算ユーティリティ。"""


def parse_time_to_minutes(time_str):
    """HH:MM 形式の文字列を 00:00 からの分数に変換する。"""
    if not time_str or ":" not in time_str:
        return None
    try:
        h, m = time_str.strip().split(":")
        return int(h) * 60 + int(m)
    except (ValueError, TypeError):
        return None


def calc_attendance(start_time, end_time, break_minutes, settings):
    """勤怠時間を計算する。

    Args:
        start_time: 出勤時刻 "HH:MM"
        end_time: 退勤時刻 "HH:MM"
        break_minutes: 休憩時間(分)
        settings: dict with keys: standard_start, standard_end,
                  early_boundary, standard_hours, break_minutes,
                  round_minutes, overtime_mode

    Returns:
        dict with keys: early, normal, overtime, total, break
    """
    result = {
        "early": 0,
        "normal": 0,
        "overtime": 0,
        "total": 0,
        "break": int(break_minutes or 0),
    }

    start_min = parse_time_to_minutes(start_time)
    end_min = parse_time_to_minutes(end_time)
    if start_min is None or end_min is None:
        return result

    # 設定値をパース
    # 出勤側の基準は standard_start ではなく early_boundary を使う（早出判定用）
    std_end = parse_time_to_minutes(settings.get("standard_end", "17:00"))
    early_boundary = parse_time_to_minutes(settings.get("early_boundary", "08:00"))
    round_min = int(settings.get("round_minutes", "0"))

    # 丸め処理（出勤は切り上げ、退勤は切り捨て — ただし早出判定には丸め前を使う）
    actual_start = start_min
    actual_end = end_min

    if round_min > 0:
        # 退勤は切り捨て
        actual_end = (actual_end // round_min) * round_min

    brk = int(break_minutes or 0)

    # 総拘束時間
    gross = actual_end - actual_start
    if gross <= 0:
        return result

    # 実労働時間
    total = max(gross - brk, 0)

    # 早出時間: early_boundary より前に出勤した分
    early = 0
    if actual_start < early_boundary:
        early = min(early_boundary - actual_start, total)

    # 所定終了後の残業
    overtime = 0
    if actual_end > std_end:
        overtime = actual_end - std_end

    # 所定内時間
    normal = max(total - early - overtime, 0)

    result["early"] = early
    result["normal"] = normal
    result["overtime"] = overtime
    result["total"] = total
    result["break"] = brk

    return result

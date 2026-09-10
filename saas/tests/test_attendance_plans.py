"""出社予定（AttendPlan）。勤怠日報＝実績とは別の、先の予定を埋める画面。

入力の向きは2つ。どちらも同じ AttendPlan を読み書きする。

  * 月グリッド（plan_board） … 行＝作業員 × 列＝日
      - plan_set       … マス1つ（区分・時刻・メモ）。区分が空なら削除
      - plan_fill      … 月のうち平日／毎日／同じ曜日／カレンダーで選んだ日を
                          まとめて記入・削除
      - plan_clear_day … その日を全員ぶん削除
  * 日シート（plan_day） … 1日を固定して全員を縦に並べ、まとめて記入
"""
import datetime

import pytest
from django.utils import timezone

from apps.attendance.models import AttendPlan, format_time_range
from apps.attendance.plans import (
    build_day_sheet,
    build_day_timeline,
    build_plan_board,
    fill_days,
    month_days,
    parse_clock,
    parse_date,
    parse_month,
    shift_month,
)
from apps.workers.models import Worker

# 土日をまたぐ月をひとつ固定して使う。
# 2026-09-01 は火曜、9/5・9/6 が土日、月末は 9/30。
YEAR, MONTH = 2026, 9


class TestMonthHelpers:
    def test_月の日を並べる(self):
        days = month_days(YEAR, MONTH)
        assert len(days) == 30
        assert days[0] == datetime.date(2026, 9, 1)
        assert days[-1] == datetime.date(2026, 9, 30)

    def test_月文字列を読む(self):
        assert parse_month("2026-09") == (2026, 9)

    def test_読めない月は今月にする(self):
        today = timezone.localdate()
        assert parse_month("") == (today.year, today.month)
        assert parse_month("2026-13") == (today.year, today.month)
        assert parse_month("あああ") == (today.year, today.month)

    def test_前月と翌月(self):
        assert shift_month(2026, 1, -1) == "2025-12"
        assert shift_month(2026, 12, 1) == "2027-01"

    def test_平日だけを取り出す(self):
        days = fill_days(YEAR, MONTH, "weekday")
        assert len(days) == 22
        assert all(d.weekday() < 5 for d in days)

    def test_曜日を指定してその曜日だけ取り出す(self):
        # 2026-09-01 は火曜。火曜は 1・8・15・22・29 の5日
        days = fill_days(YEAR, MONTH, "1")
        assert [d.day for d in days] == [1, 8, 15, 22, 29]

    def test_毎日を取り出す(self):
        assert len(fill_days(YEAR, MONTH, "all")) == 30

    def test_読めない対象は平日として扱う(self):
        assert fill_days(YEAR, MONTH, "でたらめ") == fill_days(YEAR, MONTH, "weekday")

    def test_カレンダーで選んだ日だけを取り出す(self):
        days = fill_days(YEAR, MONTH, "dates", ["2026-09-10", "2026-09-03", "2026-09-24"])
        # 日付順に並び直す
        assert [d.day for d in days] == [3, 10, 24]

    def test_選んだ日のうち月の外と読めない値と重複は捨てる(self):
        days = fill_days(YEAR, MONTH, "dates", [
            "2026-09-03", "2026-09-03", "2026-10-01", "2026-08-31", "でたらめ", "",
        ])
        assert [d.day for d in days] == [3]

    def test_選んだ日が無ければ空(self):
        assert fill_days(YEAR, MONTH, "dates", []) == []
        assert fill_days(YEAR, MONTH, "dates", None) == []


class TestFormatTimeRange:
    """マスは狭いので、分が0のときは省いて短く書く。"""

    def test_両方あれば範囲にする(self):
        assert format_time_range(datetime.time(9, 0), datetime.time(17, 0)) == "9-17"

    def test_分があれば残す(self):
        assert format_time_range(datetime.time(9, 30), datetime.time(17, 0)) == "9:30-17"

    def test_片方だけでも書ける(self):
        assert format_time_range(datetime.time(9, 0), None) == "9-"
        assert format_time_range(None, datetime.time(17, 0)) == "-17"

    def test_未設定なら空(self):
        assert format_time_range(None, None) == ""


@pytest.mark.django_db
class TestBuildPlanBoard:
    def _worker(self, company, name="田中太郎", code="E001", is_active=True):
        return Worker.unscoped.create(
            company=company, name=name, employee_code=code,
            hourly_cost=3000, is_active=is_active,
        )

    def test_在籍中の作業員だけ並ぶ(self, company_a):
        self._worker(company_a, "田中太郎", "E001")
        self._worker(company_a, "退職者", "E002", is_active=False)

        board = build_plan_board(company_a, YEAR, MONTH)
        assert [r["worker"].name for r in board["rows"]] == ["田中太郎"]

    def test_予定の無い日は空のマスになる(self, company_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="site",
        )
        cells = build_plan_board(company_a, YEAR, MONTH)["rows"][0]["cells"]

        assert cells[2]["kind"] == "site"
        assert cells[2]["label"] == "現場"
        assert cells[0]["kind"] == ""
        assert cells[0]["label"] == ""

    def test_マスに時刻が入る(self, company_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="site",
            start_time=datetime.time(7, 30), end_time=datetime.time(16, 0),
        )
        cell = build_plan_board(company_a, YEAR, MONTH)["rows"][0]["cells"][2]

        assert cell["time_label"] == "7:30-16"
        assert cell["start_time"] == datetime.time(7, 30)

    def test_時刻未設定のマスは所定どおりとして空にする(self, company_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="office",
        )
        cell = build_plan_board(company_a, YEAR, MONTH)["rows"][0]["cells"][2]
        assert cell["time_label"] == ""

    def test_土日に印が付く(self, company_a):
        self._worker(company_a)
        days = build_plan_board(company_a, YEAR, MONTH)["days"]
        # 2026-09-05 は土曜
        assert days[4]["is_weekend"] is True
        assert days[4]["weekday"] == "土"
        assert days[0]["is_weekend"] is False

    def test_出社人数は稼働する区分だけ数える(self, company_a):
        day = datetime.date(2026, 9, 3)
        for index, kind in enumerate(["office", "site", "remote", "paid", "off"]):
            worker = self._worker(company_a, f"作業員{index}", f"E{index:03d}")
            AttendPlan.unscoped.create(
                company=company_a, worker=worker, plan_date=day, kind=kind,
            )
        board = build_plan_board(company_a, YEAR, MONTH)

        # 出社・現場だけを数える。在宅・有休・休みは人数に入れない
        assert board["daily_totals"][2] == {"date": day, "count": 2}

    def test_人ごとの出社日数が出る(self, company_a):
        worker = self._worker(company_a)
        for day, kind in ((1, "office"), (2, "site"), (3, "paid")):
            AttendPlan.unscoped.create(
                company=company_a, worker=worker,
                plan_date=datetime.date(2026, 9, day), kind=kind,
            )
        assert build_plan_board(company_a, YEAR, MONTH)["rows"][0]["working_days"] == 2

    def test_他社の予定は出ない(self, company_a, company_b):
        worker_a = self._worker(company_a, "A社の人", "A001")
        worker_b = self._worker(company_b, "B社の人", "B001")
        AttendPlan.unscoped.create(
            company=company_b, worker=worker_b,
            plan_date=datetime.date(2026, 9, 3), kind="office",
        )
        board = build_plan_board(company_a, YEAR, MONTH)

        assert [r["worker"].pk for r in board["rows"]] == [worker_a.pk]
        assert all(t["count"] == 0 for t in board["daily_totals"])


@pytest.mark.django_db
class TestPlanBoardView:
    def _worker(self, company, name="田中太郎"):
        return Worker.unscoped.create(
            company=company, name=name, employee_code="E001", hourly_cost=3000,
        )

    def test_予定表が出る(self, client, company_a, user_a):
        self._worker(company_a)
        client.force_login(user_a)
        html = client.get("/attendance/plans/?month=2026-09").content.decode()

        assert "出社予定" in html
        assert "田中太郎" in html
        assert "2026年9月" in html
        assert "plan-cell" in html

    def test_作業員がいなければ案内を出す(self, client, user_a):
        client.force_login(user_a)
        html = client.get("/attendance/plans/").content.decode()

        assert "在籍中の作業員が登録されていません" in html
        assert "plan-cell" not in html


@pytest.mark.django_db
class TestPlanSet:
    def _worker(self, company):
        return Worker.unscoped.create(
            company=company, name="田中太郎", employee_code="E001", hourly_cost=3000,
        )

    def test_マスを塗ると予定ができる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "site",
        })

        assert res.status_code == 200
        assert res.json()["label"] == "現場"
        assert res.json()["is_working"] is True
        plan = AttendPlan.unscoped.get(worker=worker)
        assert (plan.plan_date, plan.kind) == (datetime.date(2026, 9, 3), "site")

    def test_同じ日を塗り替えても1件のまま(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        for kind in ("office", "paid"):
            client.post("/attendance/plans/set/", {
                "worker": worker.pk, "date": "2026-09-03", "kind": kind,
            })

        assert AttendPlan.unscoped.filter(worker=worker).count() == 1
        assert AttendPlan.unscoped.get(worker=worker).kind == "paid"

    def test_区分を空にすると消える(self, client, company_a, user_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="office",
        )
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "",
        })

        assert res.json()["is_working"] is False
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_休む区分は稼働扱いにしない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "remote",
        })
        assert res.json()["is_working"] is False

    def test_日付が不正なら保存しない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026/09/03", "kind": "site",
        })

        assert res.status_code == 400
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_区分が不正なら保存しない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "でたらめ",
        })

        assert res.status_code == 400
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_他社の作業員には書き込めない(self, client, company_b, user_a, user_b):
        worker = self._worker(company_b)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "site",
        })

        assert res.status_code == 404
        assert not AttendPlan.unscoped.filter(worker=worker).exists()


@pytest.mark.django_db
class TestPlanFill:
    def _worker(self, company):
        return Worker.unscoped.create(
            company=company, name="田中太郎", employee_code="E001", hourly_cost=3000,
        )

    def test_平日だけまとめて埋まる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "office",
        })

        plans = AttendPlan.unscoped.filter(worker=worker)
        # 2026年9月の平日は22日
        assert plans.count() == 22
        assert all(p.plan_date.weekday() < 5 for p in plans)

    def test_土日も含めて埋められる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09",
            "kind": "office", "target": "all",
        })
        assert AttendPlan.unscoped.filter(worker=worker).count() == 30

    def test_既に入っている日は上書きしない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="paid",
        )
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "office",
        })

        kept = AttendPlan.unscoped.get(
            worker=worker, plan_date=datetime.date(2026, 9, 3),
        )
        assert kept.kind == "paid"

    def test_上書きを指定すれば塗り替える(self, client, company_a, user_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="paid",
        )
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09",
            "kind": "office", "overwrite": "1",
        })

        changed = AttendPlan.unscoped.get(
            worker=worker, plan_date=datetime.date(2026, 9, 3),
        )
        assert changed.kind == "office"

    def test_区分を空にすると月ぶん消える(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "office",
        })
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "",
        })
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_他社の作業員は埋められない(self, client, company_b, user_a, user_b):
        worker = self._worker(company_b)
        client.force_login(user_a)
        res = client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "office",
        })

        assert res.status_code == 404
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_カレンダーで選んだ日だけ埋まる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "site",
            "target": "dates",
            "dates": ["2026-09-03", "2026-09-10", "2026-10-01"],
        })

        plans = AttendPlan.unscoped.filter(worker=worker).order_by("plan_date")
        # 10/1 は対象月の外なので入らない
        assert [p.plan_date.day for p in plans] == [3, 10]
        assert all(p.kind == "site" for p in plans)

    def test_日付を選ばずに送ると何も入らない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "site",
            "target": "dates",
        })

        assert res.status_code == 302
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_選んだ日だけ消せる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "office",
            "target": "all",
        })
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09", "kind": "",
            "target": "dates", "dates": ["2026-09-03", "2026-09-04"],
        })

        remaining = AttendPlan.unscoped.filter(worker=worker)
        assert remaining.count() == 28
        assert not remaining.filter(plan_date__day__in=[3, 4]).exists()

    def test_月グリッドに日付選択のカレンダーが出る(self, client, company_a, user_a):
        self._worker(company_a)
        client.force_login(user_a)
        res = client.get("/attendance/plans/?month=2026-09")

        assert res.status_code == 200
        body = res.content.decode()
        assert 'name="dates" value="2026-09-01"' in body
        assert 'name="dates" value="2026-09-30"' in body
        # 2026-09-01 は火曜なので、月曜ぶん1マス空ける
        assert body.count('class="plan-pick-blank"') == 1


@pytest.mark.django_db
class TestPlanSetTimes:
    """マスの詳細ダイアログから入る区分・時刻・メモ。"""

    def _worker(self, company):
        return Worker.unscoped.create(
            company=company, name="田中太郎", employee_code="E001", hourly_cost=3000,
        )

    def test_時刻とメモを保存する(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "site",
            "start_time": "07:30", "end_time": "16:00", "note": "入間基地",
        })

        plan = AttendPlan.unscoped.get(worker=worker)
        assert (plan.start_time, plan.end_time) == (
            datetime.time(7, 30), datetime.time(16, 0),
        )
        assert plan.note == "入間基地"
        assert res.json()["time_label"] == "7:30-16"

    def test_時刻を空にすると所定どおりに戻る(self, client, company_a, user_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="site",
            start_time=datetime.time(7, 30), end_time=datetime.time(16, 0),
        )
        client.force_login(user_a)
        client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "site",
            "start_time": "", "end_time": "",
        })

        plan = AttendPlan.unscoped.get(worker=worker)
        assert plan.start_time is None
        assert plan.end_time is None

    def test_時刻が不正なら保存しない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "site",
            "start_time": "25時", "end_time": "",
        })

        assert res.status_code == 400
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_削除すると時刻ごと消える(self, client, company_a, user_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="site",
            start_time=datetime.time(7, 30), note="入間基地",
        )
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-03", "kind": "",
        })

        assert res.json()["time_label"] == ""
        assert not AttendPlan.unscoped.filter(worker=worker).exists()


@pytest.mark.django_db
class TestPlanClearDay:
    """日付ヘッダの × 。その日を全員ぶん消す。"""

    def _worker(self, company, name, code):
        return Worker.unscoped.create(
            company=company, name=name, employee_code=code, hourly_cost=3000,
        )

    def _plan(self, company, worker, day, kind="office"):
        return AttendPlan.unscoped.create(
            company=company, worker=worker,
            plan_date=datetime.date(2026, 9, day), kind=kind,
        )

    def test_その日を全員ぶん消す(self, client, company_a, user_a):
        a = self._worker(company_a, "田中太郎", "E001")
        b = self._worker(company_a, "佐藤次郎", "E002")
        self._plan(company_a, a, 3)
        self._plan(company_a, b, 3)
        keep = self._plan(company_a, a, 4)

        client.force_login(user_a)
        client.post("/attendance/plans/clear-day/", {
            "date": "2026-09-03", "month": "2026-09",
        })

        remaining = list(AttendPlan.unscoped.all())
        assert [p.pk for p in remaining] == [keep.pk]

    def test_日付が不正なら何も消さない(self, client, company_a, user_a):
        worker = self._worker(company_a, "田中太郎", "E001")
        self._plan(company_a, worker, 3)

        client.force_login(user_a)
        client.post("/attendance/plans/clear-day/", {
            "date": "2026/09/03", "month": "2026-09",
        })
        assert AttendPlan.unscoped.count() == 1

    def test_他社の同じ日は消えない(self, client, company_a, company_b, user_a):
        a = self._worker(company_a, "A社の人", "A001")
        b = self._worker(company_b, "B社の人", "B001")
        self._plan(company_a, a, 3)
        other = self._plan(company_b, b, 3)

        client.force_login(user_a)
        client.post("/attendance/plans/clear-day/", {
            "date": "2026-09-03", "month": "2026-09",
        })

        assert [p.pk for p in AttendPlan.unscoped.all()] == [other.pk]


@pytest.mark.django_db
class TestPlanFillWeekday:
    """「同じ曜日をまとめて」と全員一括。"""

    def _worker(self, company, name="田中太郎", code="E001"):
        return Worker.unscoped.create(
            company=company, name=name, employee_code=code, hourly_cost=3000,
        )

    def test_指定した曜日だけ埋まる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09",
            "target": "1", "kind": "site",
        })

        days = sorted(
            p.plan_date.day for p in AttendPlan.unscoped.filter(worker=worker)
        )
        # 2026-09-01 は火曜
        assert days == [1, 8, 15, 22, 29]

    def test_曜日一括でも時刻を入れられる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09",
            "target": "1", "kind": "site",
            "start_time": "07:30", "end_time": "16:00",
        })

        plans = AttendPlan.unscoped.filter(worker=worker)
        assert all(p.start_time == datetime.time(7, 30) for p in plans)
        assert all(p.end_time == datetime.time(16, 0) for p in plans)

    def test_対象者を空にすると全員に入る(self, client, company_a, user_a):
        self._worker(company_a, "田中太郎", "E001")
        self._worker(company_a, "佐藤次郎", "E002")
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "month": "2026-09", "target": "1", "kind": "office",
        })

        # 火曜5日 × 2人
        assert AttendPlan.unscoped.count() == 10

    def test_全員一括でも他社には入らない(self, client, company_a, company_b, user_a):
        self._worker(company_a, "A社の人", "A001")
        self._worker(company_b, "B社の人", "B001")
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "month": "2026-09", "target": "1", "kind": "office",
        })

        assert AttendPlan.unscoped.filter(company=company_b).count() == 0
        assert AttendPlan.unscoped.filter(company=company_a).count() == 5

    def test_曜日を指定してまとめて消せる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09",
            "target": "all", "kind": "office",
        })
        client.post("/attendance/plans/fill/", {
            "worker": worker.pk, "month": "2026-09",
            "target": "1", "kind": "",
        })

        days = sorted(
            p.plan_date.day for p in AttendPlan.unscoped.filter(worker=worker)
        )
        assert 1 not in days
        assert 2 in days
        assert len(days) == 25


class TestParseDate:
    def test_日付を読む(self):
        assert parse_date("2026-09-10") == datetime.date(2026, 9, 10)

    def test_読めない日付は今日にする(self):
        today = timezone.localdate()
        assert parse_date("") == today
        assert parse_date("2026/09/10") == today
        assert parse_date("あああ") == today


@pytest.mark.django_db
class TestBuildDaySheet:
    """1日 × 全員のシート。月グリッドと向きが逆。"""

    def _worker(self, company, name, code, is_active=True):
        return Worker.unscoped.create(
            company=company, name=name, employee_code=code,
            hourly_cost=3000, is_active=is_active,
        )

    def test_予定が無い作業員も行として並ぶ(self, company_a):
        """全員ぶんを埋めるための画面なので、空欄も見えている必要がある。"""
        self._worker(company_a, "田中太郎", "E001")
        self._worker(company_a, "佐藤次郎", "E002")

        sheet = build_day_sheet(company_a, datetime.date(2026, 9, 10))
        assert [r["worker"].name for r in sheet["rows"]] == ["田中太郎", "佐藤次郎"]
        assert all(r["kind"] == "" for r in sheet["rows"])

    def test_その日の予定だけを拾う(self, company_a):
        worker = self._worker(company_a, "田中太郎", "E001")
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 10), kind="site",
            start_time=datetime.time(7, 30), note="入間基地",
        )
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 11), kind="paid",
        )

        row = build_day_sheet(company_a, datetime.date(2026, 9, 10))["rows"][0]
        assert row["kind"] == "site"
        assert row["start_time"] == datetime.time(7, 30)
        assert row["note"] == "入間基地"

    def test_出社人数と曜日が出る(self, company_a):
        for index, kind in enumerate(["office", "site", "paid"]):
            worker = self._worker(company_a, f"作業員{index}", f"E{index:03d}")
            AttendPlan.unscoped.create(
                company=company_a, worker=worker,
                plan_date=datetime.date(2026, 9, 10), kind=kind,
            )
        sheet = build_day_sheet(company_a, datetime.date(2026, 9, 10))

        assert sheet["working_count"] == 2
        assert sheet["weekday"] == "木"
        assert sheet["is_weekend"] is False

    def test_前日と翌日を持つ(self, company_a):
        self._worker(company_a, "田中太郎", "E001")
        sheet = build_day_sheet(company_a, datetime.date(2026, 9, 1))

        assert sheet["prev_date"] == datetime.date(2026, 8, 31)
        assert sheet["next_date"] == datetime.date(2026, 9, 2)
        assert sheet["month_str"] == "2026-09"

    def test_退職者は並ばない(self, company_a):
        self._worker(company_a, "田中太郎", "E001")
        self._worker(company_a, "退職者", "E002", is_active=False)

        sheet = build_day_sheet(company_a, datetime.date(2026, 9, 10))
        assert [r["worker"].name for r in sheet["rows"]] == ["田中太郎"]

    def test_他社の予定は混ざらない(self, company_a, company_b):
        self._worker(company_a, "A社の人", "A001")
        worker_b = self._worker(company_b, "B社の人", "B001")
        AttendPlan.unscoped.create(
            company=company_b, worker=worker_b,
            plan_date=datetime.date(2026, 9, 10), kind="office",
        )

        sheet = build_day_sheet(company_a, datetime.date(2026, 9, 10))
        assert [r["worker"].name for r in sheet["rows"]] == ["A社の人"]
        assert sheet["working_count"] == 0


@pytest.mark.django_db
class TestPlanDayView:
    """日を固定して全員ぶんを一度に保存する画面。"""

    def _worker(self, company, name, code):
        return Worker.unscoped.create(
            company=company, name=name, employee_code=code, hourly_cost=3000,
        )

    def test_画面が出る(self, client, company_a, user_a):
        self._worker(company_a, "田中太郎", "E001")
        client.force_login(user_a)
        html = client.get(
            "/attendance/plans/day/?date=2026-09-10",
        ).content.decode()

        assert "出社予定（日別）" in html
        assert "2026年9月10日" in html
        assert "田中太郎" in html

    def test_全員ぶんを一度に保存する(self, client, company_a, user_a):
        a = self._worker(company_a, "田中太郎", "E001")
        b = self._worker(company_a, "佐藤次郎", "E002")
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"kind_{a.pk}": "site",
            f"start_{a.pk}": "07:30",
            f"end_{a.pk}": "16:00",
            f"note_{a.pk}": "入間基地",
            f"kind_{b.pk}": "paid",
        })

        plan_a = AttendPlan.unscoped.get(worker=a)
        plan_b = AttendPlan.unscoped.get(worker=b)
        assert (plan_a.kind, plan_a.start_time, plan_a.note) == (
            "site", datetime.time(7, 30), "入間基地",
        )
        assert plan_b.kind == "paid"

    def test_区分を空にした人はその日の予定が消える(self, client, company_a, user_a):
        worker = self._worker(company_a, "田中太郎", "E001")
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 10), kind="office",
        )
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10", f"kind_{worker.pk}": "",
        })
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_他の日の予定には触らない(self, client, company_a, user_a):
        worker = self._worker(company_a, "田中太郎", "E001")
        keep = AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 11), kind="office",
        )
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10", f"kind_{worker.pk}": "site",
        })

        keep.refresh_from_db()
        assert keep.kind == "office"
        assert AttendPlan.unscoped.filter(worker=worker).count() == 2

    def test_時刻が不正なら何も保存しない(self, client, company_a, user_a):
        worker = self._worker(company_a, "田中太郎", "E001")
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"kind_{worker.pk}": "site",
            f"start_{worker.pk}": "25時",
        })
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_他社の作業員PKを混ぜても書き込まれない(
        self, client, company_a, company_b, user_a,
    ):
        mine = self._worker(company_a, "A社の人", "A001")
        theirs = self._worker(company_b, "B社の人", "B001")
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"kind_{mine.pk}": "office",
            f"kind_{theirs.pk}": "office",
        })

        assert AttendPlan.unscoped.filter(worker=mine).count() == 1
        assert AttendPlan.unscoped.filter(worker=theirs).count() == 0

    def test_月表から日別へ行ける(self, client, company_a, user_a):
        self._worker(company_a, "田中太郎", "E001")
        client.force_login(user_a)
        html = client.get("/attendance/plans/?month=2026-09").content.decode()

        assert "/attendance/plans/day/?date=2026-09-10" in html


class TestKindFields:
    """区分ごとに何を訊くか。画面の入力欄の出し分けはこの定義に従う。"""

    def test_現場と直行直帰は現場名を訊く(self):
        for kind in ("site", "direct"):
            assert AttendPlan.KIND_FIELDS[kind]["place"] == "現場名"
            assert AttendPlan.KIND_FIELDS[kind]["time"] is True

    def test_出社と在宅は時刻だけ訊く(self):
        for kind in ("office", "remote"):
            assert AttendPlan.KIND_FIELDS[kind]["time"] is True
            assert AttendPlan.KIND_FIELDS[kind]["place"] == ""
            assert AttendPlan.KIND_FIELDS[kind]["span"] is False

    def test_出張だけ行先と期間を訊く(self):
        spec = AttendPlan.KIND_FIELDS["trip"]
        assert spec["place"] == "行先"
        assert spec["span"] is True
        assert not any(
            other["span"] for kind, other in AttendPlan.KIND_FIELDS.items()
            if kind != "trip"
        )

    def test_全区分に定義がある(self):
        assert set(AttendPlan.KIND_FIELDS) == set(AttendPlan.Kind.values)
        assert set(AttendPlan.SHORT_LABELS) == set(AttendPlan.Kind.values)

    def test_マスに出す1文字(self):
        assert AttendPlan.SHORT_LABELS["direct"] == "直"
        assert AttendPlan.SHORT_LABELS["trip"] == "張"
        assert all(len(v) == 1 for v in AttendPlan.SHORT_LABELS.values())


@pytest.mark.django_db
class TestTripSpan:
    """出張は曜日をまたぐ。期間で登録し、保存時に日ごとの行へ展開する。"""

    def _worker(self, company):
        return Worker.unscoped.create(
            company=company, name="田中太郎", employee_code="E001", hourly_cost=3000,
        )

    def test_期間を指定すると日ごとに展開される(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
            "note": "仙台支社", "until": "2026-09-11",
        })

        plans = AttendPlan.unscoped.filter(worker=worker).order_by("plan_date")
        assert [p.plan_date.day for p in plans] == [9, 10, 11]
        assert all(p.kind == "trip" and p.note == "仙台支社" for p in plans)

    def test_1日1行という持ち方は崩さない(self, company_a, user_a, client):
        """月グリッドと出社人数の集計が成り立つ前提。"""
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
            "until": "2026-09-11",
        })
        # 同じ期間をもう一度送っても行は増えない
        client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
            "until": "2026-09-11",
        })
        assert AttendPlan.unscoped.filter(worker=worker).count() == 3

    def test_期間で入れると画面に読み直しを指示する(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
            "until": "2026-09-11",
        })
        assert res.json()["reload"] is True

    def test_1日だけなら読み直さない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
        })
        assert res.json()["reload"] is False
        assert AttendPlan.unscoped.filter(worker=worker).count() == 1

    def test_期間を持たない区分では終了日を無視する(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "site",
            "until": "2026-09-30",
        })
        assert AttendPlan.unscoped.filter(worker=worker).count() == 1

    def test_終了日が開始より前なら断る(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
            "until": "2026-09-01",
        })

        assert res.status_code == 400
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_期間が長すぎたら断る(self, client, company_a, user_a):
        """年の打ち間違いで数千行作らないための歯止め。"""
        worker = self._worker(company_a)
        client.force_login(user_a)
        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-09", "kind": "trip",
            "until": "2036-09-09",
        })

        assert res.status_code == 400
        assert not AttendPlan.unscoped.filter(worker=worker).exists()

    def test_日別画面からも期間で入れられる(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/day/", {
            "date": "2026-09-09",
            f"kind_{worker.pk}": "trip",
            f"note_{worker.pk}": "仙台支社",
            f"until_{worker.pk}": "2026-09-11",
        })

        plans = AttendPlan.unscoped.filter(worker=worker).order_by("plan_date")
        assert [p.plan_date.day for p in plans] == [9, 10, 11]

    def test_日別画面で終了日が不正なら保存しない(self, client, company_a, user_a):
        worker = self._worker(company_a)
        client.force_login(user_a)
        client.post("/attendance/plans/day/", {
            "date": "2026-09-09",
            f"kind_{worker.pk}": "trip",
            f"until_{worker.pk}": "2026-09-01",
        })
        assert not AttendPlan.unscoped.filter(worker=worker).exists()


@pytest.mark.django_db
class TestBoardDisplay:
    """マスの表示。31列を12px以上で並べるため、区分は1文字にする。"""

    def _worker(self, company):
        return Worker.unscoped.create(
            company=company, name="田中太郎", employee_code="E001", hourly_cost=3000,
        )

    def test_マスは短縮ラベルを持つ(self, company_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker,
            plan_date=datetime.date(2026, 9, 3), kind="direct",
        )
        cell = build_plan_board(company_a, YEAR, MONTH)["rows"][0]["cells"][2]

        assert cell["short"] == "直"
        assert cell["label"] == "直行直帰"

    def test_土曜と日曜を別々に持つ(self, company_a):
        self._worker(company_a)
        days = build_plan_board(company_a, YEAR, MONTH)["days"]

        # 2026-09-05 は土曜、9-06 は日曜
        assert (days[4]["is_saturday"], days[4]["is_sunday"]) == (True, False)
        assert (days[5]["is_saturday"], days[5]["is_sunday"]) == (False, True)
        # 平日はどちらでもない（色を付けない）
        assert (days[0]["is_saturday"], days[0]["is_sunday"]) == (False, False)


STD_START = datetime.time(8, 0)
STD_END = datetime.time(17, 0)
DAY = datetime.date(2026, 9, 10)


class TestParseClock:
    def test_勤怠設定の時刻を読む(self):
        assert parse_clock("07:30", STD_START) == datetime.time(7, 30)

    def test_読めなければ既定値(self):
        assert parse_clock("", STD_START) == STD_START
        assert parse_clock("八時", STD_START) == STD_START


@pytest.mark.django_db
class TestDayTimeline:
    """1日を24時間の横軸にした図。誰がいつ・どこにいるか。"""

    def _worker(self, company, name="田中太郎", code="E001"):
        return Worker.unscoped.create(
            company=company, name=name, employee_code=code, hourly_cost=3000,
        )

    def _plan(self, company, worker, kind, **kwargs):
        return AttendPlan.unscoped.create(
            company=company, worker=worker, plan_date=DAY, kind=kind, **kwargs,
        )

    def _timeline(self, company):
        return build_day_timeline(company, DAY, STD_START, STD_END)

    def test_時刻の帯が24時間に対する割合になる(self, company_a):
        worker = self._worker(company_a)
        self._plan(
            company_a, worker, "site",
            start_time=datetime.time(6, 0), end_time=datetime.time(18, 0),
        )
        row = self._timeline(company_a)["rows"][0]

        # 6:00 は 1日の 25%、6:00〜18:00 は 50%
        assert row["has_bar"] is True
        assert float(row["left_pct"]) == pytest.approx(25.0)
        assert float(row["width_pct"]) == pytest.approx(50.0)

    def test_時刻未設定なら所定の帯で描く(self, company_a):
        worker = self._worker(company_a)
        self._plan(company_a, worker, "office")
        row = self._timeline(company_a)["rows"][0]

        # 8:00 = 33.33%, 8:00〜17:00 = 9時間 = 37.5%
        assert float(row["left_pct"]) == pytest.approx(33.3333, abs=0.01)
        assert float(row["width_pct"]) == pytest.approx(37.5)
        assert "所定" in row["time_label"]

    def test_休む区分は帯にしない(self, company_a):
        """帯にすると「その時間そこにいる」と読めてしまう。"""
        for index, kind in enumerate(["paid", "off"]):
            worker = self._worker(company_a, f"作業員{index}", f"E{index:03d}")
            self._plan(company_a, worker, kind)

        rows = self._timeline(company_a)["rows"]
        assert [r["has_bar"] for r in rows] == [False, False]

    def test_出張は行先だけ出して帯にしない(self, company_a):
        worker = self._worker(company_a)
        self._plan(company_a, worker, "trip", note="仙台支社")
        row = self._timeline(company_a)["rows"][0]

        assert row["has_bar"] is False
        assert row["note"] == "仙台支社"
        assert row["label"] == "出張"

    def test_日をまたぐ勤務は24時で切って印を付ける(self, company_a):
        worker = self._worker(company_a)
        self._plan(
            company_a, worker, "site",
            start_time=datetime.time(22, 0), end_time=datetime.time(6, 0),
        )
        row = self._timeline(company_a)["rows"][0]

        assert row["crosses_midnight"] is True
        assert float(row["left_pct"]) == pytest.approx(91.6667, abs=0.01)
        # 22:00 から 24:00 まで＝2時間
        assert float(row["width_pct"]) == pytest.approx(8.3333, abs=0.01)

    def test_予定の無い人は別枠にする(self, company_a):
        working = self._worker(company_a, "働く人", "E001")
        self._worker(company_a, "予定なしの人", "E002")
        self._plan(company_a, working, "office")

        timeline = self._timeline(company_a)
        assert [r["worker"].name for r in timeline["rows"]] == ["働く人"]
        assert [w.name for w in timeline["idle"]] == ["予定なしの人"]

    def test_目盛りは3時間おきで0から24まで(self, company_a):
        self._worker(company_a)
        hours = self._timeline(company_a)["hours"]

        assert [h["hour"] for h in hours] == [0, 3, 6, 9, 12, 15, 18, 21, 24]
        assert float(hours[0]["left_pct"]) == 0.0
        assert float(hours[-1]["left_pct"]) == pytest.approx(100.0)

    def test_今日でなければ現在時刻の線を出さない(self, company_a):
        self._worker(company_a)
        # DAY が実行日と一致すると線が出てしまうので、必ず今日ではない昨日で確認する
        yesterday = timezone.localdate() - datetime.timedelta(days=1)
        timeline = build_day_timeline(company_a, yesterday, STD_START, STD_END)
        assert timeline["now_pct"] is None

    def test_今日なら現在時刻の線を出す(self, company_a):
        worker = self._worker(company_a)
        today = timezone.localdate()
        AttendPlan.unscoped.create(
            company=company_a, worker=worker, plan_date=today, kind="office",
        )
        timeline = build_day_timeline(company_a, today, STD_START, STD_END)

        assert timeline["is_today"] is True
        assert 0.0 <= float(timeline["now_pct"]) <= 100.0

    def test_他社の予定は混ざらない(self, company_a, company_b):
        self._worker(company_a, "A社の人", "A001")
        worker_b = self._worker(company_b, "B社の人", "B001")
        self._plan(company_b, worker_b, "office")

        timeline = self._timeline(company_a)
        assert timeline["rows"] == []
        assert [w.name for w in timeline["idle"]] == ["A社の人"]


@pytest.mark.django_db
class TestTimelineOnBoard:
    """月表の下にタイムラインが並ぶこと。"""

    def _worker(self, company):
        return Worker.unscoped.create(
            company=company, name="田中太郎", employee_code="E001", hourly_cost=3000,
        )

    def test_表の下にタイムラインが出る(self, client, company_a, user_a):
        worker = self._worker(company_a)
        AttendPlan.unscoped.create(
            company=company_a, worker=worker, plan_date=DAY, kind="site",
            note="入間基地", start_time=datetime.time(7, 30),
            end_time=datetime.time(16, 0),
        )
        client.force_login(user_a)
        html = client.get(
            "/attendance/plans/?month=2026-09&day=2026-09-10",
        ).content.decode()

        assert "1日のタイムライン" in html
        assert "plan-timeline-bar" in html
        assert "入間基地" in html

    def test_今月を見ているときは今日が選ばれる(self, client, company_a, user_a):
        self._worker(company_a)
        today = timezone.localdate()
        client.force_login(user_a)
        html = client.get(
            f"/attendance/plans/?month={today:%Y-%m}",
        ).content.decode()

        assert f'value="{today:%Y-%m-%d}"' in html

    def test_他の月を見ているときは1日が選ばれる(self, client, company_a, user_a):
        """今日がその月に無いので、先頭の日を出す。"""
        self._worker(company_a)
        today = timezone.localdate()
        other = "2030-04" if today.year != 2030 else "2031-04"
        client.force_login(user_a)
        html = client.get(f"/attendance/plans/?month={other}").content.decode()

        assert f'value="{other}-01"' in html

    def test_予定が無い日は案内を出す(self, client, company_a, user_a):
        self._worker(company_a)
        client.force_login(user_a)
        html = client.get(
            "/attendance/plans/?month=2026-09&day=2026-09-10",
        ).content.decode()

        assert "誰も予定が入っていません" in html
        assert "plan-timeline-bar" not in html

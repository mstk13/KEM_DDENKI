"""ホームのガントチャートと「誰がどの現場へ行くか」（ADR-0032）。

固定したいのは次の点:

1. ホームのガントは工期管理と同じデータ・同じテンプレート
2. 行き先は出社予定の note で束ね、空白の違いは同じ行き先とみなす。未入力は消さずに最後
3. 出社・在宅・休み等は行き先に混ぜず、予定の無い在籍者は人数だけ数える
4. 他社・退職者の予定は出さない
5. ?date= で日を切り替えられ、読めない日付は今日
"""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.attendance.models import AttendPlan
from apps.attendance.plans import UNKNOWN_PLACE, build_day_destinations
from apps.core.tenant_context import set_current_company
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)


def _worker(company, name, code, is_active=True):
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code, hourly_cost=3000, is_active=is_active,
    )


def _plan(worker, kind, note="", day=DAY, **kwargs):
    return AttendPlan.unscoped.create(
        company=worker.company, worker=worker, plan_date=day, kind=kind, note=note, **kwargs,
    )


def _places(result):
    return [(d["place"], [m["worker"].name for m in d["members"]]) for d in result["destinations"]]


@pytest.fixture
def home_client(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


@pytest.mark.django_db
class TestBuildDayDestinations:
    def test_同じ行き先を束ね人数の多い順に並べる(self, company_a):
        _plan(_worker(company_a, "佐藤", "E001"), "site", "A社ビル")
        _plan(_worker(company_a, "鈴木", "E002"), "direct", " A社ビル ")
        _plan(_worker(company_a, "高橋", "E003"), "site", "B工場")
        _plan(_worker(company_a, "田中", "E004"), "trip", "大阪")

        result = build_day_destinations(company_a, DAY)

        assert _places(result) == [
            ("A社ビル", ["佐藤", "鈴木"]),
            ("B工場", ["高橋"]),
            ("大阪", ["田中"]),
        ]

    def test_行き先未入力は消さずに最後にまとめる(self, company_a):
        _plan(_worker(company_a, "佐藤", "E001"), "site", "")
        _plan(_worker(company_a, "鈴木", "E002"), "site", "Z現場")

        result = build_day_destinations(company_a, DAY)

        assert _places(result) == [("Z現場", ["鈴木"]), (UNKNOWN_PLACE, ["佐藤"])]

    def test_出社_在宅_休み等は行き先に混ぜない(self, company_a):
        _plan(_worker(company_a, "出社さん", "E001"), "office")
        _plan(_worker(company_a, "在宅さん", "E002"), "remote")
        _plan(_worker(company_a, "有休さん", "E003"), "paid")
        _plan(_worker(company_a, "休みさん", "E004"), "off")
        _worker(company_a, "未入力さん", "E005")

        result = build_day_destinations(company_a, DAY)

        assert result["destinations"] == []
        assert [m["worker"].name for m in result["office"]] == ["出社さん"]
        assert [m["worker"].name for m in result["remote"]] == ["在宅さん"]
        assert [m["worker"].name for m in result["away"]] == ["有休さん", "休みさん"]
        # 稼働に数えるのは出社・現場・直行直帰・出張だけ（AttendPlan.WORKING_KINDS）
        assert result["working_count"] == 1
        assert result["unplanned_count"] == 1

    def test_時刻と区分名を持つ(self, company_a):
        worker = _worker(company_a, "佐藤", "E001")
        _plan(worker, "direct", "A社ビル",
              start_time=datetime.time(8, 30), end_time=datetime.time(17, 0))

        member = build_day_destinations(company_a, DAY)["destinations"][0]["members"][0]

        assert member["label"] == "直行直帰"
        assert member["time_label"] == "8:30-17"

    def test_他社と退職者と別の日の予定は出さない(self, company_a, company_b):
        _plan(_worker(company_b, "B社の人", "E001"), "site", "A社ビル")
        _plan(_worker(company_a, "退職者", "E002", is_active=False), "site", "A社ビル")
        _plan(_worker(company_a, "翌日の人", "E003"), "site", "A社ビル",
              day=DAY + datetime.timedelta(days=1))

        result = build_day_destinations(company_a, DAY)

        assert result["destinations"] == []
        assert result["unplanned_count"] == 1  # 翌日の人（今日は予定なし）

    def test_前日と翌日(self, company_a):
        result = build_day_destinations(company_a, DAY)

        assert result["prev_date"] == datetime.date(2026, 9, 9)
        assert result["next_date"] == datetime.date(2026, 9, 11)
        assert result["weekday"] == "木"


@pytest.mark.django_db
class TestHomeDayPlanView:
    def test_指定した日の行き先を出す(self, home_client, company_a):
        _plan(_worker(company_a, "佐藤", "E001"), "site", "A社ビル")

        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert "<h2>誰がどの現場へ行くか</h2>" in body
        assert "2026/9/10（木）" in body
        assert "A社ビル" in body
        assert "佐藤" in body
        assert f'{reverse("attendance:plan_day")}?date=2026-09-10' in body
        assert "?date=2026-09-09#home-day" in body
        assert "?date=2026-09-11#home-day" in body

    def test_日付を省略すると今日(self, home_client):
        res = home_client.get(reverse("dashboard"))

        assert res.context["day_plan"]["date"] == timezone.localdate()

    def test_読めない日付は今日(self, home_client):
        res = home_client.get(reverse("dashboard"), {"date": "2026-13-40"})

        assert res.context["day_plan"]["date"] == timezone.localdate()

    def test_予定が無い日は空の表示(self, home_client):
        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert "この日の現場・直行直帰・出張の予定はありません" in body

    def test_最近の日報は出さない(self, home_client):
        body = home_client.get(reverse("dashboard")).content.decode()

        assert "最近の日報" not in body


@pytest.mark.django_db
class TestHomeGantt:
    def test_工期管理と同じガントを出す(self, home_client, company_a):
        Site.unscoped.create(
            company=company_a, code="S1", name="A社ビル新築", status=Site.Status.IN_PROGRESS,
            start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2026, 10, 31),
        )

        home = home_client.get(reverse("dashboard"))
        schedules = home_client.get(reverse("schedules:list"))

        assert home.context["gantt_tasks_exist"] is True
        assert home.context["gantt_json"] == schedules.context["gantt_json"]
        for res in (home, schedules):
            body = res.content.decode()
            assert 'id="gantt-chart"' in body
            assert "A社ビル新築" in body
        assert "schedules/partials/gantt_chart.html" in [t.name for t in home.templates]
        assert "schedules/partials/gantt_chart.html" in [t.name for t in schedules.templates]

    def test_工期の無い会社は空の表示(self, home_client):
        body = home_client.get(reverse("dashboard")).content.decode()

        assert 'id="gantt-chart"' not in body
        assert "表示できる工期がありません" in body

    def test_ポップアップの現場名は逃がしてから差し込む(self, home_client, company_a):
        """現場名は入力値。custom_popup_html にそのまま連結すると HTML として解釈される。"""
        Site.unscoped.create(
            company=company_a, code="S1", name="現場", status=Site.Status.IN_PROGRESS,
            start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2026, 10, 31),
        )

        body = home_client.get(reverse("dashboard")).content.decode()

        assert "escapeHtml(task.name)" in body

"""ガントチャートは当日から先だけを出す（ADR-0072）。

- 終わった予定（終了日が昨日以前）は出さない
- 始まっている予定は当日から描く。実際の開始日は real_start に残す
- 比較表の工期・日数はもとの日付のまま
"""

import datetime
import json

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.schedules.models import Milestone, Phase
from apps.schedules.services import clip_gantt_tasks_to_today
from apps.sites.models import Site

TODAY = datetime.date(2026, 9, 16)


def _task(start, end, task_id="site-1"):
    return {
        "id": task_id, "name": "A現場", "start": start, "end": end,
        "progress": 0, "custom_class": "bar-blue",
    }


def _site(company, name, start, end, status=Site.Status.IN_PROGRESS):
    return Site.unscoped.create(
        company=company, code=name, name=name, status=status,
        contract_amount=1000000, start_date=start, end_date=end,
    )


def _days(n):
    return timezone.localdate() + datetime.timedelta(days=n)


class TestClip:
    def test_終わった予定は出さない(self):
        tasks = [_task("2026-09-01", "2026-09-15"), _task("2026-09-10", "2026-09-16", "site-2")]

        clipped = clip_gantt_tasks_to_today(tasks, TODAY)

        assert [t["id"] for t in clipped] == ["site-2"]

    def test_始まっている予定は当日から描き実際の開始日を残す(self):
        clipped = clip_gantt_tasks_to_today([_task("2026-09-01", "2026-09-30")], TODAY)

        assert clipped[0]["start"] == "2026-09-16"
        assert clipped[0]["real_start"] == "2026-09-01"
        assert clipped[0]["end"] == "2026-09-30"

    def test_これからの予定はそのまま(self):
        clipped = clip_gantt_tasks_to_today([_task("2026-09-20", "2026-09-30")], TODAY)

        assert clipped[0]["start"] == "2026-09-20"
        assert "real_start" not in clipped[0]

    def test_もとのデータは変えない(self):
        tasks = [_task("2026-09-01", "2026-09-30")]

        clip_gantt_tasks_to_today(tasks, TODAY)

        assert tasks[0]["start"] == "2026-09-01"


@pytest.mark.django_db
class TestScreens:
    def test_ホームのガントは当日から始まる(self, client, company_a, user_a):
        _site(company_a, "続いている現場", _days(-10), _days(10))
        _site(company_a, "終わった現場", _days(-30), _days(-1))
        client.force_login(user_a)

        res = client.get("/")

        tasks = json.loads(res.context["gantt_json"])
        assert [t["name"] for t in tasks] == ["続いている現場"]
        assert tasks[0]["start"] == timezone.localdate().isoformat()
        assert tasks[0]["real_start"] == _days(-10).isoformat()

    def test_工期管理のガントは当日から_比較表はもとの日付(self, client, company_a, user_a):
        site = _site(company_a, "続いている現場", _days(-10), _days(10))
        _site(company_a, "終わった現場", _days(-30), _days(-1))
        client.force_login(user_a)

        res = client.get(reverse("schedules:list"))

        tasks = json.loads(res.context["gantt_json"])
        assert [t["name"] for t in tasks] == ["続いている現場"]
        assert tasks[0]["start"] == timezone.localdate().isoformat()
        legend = {row["name"]: row for row in res.context["legend"]}
        assert legend["続いている現場"]["start"] == site.start_date
        assert legend["終わった現場"]["days"] == 30

    def test_目盛りの左端も当日にする(self, client, company_a, user_a):
        """frappe-gantt は開始日の1か月前から目盛りを引くので、画面側で当日に詰める。"""
        _site(company_a, "続いている現場", _days(-10), _days(10))
        client.force_login(user_a)

        home = client.get("/").content.decode()
        compare = client.get(reverse("schedules:list")).content.decode()

        assert "clampGanttStartToToday(Gantt);" in home
        assert "clampGanttStartToToday(Gantt);" in compare
        # 左端のラベル（当日）が枠の外に出て切れないようにする
        assert "showFirstGanttLabel(chart);" in home
        assert "showFirstGanttLabel(chart);" in compare

    def test_現場の工程も当日から(self, client, company_a, user_a):
        site = _site(company_a, "A現場", _days(-20), _days(20))
        Phase.unscoped.create(
            company=company_a, site=site, name="終わった工程",
            start_date=_days(-20), end_date=_days(-5), sort_order=1,
        )
        Phase.unscoped.create(
            company=company_a, site=site, name="続いている工程",
            start_date=_days(-5), end_date=_days(5), sort_order=2,
        )
        Milestone.unscoped.create(
            company=company_a, site=site, name="過ぎた節目", target_date=_days(-2),
        )
        client.force_login(user_a)

        res = client.get(reverse("schedules:detail", args=[site.pk]))

        tasks = json.loads(res.context["gantt_json"])
        assert [t["name"] for t in tasks] == ["続いている工程"]
        assert tasks[0]["start"] == timezone.localdate().isoformat()
        assert tasks[0]["real_start"] == _days(-5).isoformat()

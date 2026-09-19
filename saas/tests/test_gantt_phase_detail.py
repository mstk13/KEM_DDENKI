"""ガントで「いつからいつまで何をするか」を読めるようにする（ADR-0101）。

固定したいのは次の点:

1. 現場詳細（工期）のバーには、工程名だけでなく **期間と日数** を書く
2. 期日1日のマイルストーンは「〜」を付けず、日付だけを添える
3. ホーム・工期管理のバーには、現場の中の **工程の区切り**（segments）を渡す
4. 区切りは開始日順。日付の入っていない工程は渡さない（区切れないため）
5. 工期日数は両端を含めて数える（1日工事なら1日）
6. 画面に、区切りを描く処理が読み込まれている
"""

import datetime

import pytest
from django.urls import reverse

from apps.schedules.models import Milestone, Phase
from apps.schedules.services import (
    get_comparison_gantt_data,
    get_site_gantt_data,
)
from apps.sites.models import Site

DAY = datetime.date(2026, 9, 1)


def _site(company, code="S001", name="七沢センター改修", **kwargs):
    fields = {
        "status": Site.Status.IN_PROGRESS,
        "start_date": DAY,
        "end_date": DAY + datetime.timedelta(days=29),
    }
    fields.update(kwargs)
    return Site.unscoped.create(company=company, code=code, name=name, **fields)


def _phase(site, name, start, end, order=0, **kwargs):
    return Phase.unscoped.create(
        company=site.company, site=site, name=name,
        start_date=start, end_date=end, sort_order=order, **kwargs,
    )


# ---------------------------------------------------------------------------
# 現場詳細（工期）のガント
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSiteGantt:
    def test_バーに期間と日数を書く(self, company_a):
        site = _site(company_a)
        _phase(site, "仮設工事", DAY, DAY + datetime.timedelta(days=4))

        task = get_site_gantt_data(site)[0]

        assert task["name"] == "仮設工事  9/1〜9/5（5日）"
        assert task["title"] == "仮設工事"
        assert task["days"] == 5

    def test_1日で終わる工程も1日と数える(self, company_a):
        site = _site(company_a)
        _phase(site, "試験", DAY, DAY)

        task = get_site_gantt_data(site)[0]

        assert task["days"] == 1
        assert "9/1〜9/1（1日）" in task["name"]

    def test_メモも画面に渡す(self, company_a):
        """「何をするのか」は工程名だけでは足りないことがある。"""
        site = _site(company_a)
        _phase(site, "施工", DAY, DAY + datetime.timedelta(days=9), memo="3階から先に着手")

        assert get_site_gantt_data(site)[0]["memo"] == "3階から先に着手"

    def test_マイルストーンは日付だけ添える(self, company_a):
        site = _site(company_a)
        Milestone.unscoped.create(
            company=company_a, site=site, name="中間検査", target_date=DAY,
        )

        task = get_site_gantt_data(site)[0]

        assert task["name"] == "◆ 中間検査（9/1）"
        assert task["title"] == "中間検査"
        assert "〜" not in task["name"]

    def test_日付の無い工程は出さない(self, company_a):
        site = _site(company_a)
        _phase(site, "未定", None, None)

        assert get_site_gantt_data(site) == []


# ---------------------------------------------------------------------------
# ホーム・工期管理のガント（現場1本の中を工程で区切る）
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestComparisonGantt:
    def test_現場のバーに工程の区切りを渡す(self, company_a):
        site = _site(company_a)
        _phase(site, "仮設", DAY, DAY + datetime.timedelta(days=4), order=1)
        _phase(site, "配線", DAY + datetime.timedelta(days=5),
               DAY + datetime.timedelta(days=19), order=2)

        task = get_comparison_gantt_data(company_a)["tasks"][0]

        assert [s["name"] for s in task["segments"]] == ["仮設", "配線"]
        assert [s["days"] for s in task["segments"]] == [5, 15]

    def test_区切りは開始日順に並べる(self, company_a):
        """表示順が実際の日付と食い違っていても、図は日付の順で読む。"""
        site = _site(company_a)
        _phase(site, "あと", DAY + datetime.timedelta(days=10),
               DAY + datetime.timedelta(days=14), order=1)
        _phase(site, "さき", DAY, DAY + datetime.timedelta(days=4), order=2)

        segments = get_comparison_gantt_data(company_a)["tasks"][0]["segments"]

        assert [s["name"] for s in segments] == ["さき", "あと"]

    def test_日付の無い工程は区切りに入れない(self, company_a):
        site = _site(company_a)
        _phase(site, "仮設", DAY, DAY + datetime.timedelta(days=4), order=1)
        _phase(site, "未定", None, None, order=2)

        segments = get_comparison_gantt_data(company_a)["tasks"][0]["segments"]

        assert [s["name"] for s in segments] == ["仮設"]

    def test_工程が無ければ区切りは空(self, company_a):
        _site(company_a)

        assert get_comparison_gantt_data(company_a)["tasks"][0]["segments"] == []

    def test_現場のバーにも日数を持たせる(self, company_a):
        _site(company_a)

        assert get_comparison_gantt_data(company_a)["tasks"][0]["days"] == 30

    def test_区切りには工程の色を渡す(self, company_a):
        site = _site(company_a)
        _phase(site, "仮設", DAY, DAY + datetime.timedelta(days=4), color="#ef4444")

        segments = get_comparison_gantt_data(company_a)["tasks"][0]["segments"]

        assert segments[0]["color"] == "#ef4444"


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestScreens:
    def test_ホームに区切りを描く処理が入っている(self, client, company_a, user_a):
        site = _site(company_a)
        _phase(site, "仮設", DAY, DAY + datetime.timedelta(days=4))
        client.force_login(user_a)

        html = client.get(reverse("dashboard")).content.decode()

        assert "drawGanttPhaseDividers" in html
        assert "segments" in html

    def test_現場詳細のバーに期間が入っている(self, client, company_a, user_a):
        site = _site(company_a)
        _phase(site, "仮設工事", DAY, DAY + datetime.timedelta(days=4))
        client.force_login(user_a)

        html = client.get(reverse("schedules:detail", args=[site.pk])).content.decode()

        assert "9/1\\u301c9/5" in html or "9/1〜9/5" in html


# ---------------------------------------------------------------------------
# テナント越境
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の現場は出さない(self, company_a, company_b):
        _site(company_b, code="B001", name="他社の現場")

        assert get_comparison_gantt_data(company_a)["tasks"] == []

    def test_他社の工程は区切りに入らない(self, company_a, company_b):
        mine = _site(company_a)
        other = _site(company_b, code="B001", name="他社の現場")
        _phase(other, "他社の工程", DAY, DAY + datetime.timedelta(days=4))
        _phase(mine, "自社の工程", DAY, DAY + datetime.timedelta(days=4))

        segments = get_comparison_gantt_data(company_a)["tasks"][0]["segments"]

        assert [s["name"] for s in segments] == ["自社の工程"]

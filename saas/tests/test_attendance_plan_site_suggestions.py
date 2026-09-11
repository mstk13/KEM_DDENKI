"""出社予定の「場所・メモ」に登録済みの現場名を候補として出す（ADR-0037）。

固定したいのは次の点:

1. 候補は自社の 施工中 → 受注済 → 見積中 の現場名。終わった現場は出さない。同じ名前は1つ
2. 月グリッドのダイアログと日シートの入力欄に候補（<datalist>）が付く
3. 候補は手助けにすぎず、候補にない行き先もそのまま保存できる
"""

import pytest

from apps.attendance.models import AttendPlan
from apps.attendance.plans import site_name_suggestions
from apps.sites.models import Site
from apps.workers.models import Worker


def _site(company, code, name, status):
    return Site.unscoped.create(company=company, code=code, name=name, status=status)


def _worker(company, name="田中太郎"):
    return Worker.unscoped.create(
        company=company, name=name, employee_code="E001", hourly_cost=3000,
    )


@pytest.mark.django_db
class TestSiteNameSuggestions:
    def test_行き先になりうる現場だけを状態の順に並べる(self, company_a):
        _site(company_a, "S1", "C見積中の現場", Site.Status.ESTIMATING)
        _site(company_a, "S2", "B受注済の現場", Site.Status.ORDERED)
        _site(company_a, "S3", "A施工中の現場", Site.Status.IN_PROGRESS)
        _site(company_a, "S4", "Z施工中の現場", Site.Status.IN_PROGRESS)
        _site(company_a, "S5", "完工した現場", Site.Status.COMPLETED)
        _site(company_a, "S6", "請求済の現場", Site.Status.BILLED)
        _site(company_a, "S7", "中止した現場", Site.Status.CANCELLED)

        assert site_name_suggestions(company_a) == [
            "A施工中の現場", "Z施工中の現場", "B受注済の現場", "C見積中の現場",
        ]

    def test_同じ名前は1つにまとめ前後の空白を除く(self, company_a):
        _site(company_a, "S1", "A社ビル新築", Site.Status.IN_PROGRESS)
        _site(company_a, "S2", " A社ビル新築 ", Site.Status.ORDERED)

        assert site_name_suggestions(company_a) == ["A社ビル新築"]

    def test_他社の現場は出さない(self, company_a, company_b):
        _site(company_a, "S1", "A社の現場", Site.Status.IN_PROGRESS)
        _site(company_b, "S1", "B社の現場", Site.Status.IN_PROGRESS)

        assert site_name_suggestions(company_a) == ["A社の現場"]


@pytest.mark.django_db
class TestSuggestionsOnScreens:
    def test_月グリッドのダイアログに候補が付く(self, client, company_a, company_b, user_a):
        _worker(company_a)
        _site(company_a, "S1", "A社ビル新築", Site.Status.IN_PROGRESS)
        _site(company_b, "S1", "B社の現場", Site.Status.IN_PROGRESS)
        client.force_login(user_a)

        html = client.get("/attendance/plans/?month=2026-09").content.decode()

        assert '<datalist id="attend-site-names">' in html
        assert '<option value="A社ビル新築"></option>' in html
        assert "B社の現場" not in html
        assert 'id="plan-dialog-note" maxlength="200"' in html
        assert 'list="attend-site-names"' in html

    def test_日シートの行き先欄に候補が付く(self, client, company_a, user_a):
        worker = _worker(company_a)
        _site(company_a, "S1", "A社ビル新築", Site.Status.IN_PROGRESS)
        client.force_login(user_a)

        html = client.get("/attendance/plans/day/?date=2026-09-10").content.decode()

        assert html.count('<datalist id="attend-site-names">') == 1
        assert '<option value="A社ビル新築"></option>' in html
        assert f'name="note_{worker.pk}"' in html
        assert 'list="attend-site-names" autocomplete="off"' in html

    def test_候補にない行き先もそのまま保存できる(self, client, company_a, user_a):
        worker = _worker(company_a)
        _site(company_a, "S1", "A社ビル新築", Site.Status.IN_PROGRESS)
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"kind_{worker.pk}": "trip",
            f"note_{worker.pk}": "大阪 支店",
        })

        plan = AttendPlan.unscoped.get(company=company_a, worker=worker)
        assert plan.note == "大阪 支店"

    def test_現場がひとつも無くても画面は出る(self, client, company_a, user_a):
        _worker(company_a)
        client.force_login(user_a)

        res = client.get("/attendance/plans/day/?date=2026-09-10")

        assert res.status_code == 200
        assert res.context["site_names"] == []

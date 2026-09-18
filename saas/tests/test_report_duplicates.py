"""同じ日に同じ人の日報が二重に入るのを止める（ADR-0079・ADR-0100）。

- 同じ日・同じ人（同姓同名を含む）の日報は見つける
- **止めるのは同じ現場のときだけ。** 別の現場は1日2現場として素通しする（ADR-0100）
- 「このまま登録する」で送り直したときだけ保存する
"""

import datetime

import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.duplicates import find_duplicate_reports, needs_confirmation
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)


@pytest.fixture
def setup(company_a, user_a):
    site_a = Site.unscoped.create(company=company_a, code="S001", name="A現場")
    site_b = Site.unscoped.create(company=company_a, code="S002", name="B現場")
    work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
    worker = Worker.unscoped.create(company=company_a, name="電工太郎", user=user_a)
    return site_a, site_b, work_type, worker


def _report(company, user, site, work_type, worker, day=DAY):
    return DailyReport.unscoped.create(
        company=company, created_by=user, site=site, work_type=work_type,
        worker=worker, report_date=day, work_hours=8,
    )


def _post(client, site, work_type, worker, extra=None):
    data = {
        "report_date": DAY.isoformat(),
        "site": site.name,
        "work_type": work_type.name,
        "workers": [str(worker.pk)],
        "work_description": "配線",
        "work_hours": "8",
        "action": "draft",
    }
    data.update(extra or {})
    return client.post(reverse("reports:create"), data)


@pytest.mark.django_db
class TestFind:
    def test_同じ日の日報を見つける(self, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)

        found = find_duplicate_reports(company_a, [worker], DAY)

        assert len(found) == 1
        assert found[0]["worker"] == worker
        assert len(found[0]["reports"]) == 1

    def test_別の日なら重複ではない(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)

        assert find_duplicate_reports(
            company_a, [worker], DAY + datetime.timedelta(days=1),
        ) == []

    def test_同姓同名の別登録も重複とみなす(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        same_name = Worker.unscoped.create(company=company_a, name="電工太郎")
        _report(company_a, user_a, site_a, work_type, worker)

        found = find_duplicate_reports(company_a, [same_name], DAY)

        assert len(found) == 1

    def test_編集中の日報は自分を数えない(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        report = _report(company_a, user_a, site_a, work_type, worker)

        assert find_duplicate_reports(
            company_a, [worker], DAY, exclude_pk=report.pk,
        ) == []


@pytest.mark.django_db
class TestCreateScreen:
    def test_同じ現場の重複は保存せずに知らせる(self, client, company_a, user_a, setup):
        """同じ現場に1日2回書くのは、うっかりの可能性が高い。"""
        site_a, _b, work_type, worker = setup
        other_type = WorkType.unscoped.create(
            company=company_a, code="W02", name="通信工事",
        )
        _report(company_a, user_a, site_a, work_type, worker)
        client.force_login(user_a)

        res = _post(client, site_a, other_type, worker)

        assert res.status_code == 200
        html = res.content.decode()
        assert "重複があります" in html
        assert "A現場" in html
        assert "このまま登録する" in html
        assert DailyReport.unscoped.filter(work_type=other_type).count() == 0

    def test_このまま登録すると保存する(self, client, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        other_type = WorkType.unscoped.create(
            company=company_a, code="W02", name="通信工事",
        )
        _report(company_a, user_a, site_a, work_type, worker)
        client.force_login(user_a)

        res = _post(client, site_a, other_type, worker, {"confirm_duplicate": "1"})

        assert res.status_code == 302
        assert DailyReport.unscoped.filter(work_type=other_type).count() == 1

    def test_別の現場なら止めずに保存する(self, client, company_a, user_a, setup):
        """1日に2現場へ行く日は普通にある。午前A現場・午後B現場（ADR-0100）。"""
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker, {"work_hours": "4"})

        assert res.status_code == 302
        assert DailyReport.unscoped.filter(site=site_b).count() == 1

    def test_重複が無ければそのまま保存する(self, client, company_a, user_a, setup):
        _a, site_b, work_type, worker = setup
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker)

        assert res.status_code == 302
        assert DailyReport.unscoped.filter(site=site_b).count() == 1


# ---------------------------------------------------------------------------
# 1日を現場ごとに分けて入れる（ADR-0100）
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSplitDay:
    def test_同じ現場かどうかを見分ける(self, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)

        same = find_duplicate_reports(
            company_a, [worker], DAY, site_name=site_a.name,
        )
        other = find_duplicate_reports(
            company_a, [worker], DAY, site_name=site_b.name,
        )

        assert same[0]["same_site_reports"]
        assert other[0]["same_site_reports"] == []
        assert needs_confirmation(same) is True
        assert needs_confirmation(other) is False

    def test_その日に入っている時間を返す(self, company_a, user_a, setup):
        site_a, _b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)

        found = find_duplicate_reports(company_a, [worker], DAY, site_name="B現場")

        assert found[0]["hours"] == 8

    def test_午前と午後で分けて登録できる(self, client, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        client.force_login(user_a)

        first = _post(client, site_a, work_type, worker, {"work_hours": "4"})
        second = _post(client, site_b, work_type, worker, {"work_hours": "4"})

        assert first.status_code == 302
        assert second.status_code == 302
        hours = sorted(
            DailyReport.unscoped.filter(
                company=company_a, worker=worker, report_date=DAY,
            ).values_list("work_hours", flat=True),
        )
        assert [float(h) for h in hours] == [4.0, 4.0]

    def test_1日24時間を超える入力は弾く(self, client, company_a, user_a, setup):
        """現場をまたぐこと自体は止めないが、24時間超は必ず打ち間違い。"""
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker)  # 8時間
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker, {"work_hours": "20"})

        assert res.status_code == 200
        assert "24 時間まで" in res.content.decode()
        assert DailyReport.unscoped.filter(site=site_b).count() == 0

    def test_分けて入れたら内訳を知らせる(self, client, company_a, user_a, setup):
        site_a, site_b, work_type, worker = setup
        _report(company_a, user_a, site_a, work_type, worker, day=DAY)
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker, {"work_hours": "4"})
        html = client.get(res["Location"]).content.decode()

        assert "合計 12 時間" in html
        assert "A現場" in html and "B現場" in html

    def test_1件しか無い人の内訳は出さない(self, client, company_a, user_a, setup):
        _a, site_b, work_type, worker = setup
        client.force_login(user_a)

        res = _post(client, site_b, work_type, worker, {"work_hours": "8"})
        html = client.get(res["Location"]).content.decode()

        assert "合計" not in html

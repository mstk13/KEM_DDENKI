"""日報の変更履歴を、誰が・いつ・何を直したかまで出す（ADR-0104 改訂）。

現場ごとに複数人ぶんをまとめて登録・修正する使い方（ADR-0056）を残したいので、
**他人の日報も直せるままにした。** その代わり、**抑止は権限ではなくログで行う。**

そのため次の2つが崩れると、緩めた判断の前提が無くなる。

1. 直した人が必ず記録されること（HistoryRequestMiddleware が入っていること）
2. その記録が日報の画面で読めること。/audit-log/ は全モデル横断で1件を追うには
   向かないため、詳細画面に出す

削除だけは所有者の判定を残している。戻せない操作のため。
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.core.change_log import build_change_log
from apps.core.tenant_context import set_current_company
from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 19)


@pytest.fixture
def data(company_a, user_a, django_user_model):
    set_current_company(company_a)
    other_u = django_user_model.objects.create_user(
        username="genba", password="testpass123", company=company_a,
    )
    me = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎",
        hourly_cost=3000, user=user_a,
    )
    other = Worker.unscoped.create(
        company=company_a, employee_code="E002", name="他人花子", hourly_cost=3000,
        user=other_u,
    )
    site = Site.unscoped.create(company=company_a, code="S001", name="A社ビル")
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
    report = DailyReport.unscoped.create(
        company=company_a, site=site, worker=other, work_type=wt,
        report_date=DAY, work_hours=Decimal("8.00"), work_description="配線",
    )
    yield {
        "me": me, "other": other, "site": site, "wt": wt,
        "report": report, "user_a": user_a, "other_u": other_u,
    }
    set_current_company(None)


@pytest.mark.django_db
class TestOthersReportStaysEditable:
    """まとめて修正を残すため、他人の日報も直せること（ADR-0104 改訂）。"""

    def test_他人の日報の編集画面を開ける(self, client, data):
        client.force_login(data["user_a"])

        res = client.get(reverse("reports:edit", args=[data["report"].pk]))

        assert res.status_code == 200

    def test_他人の日報は消せないまま(self, client, data):
        """「直す」は誰でもできるが、「消す」は戻せないので所有者の判定を残す。"""
        client.force_login(data["user_a"])

        res = client.post(reverse("reports:delete", args=[data["report"].pk]))

        assert res.status_code == 403
        assert DailyReport.unscoped.filter(pk=data["report"].pk).exists()


@pytest.mark.django_db
class TestWhoChangedItIsRecorded:
    def test_画面から直すと直した人が記録される(self, client, data):
        """緩めた判断の前提。記録されなければ抑止が無くなる。"""
        client.force_login(data["user_a"])

        client.post(reverse("reports:edit", args=[data["report"].pk]), {
            "site": "A社ビル", "workers": [data["other"].pk],
            "report_date": DAY.isoformat(), "work_type": "電気",
            "work_description": "配線と結線", "work_hours": "8",
            "weather": "", "process": "", "start_date": "", "start_time": "",
            "end_date": "", "end_time": "", "partner": "", "memo": "",
            "action": "draft",
        })

        latest = data["report"].history.first()
        assert latest.history_user == data["user_a"]


@pytest.mark.django_db
class TestChangeLogShowsWhatChanged:
    def test_直前の版との差分が出る(self, data):
        report = data["report"]
        report.work_description = "配線と結線"
        report.save()

        log = build_change_log(report)

        latest = log[0]
        labels = {c.label: (c.old, c.new) for c in latest.changes}
        assert "作業内容" in labels
        assert labels["作業内容"] == ("配線", "配線と結線")

    def test_最初の登録は差分を出さない(self, data):
        log = build_change_log(data["report"])

        assert log[-1].is_first is True

    def test_新しい順に並ぶ(self, data):
        report = data["report"]
        report.work_description = "1回目"
        report.save()
        report.work_description = "2回目"
        report.save()

        log = build_change_log(report)

        assert len(log) == 3
        assert log[0].changes[0].new == "2回目"

    def test_空の項目は空と出す(self, data):
        report = data["report"]
        report.memo = "あとで消す"
        report.save()
        report.memo = ""
        report.save()

        log = build_change_log(report)

        # memo の verbose_name は「その他」。項目名は画面の言葉で出す
        memo = [c for c in log[0].changes if c.label == "その他"]
        assert memo and memo[0].new == "（空）"


@pytest.mark.django_db
class TestDetailScreenShowsTheLog:
    def test_詳細画面に誰がいつ何を直したかが出る(self, client, data):
        report = data["report"]
        report.work_description = "配線と結線"
        report._history_user = data["user_a"]
        report.save()
        client.force_login(data["user_a"])

        body = client.get(
            reverse("reports:detail", args=[report.pk])
        ).content.decode()

        assert "変更履歴" in body
        assert str(data["user_a"]) in body
        assert "作業内容" in body
        assert "配線と結線" in body

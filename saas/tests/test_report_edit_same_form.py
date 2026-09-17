"""日報の編集画面を、日報を書く画面と同じ形にする（ADR-0056）。

- 上の行はこの日報の作業員（チェック済み・時間変更の欄つき）。退職していても出る
- 「作業員の日報をまとめて書く」で他の作業員を足せる（最初は閉じている）
- 足した人には同じ内容の日報を新しく作り、同じ組にする。承認済みの日報から足しても承認済みにしない
- この日報の作業員を外して別の 1 人を選ぶと、この日報の作業員を付け替える
- 上の行の時間変更はこの日報に、足した人には共通の時間を使う
- 同じ現場・日付・工種の日報が既にある人は作らない
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker


@pytest.fixture
def data(company_a, user_a):
    me = Worker.unscoped.create(
        company=company_a, employee_code="E001", name="電工太郎", hourly_cost=3000, user=user_a,
    )
    other = Worker.unscoped.create(
        company=company_a, employee_code="E002", name="佐々木健太郎", hourly_cost=3000,
    )
    office = Worker.unscoped.create(
        company=company_a, employee_code="S001", name="高橋事務子", hourly_cost=3000,
    )
    site = Site.unscoped.create(company=company_a, code="S001", name="A社ビル")
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気")
    report = DailyReport.unscoped.create(
        company=company_a, site=site, worker=me, work_type=wt,
        report_date=datetime.date(2026, 9, 14),
        start_time=datetime.time(8, 30), end_time=datetime.time(17, 30), work_hours=0,
        work_description="配線", created_by=user_a,
    )
    return {"me": me, "other": other, "office": office, "site": site, "wt": wt,
            "report": report}


def _post(workers, **overrides):
    values = {
        "site": "A社ビル", "workers": [w.pk for w in workers],
        "report_date": "2026-09-14", "weather": "", "process": "", "work_type": "電気",
        "work_description": "配線と結線", "start_date": "", "start_time": "08:30",
        "end_date": "", "end_time": "17:30", "work_hours": "", "partner": "", "memo": "",
        "action": "draft",
    }
    values.update(overrides)
    return values


@pytest.mark.django_db
class TestEditScreenLooksLikeCreate:
    def test_上の行はこの日報の作業員でまとめて書くボタンがある(self, client, user_a, data):
        client.force_login(user_a)
        res = client.get(reverse("reports:edit", args=[data["report"].pk]))
        assert res.status_code == 200
        form = res.context["form"]
        assert form.self_row["worker"].pk == data["me"].pk
        assert form.self_row["checked"] is True
        assert form.show_all_workers is False
        body = res.content.decode()
        assert 'id="open-all-workers"' in body
        assert "時間変更" in body
        assert "編集では1人だけ" not in body
        # 他の作業員は左右の列に（チェックなし）
        assert [r["worker"].pk for r in form.worker_rows_field] == [data["other"].pk]
        assert [r["worker"].pk for r in form.worker_rows_other] == [data["office"].pk]
        assert not any(r["checked"] for r in form.worker_rows_field + form.worker_rows_other)

    def test_他人が書いた日報でも上の行はその日報の作業員(self, client, user_a, data, company_a):
        report = DailyReport.unscoped.create(
            company=company_a, site=data["site"], worker=data["other"], work_type=data["wt"],
            report_date=datetime.date(2026, 9, 15), work_hours=Decimal("8.00"),
        )
        client.force_login(user_a)
        form = client.get(reverse("reports:edit", args=[report.pk])).context["form"]
        assert form.self_row["worker"].pk == data["other"].pk
        # ログインした人（電工太郎）は左の列に出る
        assert data["me"].pk in [r["worker"].pk for r in form.worker_rows_field]

    def test_退職した作業員の日報も上の行に出る(self, client, user_a, data):
        Worker.unscoped.filter(pk=data["me"].pk).update(is_active=False)
        client.force_login(user_a)
        form = client.get(reverse("reports:edit", args=[data["report"].pk])).context["form"]
        assert form.self_row["worker"].pk == data["me"].pk


@pytest.mark.django_db
class TestEditSave:
    def test_この日報だけ直す(self, client, user_a, data):
        client.force_login(user_a)
        res = client.post(reverse("reports:edit", args=[data["report"].pk]), _post([data["me"]]))
        assert res.status_code == 302
        assert DailyReport.unscoped.count() == 1
        data["report"].refresh_from_db()
        assert data["report"].work_description == "配線と結線"

    def test_作業員を足すと同じ内容の日報を作り同じ組にする(self, client, user_a, data):
        client.force_login(user_a)
        res = client.post(
            reverse("reports:edit", args=[data["report"].pk]),
            _post([data["me"], data["other"]]), follow=True,
        )
        assert res.status_code == 200
        assert DailyReport.unscoped.count() == 2
        data["report"].refresh_from_db()
        added = DailyReport.unscoped.get(worker=data["other"])
        assert added.work_description == "配線と結線"
        assert (added.start_time, added.end_time) == (datetime.time(8, 30), datetime.time(17, 30))
        assert added.batch is not None and added.batch == data["report"].batch
        assert "佐々木健太郎 の日報を同じ内容で作成しました" in res.content.decode()

    def test_上の行の時間変更はこの日報に_足した人は共通の時間(self, client, user_a, data):
        client.force_login(user_a)
        values = _post([data["me"], data["other"]])
        values[f"start_time_{data['me'].pk}"] = "07:00"
        values[f"end_time_{data['me'].pk}"] = "19:00"
        client.post(reverse("reports:edit", args=[data["report"].pk]), values)
        data["report"].refresh_from_db()
        assert (data["report"].start_time, data["report"].end_time) == (
            datetime.time(7, 0), datetime.time(19, 0),
        )
        added = DailyReport.unscoped.get(worker=data["other"])
        assert (added.start_time, added.end_time) == (datetime.time(8, 30), datetime.time(17, 30))

    def test_この日報の作業員を外して別の人を選ぶと付け替える(self, client, user_a, data):
        client.force_login(user_a)
        res = client.post(
            reverse("reports:edit", args=[data["report"].pk]), _post([data["other"]]),
        )
        assert res.status_code == 302
        assert DailyReport.unscoped.count() == 1
        data["report"].refresh_from_db()
        assert data["report"].worker_id == data["other"].pk

    def test_承認済みの日報から足した日報は承認済みにしない(self, client, user_a, data):
        DailyReport.unscoped.filter(pk=data["report"].pk).update(
            status=DailyReport.Status.APPROVED,
        )
        client.force_login(user_a)
        client.post(
            reverse("reports:edit", args=[data["report"].pk]), _post([data["me"], data["other"]]),
        )
        added = DailyReport.unscoped.get(worker=data["other"])
        assert added.status == DailyReport.Status.DRAFT

    def test_既に同じ日報がある人は作らない(self, client, user_a, data, company_a):
        DailyReport.unscoped.create(
            company=company_a, site=data["site"], worker=data["other"], work_type=data["wt"],
            report_date=datetime.date(2026, 9, 14), work_hours=Decimal("8.00"),
            work_description="先に書いた分",
        )
        client.force_login(user_a)

        # まず「重複があります」で止まる（ADR-0079）
        res = client.post(
            reverse("reports:edit", args=[data["report"].pk]),
            _post([data["me"], data["other"]]),
        )
        assert "重複があります" in res.content.decode()

        # このまま登録すると、既にある日報はそのまま残る
        res = client.post(
            reverse("reports:edit", args=[data["report"].pk]),
            {**_post([data["me"], data["other"]]), "confirm_duplicate": "1"},
            follow=True,
        )
        assert DailyReport.unscoped.filter(worker=data["other"]).count() == 1
        assert DailyReport.unscoped.get(worker=data["other"]).work_description == "先に書いた分"
        assert "既にあるため作成しませんでした" in res.content.decode()

    def test_足した人がいてエラーで戻ると一覧が開いたまま(self, client, user_a, data):
        client.force_login(user_a)
        res = client.post(
            reverse("reports:edit", args=[data["report"].pk]),
            _post([data["me"], data["other"]], site=""),
        )
        assert res.status_code == 200
        assert res.context["form"].show_all_workers is True

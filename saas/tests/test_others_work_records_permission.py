"""他人の日報・勤怠を直せるのは社長・IT・事務員だけ（ADR-0103）。

プロダクトオーナーの指示（2026-09-19）:
「日報および勤務時間の管理で、他人の日報や勤務時間などは社長および IT の人のみが
管理できるようにしてください」。同日のやり取りで次の2点を確定した。

1. **絞るのは「直す・消す」だけ。閲覧は今までどおり。** 他人の日報を見られなく
   すると、現場担当が現場の日報を見る・事務員が集計する・原価や月次集計や PDF が
   読む、という経路が全部止まる
2. **事務員も直せる。** 日報の取りまとめや打ち直しをしているため

**同日に改訂。** 日報の「修正」は誰でもできるように戻した。現場ごとに複数人ぶんを
まとめて修正する使い方（ADR-0056）と両立しないため。抑止はログに移してあり、
そちらは tests/test_report_change_log.py で見る。

このファイルに残しているのは、**改訂後も権限で止めているもの**だけ。

| 対象 | 残っている理由 |
|---|---|
| 日報の**削除** | 戻せない操作のため |
| **勤怠**の書き換え | 今回の指示の対象外。全員の予定の一括削除は特に危険 |
| 権限管理の画面 | 社長と IT が開けること |

塞ぐ前は次の状態だった。

| 経路 | 塞ぐ前 |
|---|---|
| 日報の削除 | 「ログインしていれば誰でも削除できる」（承認済のみ不可） |
| 勤怠のマス塗り・ダイアログ保存 | 本人確認なし。他人の予定を書き換えられた |
| 勤怠の一括埋め | 同上。worker を空にすると在籍中の全員が対象 |
| 勤怠の日まとめ消し | 権限チェックなし。**全員の予定をその日ぶん消せた** |
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.attendance.models import AttendPlan
from apps.core.tenant_context import set_current_company
from apps.masters.models import WorkType
from apps.permissions.models import Role, UserRole
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import JobTitle, Position, Worker

DAY = datetime.date(2026, 9, 19)


def _user(django_user_model, company, username):
    return django_user_model.objects.create_user(
        username=username, password="testpass123", company=company,
    )


def _worker(company, name, code, user=None, position=None, job_title=None):
    return Worker.unscoped.create(
        company=company, employee_code=code, name=name, hourly_cost=3000,
        user=user, position=position, job_title=job_title,
    )


@pytest.fixture
def data(company_a, django_user_model):
    set_current_company(company_a)

    ippan_u = _user(django_user_model, company_a, "ippan")
    other_u = _user(django_user_model, company_a, "other")
    shacho_u = _user(django_user_model, company_a, "shacho")
    it_u = _user(django_user_model, company_a, "it")
    jimu_u = _user(django_user_model, company_a, "jimu")

    shacho_pos = Position.unscoped.create(company=company_a, name="社長")
    it_job = JobTitle.unscoped.create(company=company_a, name="ITインフラ")

    ippan = _worker(company_a, "一般太郎", "E001", user=ippan_u)
    other = _worker(company_a, "他人花子", "E002", user=other_u)
    shacho = _worker(company_a, "社長", "E003", user=shacho_u, position=shacho_pos)
    it = _worker(company_a, "IT担当", "E004", user=it_u, job_title=it_job)
    jimu = _worker(company_a, "事務員", "E005", user=jimu_u)

    role = Role.unscoped.create(company=company_a, code="office_staff", name="事務員")
    UserRole.unscoped.create(company=company_a, user=jimu_u, role=role)

    site = Site.unscoped.create(company=company_a, code="S001", name="A社ビル")
    wt = WorkType.unscoped.create(company=company_a, code="E01", name="電気")

    def report_for(worker):
        return DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker, work_type=wt,
            report_date=DAY, work_hours=Decimal("8.00"),
        )

    yield {
        "ippan_u": ippan_u, "shacho_u": shacho_u, "it_u": it_u, "jimu_u": jimu_u,
        "ippan": ippan, "other": other, "shacho": shacho, "it": it, "jimu": jimu,
        "report_for": report_for, "site": site,
    }
    set_current_company(None)


# ---------------------------------------------------------------- 日報


@pytest.mark.django_db
class TestReportDelete:
    def test_自分の日報は消せる(self, client, data):
        report = data["report_for"](data["ippan"])
        client.force_login(data["ippan_u"])

        assert client.get(reverse("reports:delete", args=[report.pk])).status_code == 200

    def test_他人の日報は一般の人には消せない(self, client, data):
        report = data["report_for"](data["other"])
        client.force_login(data["ippan_u"])

        res = client.post(reverse("reports:delete", args=[report.pk]))

        assert res.status_code == 403
        assert DailyReport.unscoped.filter(pk=report.pk).exists()

    def test_承認済は社長でも消せない(self, client, data):
        report = data["report_for"](data["other"])
        DailyReport.unscoped.filter(pk=report.pk).update(
            status=DailyReport.Status.APPROVED,
        )
        client.force_login(data["shacho_u"])

        res = client.post(reverse("reports:delete", args=[report.pk]))

        assert res.status_code == 403
        assert DailyReport.unscoped.filter(pk=report.pk).exists()


# ---------------------------------------------------------------- 勤怠


@pytest.mark.django_db
class TestAttendanceWrite:
    def _set(self, client, worker):
        return client.post(reverse("attendance:plan_set"), {
            "worker": worker.pk, "date": DAY.isoformat(), "kind": "office",
        })

    def test_自分の予定は塗れる(self, client, data):
        client.force_login(data["ippan_u"])

        assert self._set(client, data["ippan"]).status_code == 200

    def test_他人の予定は一般の人には塗れない(self, client, data):
        client.force_login(data["ippan_u"])

        res = self._set(client, data["other"])

        assert res.status_code == 403
        assert not AttendPlan.unscoped.filter(worker=data["other"]).exists()

    @pytest.mark.parametrize("who", ["shacho_u", "it_u", "jimu_u"])
    def test_社長とITと事務員は他人の予定を塗れる(self, client, data, who):
        client.force_login(data[who])

        assert self._set(client, data["other"]).status_code == 200

    def test_日まとめ消しは一般の人にはできない(self, client, data, company_a):
        AttendPlan.unscoped.create(
            company=company_a, worker=data["other"], plan_date=DAY, kind="office",
        )
        client.force_login(data["ippan_u"])

        res = client.post(reverse("attendance:plan_clear_day"), {
            "date": DAY.isoformat(), "month": "2026-09",
        })

        assert res.status_code == 403
        # 全員ぶんが消えていないこと
        assert AttendPlan.unscoped.filter(worker=data["other"]).exists()

    def test_全員の一括埋めは一般の人にはできない(self, client, data):
        client.force_login(data["ippan_u"])

        res = client.post(reverse("attendance:plan_fill"), {
            "month": "2026-09", "target": "weekday", "kind": "office",
        })

        assert res.status_code == 403
        assert not AttendPlan.unscoped.filter(worker=data["other"]).exists()

    def test_自分ひとりの一括埋めは本人でもできる(self, client, data):
        client.force_login(data["ippan_u"])

        res = client.post(reverse("attendance:plan_fill"), {
            "worker": data["ippan"].pk,
            "month": "2026-09", "target": "weekday", "kind": "office",
        })

        assert res.status_code in (200, 302)
        assert AttendPlan.unscoped.filter(worker=data["ippan"]).exists()


# ---------------------------------------------------------------- 権限画面


@pytest.mark.django_db
class TestPermissionScreenOpensForIt:
    """IT が権限画面を開けること（ADR-0103）。

    ガードが settings の admin ロールだけを見ていたため、developer ロールが
    本番で0件の IT は開けなかった（ADR-0039 と同じ問題）。
    """

    @pytest.mark.parametrize("who", ["shacho_u", "it_u"])
    def test_社長とITは機能ごとのチェック表を開ける(self, client, data, who):
        client.force_login(data[who])

        assert client.get(reverse("permissions:app_access")).status_code == 200

    def test_一般の人は開けない(self, client, data):
        client.force_login(data["ippan_u"])

        assert client.get(reverse("permissions:app_access")).status_code == 403

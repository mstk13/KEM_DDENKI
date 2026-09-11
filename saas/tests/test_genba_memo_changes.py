"""現場ヒアリングメモ（2026-08）で挙がった変更点のテスト。

対象:
- 現場の見積担当者
- 日報の種別（モデルには残すが、入力画面からは外した）
- 協力会社欄は「協力会社の作業員」の場合のみ
- 日報の承認は社長とITのみ
- 工程の手入力（Process の作成・編集・削除）
- 権限エラー時に 403 テンプレートが使われること
"""

from decimal import Decimal

import pytest

from apps.masters.models import CostCategory, Supplier, WorkType
from apps.permissions.models import Role, UserRole
from apps.permissions.services import can_approve_report
from apps.reports.forms import DailyReportForm
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Position, Worker


@pytest.fixture
def work_type(company_a):
    return WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")


@pytest.fixture
def site(company_a):
    return Site.unscoped.create(
        company=company_a,
        code="S001",
        name="A社ビル新築",
        status=Site.Status.IN_PROGRESS,
        contract_amount=5000000,
    )


@pytest.fixture
def worker(company_a):
    return Worker.unscoped.create(
        company=company_a, employee_code="E001", name="田中太郎",
        name_kana="タナカタロウ", hourly_cost=3000,
    )


@pytest.fixture
def supplier(company_a):
    return Supplier.unscoped.create(
        company=company_a, code="SUP1", name="協力電設",
    )


def _report_post_data(site, worker, work_type, **overrides):
    data = {
        # 現場・工種・工程は名前で送る（一覧から選んでも手入力でも同じ）
        "site": site.name,
        # 作業員は複数選べる
        "workers": [worker.pk],
        "report_date": "2026-08-01",
        "weather": "",
        "process": "",
        "work_type": work_type.name,
        "work_description": "配線作業",
        "start_time": "",
        "end_time": "",
        "work_hours": "8.00",
        "partner": "",
        "memo": "",
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# 現場: 見積担当者
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSiteEstimator:
    def test_estimator_can_be_set(self, company_a, user_a, site):
        site.estimator = user_a
        site.save()
        site.refresh_from_db()
        assert site.estimator == user_a

    def test_estimator_is_optional(self, site):
        assert site.estimator is None

    def test_site_form_includes_estimator(self, company_a):
        from apps.sites.forms import SiteForm

        form = SiteForm(company=company_a)
        assert "estimator" in form.fields


# ---------------------------------------------------------------------------
# 日報: 種別
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDailyReportType:
    def test_choices_match_memo(self):
        labels = [label for _value, label in DailyReport.ReportType.choices]
        assert labels == ["管理", "事務", "電工", "IT"]

    def test_default_is_electrician(self, company_a, site, worker, work_type):
        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
        )
        assert report.report_type == DailyReport.ReportType.ELECTRICIAN

    def test_form_has_no_report_type(self, company_a):
        """種別は入力しない（モデルの既定値のまま保存される）。"""
        form = DailyReportForm(company=company_a)
        assert "report_type" not in form.fields


# ---------------------------------------------------------------------------
# 日報: 協力会社は該当時のみ
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestPartnerField:
    def test_partner_required_when_partner_worker(
        self, company_a, site, worker, work_type,
    ):
        form = DailyReportForm(
            data=_report_post_data(
                site, worker, work_type, is_partner_worker="on",
            ),
            company=company_a,
        )
        assert not form.is_valid()
        assert "partner" in form.errors

    def test_partner_accepted_when_partner_worker(
        self, company_a, site, worker, work_type, supplier,
    ):
        form = DailyReportForm(
            data=_report_post_data(
                site, worker, work_type,
                is_partner_worker="on", partner=supplier.pk,
            ),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        assert form.cleaned_data["partner"] == supplier

    def test_partner_cleared_when_not_partner_worker(
        self, company_a, site, worker, work_type, supplier,
    ):
        """自社作業員なのに協力会社が選ばれていたら無視する。"""
        form = DailyReportForm(
            data=_report_post_data(
                site, worker, work_type, partner=supplier.pk,
            ),
            company=company_a,
        )
        assert form.is_valid(), form.errors
        report = form.save(commit=False)
        assert report.partner is None


# ---------------------------------------------------------------------------
# 日報: 承認できるのは社長とITのみ
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestApprovalPermission:
    def test_plain_user_cannot_approve(self, user_a):
        assert can_approve_report(user_a) is False

    def test_president_position_can_approve(self, company_a, user_a):
        position = Position.unscoped.create(company=company_a, name="社長", rank=1)
        Worker.unscoped.create(
            company=company_a, name="社長太郎", hourly_cost=0,
            position=position, user=user_a,
        )
        user_a.refresh_from_db()
        assert can_approve_report(user_a) is True

    def test_developer_role_can_approve(self, company_a, user_a):
        role = Role.unscoped.create(
            company=company_a, code="developer", name="開発者",
        )
        UserRole.unscoped.create(company=company_a, user=user_a, role=role)
        assert can_approve_report(user_a) is True

    def test_developer_position_can_approve(self, company_a, user_a):
        """IT 担当は役職「Developer」。本番はロールが0件なので役職で通す（ADR-0039）。"""
        position = Position.unscoped.create(company=company_a, name="Developer", rank=8)
        Worker.unscoped.create(
            company=company_a, name="開発花子", hourly_cost=0,
            position=position, user=user_a,
        )
        user_a.refresh_from_db()
        assert can_approve_report(user_a) is True

    @pytest.mark.parametrize("name", ["役員", "正社員", "developer"])
    def test_other_positions_cannot_approve(self, company_a, user_a, name):
        """社長・Developer 以外の役職は承認できない。役職名は大文字小文字も一致させる。"""
        position = Position.unscoped.create(company=company_a, name=name, rank=5)
        Worker.unscoped.create(
            company=company_a, name="一般次郎", hourly_cost=0,
            position=position, user=user_a,
        )
        user_a.refresh_from_db()
        assert can_approve_report(user_a) is False

    def test_developer_position_sees_approve_button_and_can_approve(
        self, client, company_a, user_a, site, worker, work_type,
    ):
        # 承認すると労務費を計上する。原価区分は全テナント共通のシステム定義（apps/core/seed.py）
        CostCategory.objects.get_or_create(
            code="labor", defaults={"name": "労務費", "display_order": 2},
        )
        position = Position.unscoped.create(company=company_a, name="Developer", rank=8)
        Worker.unscoped.create(
            company=company_a, name="開発花子", hourly_cost=0,
            position=position, user=user_a,
        )
        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
            status=DailyReport.Status.SUBMITTED,
        )
        client.force_login(user_a)

        body = client.get("/reports/").content.decode()
        assert f"/reports/{report.pk}/approve/" in body
        assert "選択した日報を一括承認" in body

        client.get(f"/reports/{report.pk}/approve/")
        report.refresh_from_db()
        assert report.status == DailyReport.Status.APPROVED

    def test_approve_view_forbidden_for_plain_user(
        self, client, company_a, user_a, site, worker, work_type,
    ):
        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
            status=DailyReport.Status.SUBMITTED,
        )
        client.force_login(user_a)
        response = client.get(f"/reports/{report.pk}/approve/")
        assert response.status_code == 403
        report.refresh_from_db()
        assert report.status == DailyReport.Status.SUBMITTED

    def test_bulk_approve_forbidden_for_plain_user(self, client, user_a):
        client.force_login(user_a)
        response = client.post("/reports/approve/bulk/", {"report_ids": []})
        assert response.status_code == 403


# ---------------------------------------------------------------------------
# 工程の手入力
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestProcessManualEntry:
    def test_create_process_from_site(
        self, client, company_a, user_a, site, work_type,
    ):
        client.force_login(user_a)
        response = client.post(
            f"/sites/{site.pk}/processes/new/",
            {
                "name": "幹線敷設",
                "work_type": work_type.pk,
                "planned_start": "2026-09-01",
                "planned_end": "2026-09-30",
                "actual_start": "",
                "actual_end": "",
                "status": Process.Status.PLANNED,
                "display_order": 0,
            },
        )
        assert response.status_code == 302
        process = Process.unscoped.get(site=site, name="幹線敷設")
        assert process.company == company_a

    def test_end_before_start_is_rejected(
        self, client, user_a, site, work_type,
    ):
        client.force_login(user_a)
        response = client.post(
            f"/sites/{site.pk}/processes/new/",
            {
                "name": "逆転工程",
                "work_type": work_type.pk,
                "planned_start": "2026-09-30",
                "planned_end": "2026-09-01",
                "actual_start": "",
                "actual_end": "",
                "status": Process.Status.PLANNED,
                "display_order": 0,
            },
        )
        assert response.status_code == 200
        assert not Process.unscoped.filter(name="逆転工程").exists()

    def test_edit_and_delete_process(
        self, client, company_a, user_a, site, work_type,
    ):
        process = Process.unscoped.create(
            company=company_a, site=site, work_type=work_type, name="仮設",
        )
        client.force_login(user_a)

        response = client.post(
            f"/sites/processes/{process.pk}/edit/",
            {
                "name": "仮設電気",
                "work_type": work_type.pk,
                "planned_start": "",
                "planned_end": "",
                "actual_start": "",
                "actual_end": "",
                "status": Process.Status.IN_PROGRESS,
                "display_order": 10,
            },
        )
        assert response.status_code == 302
        process.refresh_from_db()
        assert process.name == "仮設電気"

        response = client.post(f"/sites/processes/{process.pk}/delete/")
        assert response.status_code == 302
        assert not Process.unscoped.filter(pk=process.pk).exists()


# ---------------------------------------------------------------------------
# 403 画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestForbiddenPage:
    def test_403_uses_styled_template(
        self, client, company_a, user_a, site, worker, work_type,
    ):
        """権限エラーがレイアウト付きの 403 テンプレートで返ること。"""
        report = DailyReport.unscoped.create(
            company=company_a, site=site, worker=worker,
            report_date="2026-08-01", work_type=work_type,
            work_hours=Decimal("8.00"),
            status=DailyReport.Status.SUBMITTED,
        )
        client.force_login(user_a)
        response = client.get(f"/reports/{report.pk}/approve/")

        assert response.status_code == 403
        body = response.content.decode()
        # base.html を継承しているのでサイドバーが含まれる
        assert "sidebar" in body
        assert "アクセス権限がありません" in body

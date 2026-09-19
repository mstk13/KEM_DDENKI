"""一覧から選んだものをまとめて消す（ADR-0098）。

- 消せるのは決めた対象だけ。他社の行は選んでも消えない
- 画面ごとの決まり（承認済みの日報は消せない）はそのまま効く
- ほかから使われていて消せない行は残し、名前を知らせる
"""

import datetime

import pytest
from django.urls import reverse

from apps.masters.models import Customer, WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Site
from apps.workers.models import Worker

URL = "/bulk-delete/"


def _site(company, code="S001", name="A現場"):
    return Site.unscoped.create(company=company, code=code, name=name)


@pytest.fixture(autouse=True)
def _as_office_staff(user_a_is_office_staff):
    """まとめて削除は事務員・管理者が使う画面として動かす（ADR-0102）。詳細は conftest。"""

@pytest.mark.django_db
class TestBulkDelete:
    def test_選んだ現場をまとめて消す(self, client, company_a, user_a):
        keep = _site(company_a, "S001", "残す現場")
        gone = [_site(company_a, f"S00{i}", f"消す現場{i}") for i in (2, 3, 4)]
        client.force_login(user_a)

        res = client.post(URL, {
            "key": "sites.site",
            "ids": [str(s.pk) for s in gone],
            "next": reverse("sites:list"),
        }, follow=True)

        assert Site.unscoped.filter(company=company_a).count() == 1
        assert Site.unscoped.get().pk == keep.pk
        assert "現場を 3 件削除しました" in res.content.decode()

    def test_他社の行は消えない(self, client, company_a, company_b, user_a):
        mine = _site(company_a, "S001", "自社の現場")
        other = _site(company_b, "S001", "他社の現場")
        client.force_login(user_a)

        client.post(URL, {
            "key": "sites.site", "ids": [str(mine.pk), str(other.pk)],
        })

        assert not Site.unscoped.filter(pk=mine.pk).exists()
        assert Site.unscoped.filter(pk=other.pk).exists()

    def test_決めていない対象は消せない(self, client, company_a, user_a):
        client.force_login(user_a)

        res = client.post(URL, {"key": "accounts.user", "ids": ["1"]}, follow=True)

        assert "まとめて削除できません" in res.content.decode()

    def test_承認済みの日報は残す(self, client, company_a, user_a):
        site = _site(company_a)
        work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気")
        worker = Worker.unscoped.create(company=company_a, name="電工太郎")
        approved = DailyReport.unscoped.create(
            company=company_a, site=site, work_type=work_type, worker=worker,
            report_date=datetime.date(2026, 9, 10), work_hours=8,
            status=DailyReport.Status.APPROVED,
        )
        draft = DailyReport.unscoped.create(
            company=company_a, site=site, work_type=work_type, worker=worker,
            report_date=datetime.date(2026, 9, 11), work_hours=8,
        )
        client.force_login(user_a)

        res = client.post(URL, {
            "key": "reports.daily", "ids": [str(approved.pk), str(draft.pk)],
        }, follow=True)

        assert DailyReport.unscoped.filter(pk=approved.pk).exists()
        assert not DailyReport.unscoped.filter(pk=draft.pk).exists()
        assert "削除できないため残しました" in res.content.decode()

    def test_ほかから使われている行は残す(self, client, company_a, user_a):
        from apps.materials.models import Quotation

        customer = Customer.unscoped.create(company=company_a, code="C1", name="厚木市")
        # 見積は顧客を PROTECT で参照している。消すと帳票の宛先が消えるため
        Quotation.unscoped.create(
            company=company_a, customer=customer,
            quotation_date=datetime.date(2026, 9, 1),
        )
        client.force_login(user_a)

        res = client.post(URL, {
            "key": "masters.customer", "ids": [str(customer.pk)],
        }, follow=True)

        assert Customer.unscoped.filter(pk=customer.pk).exists()
        assert "ほかから使われているため削除できませんでした" in res.content.decode()

    def test_何も選ばれていなければ知らせる(self, client, company_a, user_a):
        client.force_login(user_a)

        res = client.post(URL, {"key": "sites.site"}, follow=True)

        assert "削除するものが選ばれていません" in res.content.decode()

    def test_ログインしていないと消せない(self, client, company_a):
        site = _site(company_a)

        res = client.post(URL, {"key": "sites.site", "ids": [str(site.pk)]})

        assert res.status_code == 302
        assert Site.unscoped.filter(pk=site.pk).exists()

    def test_GETでは消せない(self, client, user_a):
        client.force_login(user_a)

        assert client.get(URL).status_code == 405

    def test_外のサイトへは戻さない(self, client, company_a, user_a):
        site = _site(company_a)
        client.force_login(user_a)

        res = client.post(URL, {
            "key": "sites.site", "ids": [str(site.pk)], "next": "https://example.com/",
        })

        assert res["Location"] == reverse("sites:list")


@pytest.mark.django_db
class TestScreens:
    """一覧にチェック欄とまとめて削除のボタンが出る。"""

    @pytest.mark.parametrize(("url_name", "key"), [
        ("sites:list", "sites.site"),
        ("workers:list", "workers.worker"),
        ("masters:customer_list", "masters.customer"),
        ("masters:supplier_list", "masters.supplier"),
        ("reports:list", "reports.daily"),
    ])
    def test_画面に出る(self, client, user_a, url_name, key):
        client.force_login(user_a)

        html = client.get(reverse(url_name)).content.decode()

        assert 'class="bulk-check' in html
        assert f'value="{key}"' in html
        assert "bulk-delete-button" in html

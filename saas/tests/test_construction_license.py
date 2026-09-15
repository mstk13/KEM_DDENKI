"""自社の建設業許可の登録と、期限が近づいたときの知らせ（ADR-0064）。"""

import datetime
import importlib

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.bids.license_alerts import (
    check_construction_license_alerts,
    license_alert_recipients,
    reminder_steps,
)
from apps.bids.models import ConstructionLicense
from apps.core.tenant_context import set_current_company
from apps.notifications.models import Notification
from apps.permissions.models import Role, UserRole
from apps.tenants.models import Company
from apps.workers.models import JobTitle, Position, Worker

register = importlib.import_module("apps.bids.migrations.0024_register_company_licenses")

DEADLINE = datetime.date(2030, 3, 21)
VALID_UNTIL = datetime.date(2030, 4, 20)


def _license(company, **extra):
    data = {
        "trade": "電気工事業",
        "license_class": ConstructionLicense.LicenseClass.SPECIAL,
        "authority": "神奈川県知事",
        "license_number": "許可（特-7）第5170号",
        "valid_from": datetime.date(2025, 4, 21),
        "valid_until": VALID_UNTIL,
        "renewal_deadline": DEADLINE,
    }
    data.update(extra)
    return ConstructionLicense.unscoped.create(company=company, **data)


def _office_staff(company, django_user_model, username="jimu"):
    user = django_user_model.objects.create_user(
        username=username, password="testpass123", company=company,
    )
    role, _ = Role.unscoped.get_or_create(
        company=company, code="office_staff", defaults={"name": "事務員"},
    )
    UserRole.unscoped.create(company=company, user=user, role=role)
    return user


def _worker_user(company, django_user_model, username, code, position="正社員"):
    user = django_user_model.objects.create_user(
        username=username, password="testpass123", company=company,
    )
    Worker.unscoped.create(
        company=company, name=username, employee_code=code,
        job_title=JobTitle.unscoped.get_or_create(company=company, name="電工")[0],
        position=Position.unscoped.get_or_create(company=company, name=position)[0],
        user=user,
    )
    return user


def _titles(company):
    return list(
        Notification.unscoped.filter(company=company)
        .order_by("pk").values_list("title", flat=True).distinct()
    )


@pytest.mark.django_db
class TestRegisterMigration:
    def test_ケンモチ電機に2件登録する(self, company_a):
        kem = Company.objects.create(name="ケンモチ電機", industry_type="設備工事")

        assert register.register_licenses(Company, ConstructionLicense) == 2

        rows = {
            r.trade: r for r in ConstructionLicense.unscoped.filter(company=kem)
        }
        assert set(rows) == {"電気工事業", "電気通信工事業"}
        assert rows["電気工事業"].license_class == "special"
        assert rows["電気工事業"].full_number == "神奈川県知事 許可（特-7）第5170号"
        assert rows["電気通信工事業"].license_class == "general"
        assert rows["電気通信工事業"].full_number == "神奈川県知事 許可（般-7）第5170号"
        for row in rows.values():
            assert row.valid_from == datetime.date(2025, 4, 21)
            assert row.valid_until == VALID_UNTIL
            assert row.renewal_deadline == DEADLINE
        assert not ConstructionLicense.unscoped.filter(company=company_a).exists()

    def test_会社が1社だけならその会社に登録する(self, company_a):
        assert register.register_licenses(Company, ConstructionLicense) == 2
        assert ConstructionLicense.unscoped.filter(company=company_a).count() == 2

    def test_複数社でケンモチ電機が無ければ登録しない(self, company_a, company_b):
        assert register.register_licenses(Company, ConstructionLicense) == 0
        assert not ConstructionLicense.unscoped.exists()

    def test_既に登録があれば触らない(self, company_a):
        _license(company_a, trade="管工事業")

        assert register.register_licenses(Company, ConstructionLicense) == 0
        assert ConstructionLicense.unscoped.filter(company=company_a).count() == 1


@pytest.mark.django_db
class TestLicenseViews:
    def test_入札参加資格の画面に自社の建設業許可の欄が出る(self, client, company_a, user_a):
        _license(company_a)
        _license(
            company_a, trade="電気通信工事業",
            license_class=ConstructionLicense.LicenseClass.GENERAL,
            license_number="許可（般-7）第5170号",
        )
        client.force_login(user_a)

        html = client.get(reverse("bids:qualification_list")).content.decode()

        assert 'id="licenses"' in html
        assert "自社の建設業許可" in html
        assert "神奈川県知事 許可（特-7）第5170号" in html
        assert "神奈川県知事 許可（般-7）第5170号" in html
        assert ">特定</span>" in html and ">一般</span>" in html
        assert "2025/4/21〜<wbr>2030/4/20" in html
        assert "提出期限まで残り" in html
        # 建設業許可の欄が、発注機関ごとの入札参加資格より上にある
        assert html.index("自社の建設業許可") < html.index("発注機関ごとの入札参加資格")

    def test_期限切れと更新済の表示(self, client, company_a, user_a):
        today = timezone.localdate()
        _license(
            company_a, trade="管工事業", valid_from=today - datetime.timedelta(days=2000),
            valid_until=today - datetime.timedelta(days=1), renewal_deadline=None,
        )
        _license(company_a, trade="電気通信工事業", renewed=True)
        client.force_login(user_a)

        html = client.get(reverse("bids:qualification_list")).content.decode()

        assert "有効期限が切れています" in html
        assert "更新済</span>" in html

    def test_登録_編集_削除(self, client, company_a, user_a):
        client.force_login(user_a)
        data = {
            "trade": "電気通信工事業", "license_class": "general", "grantor_type": "governor",
            "authority": "神奈川県知事", "license_number": "許可（般-7）第5170号",
            "valid_from": "2025-04-21", "valid_until": "2030-04-20",
            "renewal_deadline": "2030-03-21", "memo": "",
        }

        res = client.post(reverse("bids:license_create"), data)

        assert res.status_code == 302
        assert res["Location"] == reverse("bids:qualification_list") + "#licenses"
        lic = ConstructionLicense.unscoped.get(company=company_a)
        assert (lic.trade, lic.license_class, lic.created_by) == (
            "電気通信工事業", "general", user_a,
        )

        res = client.get(reverse("bids:license_edit", args=[lic.pk]))
        assert 'value="2030-03-21"' in res.content.decode()

        res = client.post(
            reverse("bids:license_edit", args=[lic.pk]), {**data, "renewed": "on"},
        )
        assert res.status_code == 302
        lic.refresh_from_db()
        assert lic.renewed is True

        res = client.post(reverse("bids:license_delete", args=[lic.pk]))
        assert res.status_code == 302
        assert not ConstructionLicense.unscoped.filter(pk=lic.pk).exists()

    def test_期間の前後が逆なら保存しない(self, client, company_a, user_a):
        client.force_login(user_a)
        data = {
            "trade": "電気工事業", "license_class": "special", "grantor_type": "governor",
            "authority": "神奈川県知事", "license_number": "許可（特-7）第5170号",
            "valid_from": "2030-04-20", "valid_until": "2025-04-21",
            "renewal_deadline": "2031-01-01",
        }

        res = client.post(reverse("bids:license_create"), data)

        assert res.status_code == 200
        html = res.content.decode()
        assert "有効期間の終わりが始まりより前になっています" in html
        assert "更新書類の提出期限が有効期間の終わりより後になっています" in html
        assert not ConstructionLicense.unscoped.exists()

    def test_期限を直したら知らせを数え直す(self, company_a):
        lic = _license(company_a, reminder_step=3)

        lic.memo = "メモだけ直す"
        lic.save()
        lic.refresh_from_db()
        assert lic.reminder_step == 3

        lic.renewal_deadline = datetime.date(2030, 3, 25)
        lic.save()
        lic.refresh_from_db()
        assert lic.reminder_step is None


@pytest.mark.django_db
class TestLicenseIsolation:
    def test_isolation(self, company_a, company_b):
        _license(company_a)
        set_current_company(company_a)
        assert ConstructionLicense.objects.count() == 1
        set_current_company(company_b)
        assert ConstructionLicense.objects.count() == 0
        set_current_company(None)

    def test_other_tenant_cannot_edit_or_delete(self, client, company_a, user_b):
        lic = _license(company_a)
        client.force_login(user_b)

        assert client.get(reverse("bids:license_edit", args=[lic.pk])).status_code == 404
        assert client.post(reverse("bids:license_delete", args=[lic.pk])).status_code == 404
        assert ConstructionLicense.unscoped.filter(pk=lic.pk).exists()


@pytest.mark.django_db
class TestLicenseAlerts:
    @pytest.fixture
    def staff(self, company_a, django_user_model):
        return _office_staff(company_a, django_user_model)

    def test_知らせる段階の並び(self, company_a):
        steps = reminder_steps(_license(company_a))

        assert [kind for _, kind in steps] == [
            "before", "before", "before", "before", "before", "before",
            "due", "overdue", "last_day", "expired",
        ]
        assert steps[0][0] == DEADLINE - datetime.timedelta(days=180)
        assert steps[6][0] == DEADLINE
        assert steps[7][0] == datetime.date(2030, 3, 22)
        assert steps[8][0] == VALID_UNTIL
        assert steps[9][0] == datetime.date(2030, 4, 21)

    def test_受け取るのは社長_管理者_事務員_Developerだけ(
        self, company_a, company_b, user_a, staff, django_user_model,
    ):
        admin_y = _worker_user(company_a, django_user_model, "kanri", "Y001")
        developer = _worker_user(
            company_a, django_user_model, "it", "G001", position="Developer",
        )
        president = _worker_user(company_a, django_user_model, "shacho", "G002", position="社長")
        _worker_user(company_a, django_user_model, "denko", "E001")
        _office_staff(company_b, django_user_model, username="other_jimu")

        recipients = set(license_alert_recipients(company_a))

        assert recipients == {staff, admin_y, developer, president}
        assert user_a not in recipients

    def test_180日より前は知らせない(self, company_a, staff):
        _license(company_a)

        created = check_construction_license_alerts(
            company_a, today=DEADLINE - datetime.timedelta(days=181),
        )

        assert created == 0

    def test_30日前に1回だけ知らせる(self, company_a, staff):
        lic = _license(company_a)
        today = DEADLINE - datetime.timedelta(days=30)

        assert check_construction_license_alerts(company_a, today=today) == 1
        assert check_construction_license_alerts(company_a, today=today) == 0

        n = Notification.unscoped.get(company=company_a)
        assert n.recipient == staff
        assert n.title == "建設業許可（電気工事業・特定）の更新書類の提出期限まで残り30日"
        assert n.level == Notification.Level.WARNING
        assert n.module == Notification.Module.BIDS
        assert n.reference_url == reverse("bids:qualification_list") + "#licenses"
        assert "神奈川県知事 許可（特-7）第5170号" in n.body
        assert "更新書類の提出期限 2030-03-21" in n.body
        lic.refresh_from_db()
        assert lic.reminder_step == 3

    def test_止まっていた日があっても今の段階の1通だけ(self, company_a, staff):
        _license(company_a)

        created = check_construction_license_alerts(
            company_a, today=DEADLINE - datetime.timedelta(days=10),
        )

        assert created == 1
        assert _titles(company_a) == [
            "建設業許可（電気工事業・特定）の更新書類の提出期限まで残り10日",
        ]

    def test_提出期限の当日_過ぎた日_最後の日_切れた日(self, company_a, staff):
        _license(company_a)
        for day in (
            DEADLINE, DEADLINE + datetime.timedelta(days=1),
            VALID_UNTIL, VALID_UNTIL + datetime.timedelta(days=1),
        ):
            check_construction_license_alerts(company_a, today=day)

        assert _titles(company_a) == [
            "建設業許可（電気工事業・特定）の更新書類の提出期限は今日です",
            "🔴 建設業許可（電気工事業・特定）の更新書類の提出期限を過ぎています"
            "（有効期限まで残り29日）",
            "🔴 建設業許可（電気工事業・特定）の有効期限は今日までです",
            "🔴 建設業許可（電気工事業・特定）の有効期限が切れています",
        ]

    def test_提出期限が無ければ有効期限で数える(self, company_a, staff):
        _license(company_a, renewal_deadline=None)

        check_construction_license_alerts(
            company_a, today=VALID_UNTIL - datetime.timedelta(days=60),
        )

        assert _titles(company_a) == ["建設業許可（電気工事業・特定）の有効期限まで残り60日"]

    def test_更新済には知らせない(self, company_a, staff):
        _license(company_a, renewed=True)

        assert check_construction_license_alerts(company_a, today=DEADLINE) == 0

    def test_期限を直したら新しい期限で知らせる(self, company_a, staff):
        lic = _license(company_a)
        today = DEADLINE - datetime.timedelta(days=7)
        check_construction_license_alerts(company_a, today=today)

        lic.renewal_deadline = DEADLINE + datetime.timedelta(days=20)
        lic.save()
        check_construction_license_alerts(company_a, today=today)

        assert _titles(company_a)[-1] == (
            "建設業許可（電気工事業・特定）の更新書類の提出期限まで残り27日"
        )

    def test_受け取る人がいなければ段階を進めない(self, company_a, user_a):
        lic = _license(company_a)

        assert check_construction_license_alerts(company_a, today=DEADLINE) == 0

        lic.refresh_from_db()
        assert lic.reminder_step is None

    def test_他社の許可と人には出さない(self, company_a, company_b, staff, django_user_model):
        _license(company_b)
        _office_staff(company_b, django_user_model, username="other_jimu")

        assert check_construction_license_alerts(company_a, today=DEADLINE) == 0
        assert not Notification.unscoped.filter(company=company_a).exists()

    def test_毎朝の書類通知コマンドから知らせる(self, company_a, staff):
        today = timezone.localdate()
        _license(
            company_a, valid_from=today - datetime.timedelta(days=1700),
            valid_until=today + datetime.timedelta(days=60),
            renewal_deadline=today + datetime.timedelta(days=30),
        )

        call_command("send_document_alerts", "--company", company_a.name)

        assert _titles(company_a) == [
            "建設業許可（電気工事業・特定）の更新書類の提出期限まで残り30日",
        ]

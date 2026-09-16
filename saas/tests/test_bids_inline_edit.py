"""入札管理の画面で、文字をタップしてその場で直す（ADR-0073）。

- 直せるのは決めた項目だけ。ほかの項目や他社のデータは直せない
- 文字・数値・日付・日時・選択・はい/いいえ を保存でき、画面に出す文字を返す
- 入力チェックはモデルフォームに任せる（空にできない項目は空にできない）
"""

import datetime
import json
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bids.models import (
    BidProject,
    ConstructionLicense,
    Qualification,
    ScrapeTarget,
    UnifiedQualification,
    UnitPrice,
)

URL = "/bids/inline-edit/"


def _post(client, obj, field, value):
    return client.post(
        URL,
        data=json.dumps({
            "model": f"{obj._meta.app_label}.{obj._meta.object_name}",
            "pk": obj.pk, "field": field, "value": value,
        }),
        content_type="application/json",
    )


@pytest.fixture
def project(company_a, user_a):
    return BidProject.unscoped.create(
        company=company_a, created_by=user_a, title="A現場 電気工事",
        client="国土交通省", category="電気設備工事", budget=0,
    )


@pytest.mark.django_db
class TestSave:
    def test_文字を直せる(self, client, user_a, project):
        client.force_login(user_a)

        res = _post(client, project, "client", "防衛省")

        assert res.status_code == 200
        assert res.json() == {"ok": True, "display": "防衛省", "value": "防衛省"}
        project.refresh_from_db()
        assert project.client == "防衛省"

    def test_選択と数値と日付と日時を直せる(self, client, user_a, project):
        client.force_login(user_a)

        assert _post(client, project, "status", "won").json()["display"] == "落札"
        assert _post(client, project, "budget", "1234567").json()["display"] == "1,234,567"
        announced = _post(client, project, "announced_on", "2026-09-16").json()
        assert announced["display"] == "2026/09/16"
        deadline = _post(client, project, "deadline", "2026-09-30T15:00").json()
        assert deadline["display"] == "2026/09/30 15:00"

        project.refresh_from_db()
        assert project.status == BidProject.Status.WON
        assert project.budget == Decimal("1234567")
        assert project.announced_on == datetime.date(2026, 9, 16)
        local_deadline = timezone.localtime(project.deadline)
        assert local_deadline.strftime("%Y-%m-%d %H:%M") == "2026-09-30 15:00"

    def test_はいいいえを直せる(self, client, company_a, user_a):
        target = ScrapeTarget.unscoped.create(
            company=company_a, created_by=user_a, name="i-ppi", is_active=True,
        )
        client.force_login(user_a)

        res = _post(client, target, "is_active", "false")

        assert res.json()["display"] == "いいえ"
        target.refresh_from_db()
        assert target.is_active is False

    def test_空にできる項目と_できない項目(self, client, user_a, project):
        client.force_login(user_a)

        assert _post(client, project, "client", "").json()["display"] == "-"

        res = _post(client, project, "title", "")

        assert res.status_code == 400
        assert "必須" in res.json()["error"] or "入力" in res.json()["error"]
        project.refresh_from_db()
        assert project.title == "A現場 電気工事"

    def test_数値に文字を入れたら断る(self, client, user_a, project):
        client.force_login(user_a)

        res = _post(client, project, "budget", "たくさん")

        assert res.status_code == 400
        assert res.json()["ok"] is False
        project.refresh_from_db()
        assert project.budget == Decimal("0")

    def test_資格_許可_単価も直せる(self, client, company_a, user_a):
        qualification = Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気工事", grade="A",
        )
        license_ = ConstructionLicense.unscoped.create(
            company=company_a, trade="電気工事業", license_class="special",
            authority="神奈川県知事", license_number="許可（特-7）第5170号",
            valid_from=datetime.date(2025, 4, 21), valid_until=datetime.date(2030, 4, 20),
        )
        unified = UnifiedQualification.unscoped.create(
            company=company_a, agency="衆議院", goods_sales_grade="C", goods_sales_score=62,
        )
        price = UnitPrice.unscoped.create(
            company=company_a, category="電線", item_name="IV1.6", unit="m", unit_price=100,
        )
        client.force_login(user_a)

        assert _post(client, qualification, "grade", "B").json()["display"] == "B"
        assert _post(client, license_, "license_class", "general").json()["display"] == "一般"
        assert _post(client, unified, "goods_sales_score", "70").json()["display"] == "70"
        assert _post(client, price, "unit_price", "150").json()["display"] == "150"

        qualification.refresh_from_db()
        license_.refresh_from_db()
        unified.refresh_from_db()
        price.refresh_from_db()
        assert qualification.grade == "B"
        assert license_.license_class == "general"
        assert unified.goods_sales_score == 70
        assert price.unit_price == Decimal("150")


@pytest.mark.django_db
class TestGuards:
    def test_決めていない項目は直せない(self, client, user_a, project):
        client.force_login(user_a)

        res = _post(client, project, "company", "1")

        assert res.status_code == 400
        assert "直せません" in res.json()["error"]

    def test_決めていないモデルは直せない(self, client, user_a, project):
        client.force_login(user_a)

        res = client.post(
            URL,
            data=json.dumps({
                "model": "workers.Worker", "pk": 1, "field": "name", "value": "x",
            }),
            content_type="application/json",
        )

        assert res.status_code == 400

    def test_他社のデータは直せない(self, client, user_b, project):
        client.force_login(user_b)

        res = _post(client, project, "client", "のっとり")

        assert res.status_code == 404
        project.refresh_from_db()
        assert project.client == "国土交通省"

    def test_ログインしていないと直せない(self, client, project):
        res = _post(client, project, "client", "のっとり")

        assert res.status_code == 302
        project.refresh_from_db()
        assert project.client == "国土交通省"

    def test_GETでは受け付けない(self, client, user_a):
        client.force_login(user_a)

        assert client.get(URL).status_code == 405


@pytest.mark.django_db
class TestScreens:
    def test_各画面にタップで直せる文字が出る(self, client, company_a, user_a, project):
        Qualification.unscoped.create(company=company_a, issuer="防衛省", category="電気工事")
        ConstructionLicense.unscoped.create(
            company=company_a, trade="電気工事業", license_class="special",
            authority="神奈川県知事", license_number="許可（特-7）第5170号",
            valid_from=datetime.date(2025, 4, 21), valid_until=datetime.date(2030, 4, 20),
        )
        UnitPrice.unscoped.create(
            company=company_a, category="電線", item_name="IV1.6", unit="m", unit_price=100,
        )
        ScrapeTarget.unscoped.create(company=company_a, name="i-ppi", region="神奈川県")
        client.force_login(user_a)

        for url, field in (
            (reverse("bids:project_list"), "client"),
            (reverse("bids:project_detail", args=[project.pk]), "title"),
            (reverse("bids:qualification_list"), "trade"),
            (reverse("bids:unit_price_list"), "item_name"),
            (reverse("bids:scrape_target_list"), "region"),
        ):
            html = client.get(url).content.decode()
            assert 'class="inline-edit"' in html, url
            assert f'data-field="{field}"' in html, url
            # 静的ファイルは名前にハッシュが付くので、頭の部分で確かめる
            assert "js/inline-edit" in html, url

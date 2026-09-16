"""入札案件詳細の残りの欄も、タップして直せる（ADR-0074）。

- 原価情報・競合情報はその場で直せる。無ければ枠を作れる
- 工事概要・参加要件・案件概要は「この欄を直す」から直す（保存後に画面を読み直す）
- 参加資格判定は、もとになる自社資格と公告側の要件を直せる
- 重要日程の日付は、バーを動かしたときと同じ受け口に入る
"""

import datetime
import json

import pytest
from django.urls import reverse

from apps.bids.models import BidCompetitor, BidCost, BidProject, Qualification

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
        company=company_a, created_by=user_a, title="B現場 電気工事",
        client="防衛省", category="電気設備工事", budget=0,
        announced_on=datetime.date(2026, 9, 1),
    )


@pytest.mark.django_db
class TestCostAndCompetitor:
    def test_原価情報の枠を作って直せる(self, client, user_a, project):
        client.force_login(user_a)

        res = client.post(reverse("bids:cost_start", args=[project.pk]))

        assert res.status_code == 302
        cost = BidCost.unscoped.get(project=project)
        assert _post(client, cost, "estimate_amount", "1500000").json()["display"] == "1,500,000"
        assert _post(client, cost, "memo", "下請け込み").json()["display"] == "下請け込み"
        cost.refresh_from_db()
        assert cost.memo == "下請け込み"

    def test_枠は二重に作らない(self, client, user_a, project):
        client.force_login(user_a)

        client.post(reverse("bids:cost_start", args=[project.pk]))
        client.post(reverse("bids:cost_start", args=[project.pk]))

        assert BidCost.unscoped.filter(project=project).count() == 1

    def test_競合を足して直して消せる(self, client, user_a, project):
        client.force_login(user_a)

        client.post(reverse("bids:competitor_add", args=[project.pk]))
        competitor = BidCompetitor.unscoped.get(project=project)

        assert _post(client, competitor, "competitor_name", "○○電設").json()["ok"] is True
        assert _post(client, competitor, "competitor_amount", "980000").json()["display"] == (
            "980,000"
        )
        competitor.refresh_from_db()
        assert competitor.competitor_name == "○○電設"

        res = client.post(reverse("bids:competitor_delete", args=[competitor.pk]))

        assert res.status_code == 302
        assert not BidCompetitor.unscoped.filter(pk=competitor.pk).exists()

    def test_他社の競合は消せない(self, client, user_b, project, company_a, user_a):
        competitor = BidCompetitor.unscoped.create(
            company=company_a, created_by=user_a, project=project, competitor_name="○○電設",
        )
        client.force_login(user_b)

        res = client.post(reverse("bids:competitor_delete", args=[competitor.pk]))

        assert res.status_code == 404
        assert BidCompetitor.unscoped.filter(pk=competitor.pk).exists()


@pytest.mark.django_db
class TestLongText:
    def test_工事概要と参加要件と案件概要を直せる(self, client, user_a, project):
        client.force_login(user_a)

        assert _post(client, project, "work_outline", "配電盤更新一式").json()["ok"] is True
        assert _post(client, project, "requirements", "電気工事業の許可").json()["ok"] is True
        assert _post(client, project, "summary", "公告の原文").json()["ok"] is True
        assert _post(client, project, "notes", "担当者に確認").json()["ok"] is True

        project.refresh_from_db()
        assert project.work_outline == "配電盤更新一式"
        assert project.requirements == "電気工事業の許可"
        assert project.summary == "公告の原文"
        assert project.notes == "担当者に確認"


@pytest.mark.django_db
class TestDetailScreen:
    def test_各欄にタップで直せる文字が出る(self, client, company_a, user_a, project):
        Qualification.unscoped.create(
            company=company_a, issuer="防衛省", category="電気",
            grade="B", keisin_score=900,
        )
        BidCost.unscoped.create(company=company_a, created_by=user_a, project=project)
        BidCompetitor.unscoped.create(
            company=company_a, created_by=user_a, project=project, competitor_name="○○電設",
        )
        client.force_login(user_a)

        html = client.get(reverse("bids:project_detail", args=[project.pk])).content.decode()

        # 原価情報・競合情報
        assert 'data-model="bids.BidCost"' in html
        assert 'data-model="bids.BidCompetitor"' in html
        # 長い文は「この欄を直す」から
        for field in ("work_outline", "requirements", "summary", "notes"):
            assert f'data-field="{field}"' in html
        assert "この欄を直す" in html
        # 参加資格判定は、もとになる自社資格を直せる
        assert 'data-model="bids.Qualification"' in html
        assert 'data-field="keisin_score"' in html
        # 直したら画面を読み直す欄がある
        assert 'data-reload="1"' in html

    def test_案件概要の欄は空でも出る(self, client, user_a, project):
        client.force_login(user_a)

        html = client.get(reverse("bids:project_detail", args=[project.pk])).content.decode()

        assert "案件概要（情報源の原文）" in html
        assert "原文を直す" in html


@pytest.mark.django_db
class TestScheduleDates:
    def test_表の日付はバーと同じ受け口に入る(self, client, user_a, project):
        project.bid_schedule = [
            {"label": "入札書の提出期限", "end": "2026-09-25 17:00", "detail": ""},
        ]
        project.save()
        client.force_login(user_a)

        res = client.post(
            reverse("bids:schedule_override", args=[project.pk]),
            {"label": "入札書の提出期限", "end": "2026-09-28"},
        )

        assert res.status_code == 200
        project.refresh_from_db()
        assert project.schedule_overrides["入札書の提出期限"]["end"] == "2026-09-28"

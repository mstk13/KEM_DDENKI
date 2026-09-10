"""入札案件 → 現場の参照（ADR-0031）。

積算開始と落札で同じ入札から現場が2つできていた不具合を固定する。
あわせて、既存データを現場コードから紐付けるマイグレーションの規則を確かめる。
"""
import importlib
from decimal import Decimal

import pytest

from apps.bids.models import BidProject
from apps.bids.services import mark_as_won, start_estimation
from apps.masters.models import Customer
from apps.notifications.models import Notification
from apps.sites.models import Site

backfill = importlib.import_module("apps.bids.migrations.0022_backfill_bidproject_site")


def _bid(company, **kwargs):
    fields = {"title": "Ｒ８下京税務署電気設備工事"}
    fields.update(kwargs)
    return BidProject.unscoped.create(company=company, **fields)


def _site(company, code, **kwargs):
    fields = {"name": "既存の現場", "status": Site.Status.ESTIMATING}
    fields.update(kwargs)
    return Site.unscoped.create(company=company, code=code, **fields)


def _won_notices(company):
    return Notification.unscoped.filter(company=company, module=Notification.Module.BIDS)


@pytest.mark.django_db
class TestStartEstimationAndWon:
    def test_estimation_then_won_uses_one_site(self, company_a, user_a):
        bid = _bid(company_a, budget=Decimal("0"), our_bid_amount=Decimal("12500000"))

        site, created = start_estimation(bid, created_by=user_a)
        assert created is True
        assert site.code == f"EST-{bid.pk}"

        bid.client_ref = Customer.unscoped.create(
            company=company_a, code="C1", name="近畿地方整備局",
        )
        bid.save(update_fields=["client_ref"])
        won_site, created = mark_as_won(bid, created_by=user_a)

        assert created is False
        assert won_site.pk == site.pk
        assert Site.unscoped.filter(company=company_a).count() == 1
        site.refresh_from_db()
        bid.refresh_from_db()
        assert bid.site_id == site.pk
        assert bid.status == BidProject.Status.WON
        assert site.status == Site.Status.ORDERED
        assert site.contract_amount == Decimal("12500000")
        assert site.customer == bid.client_ref
        assert site.code == f"EST-{bid.pk}"  # コードは作ったときのまま
        assert "登録済みの現場" in _won_notices(company_a).get(recipient=user_a).body

    def test_won_keeps_values_already_on_site(self, company_a):
        customer = Customer.unscoped.create(company=company_a, code="C1", name="画面で選んだ顧客")
        other = Customer.unscoped.create(company=company_a, code="C2", name="入札の発注者")
        site = _site(company_a, "S-001", contract_amount=Decimal("9800000"), customer=customer)
        bid = _bid(company_a, site=site, our_bid_amount=Decimal("12500000"), client_ref=other)

        mark_as_won(bid)

        site.refresh_from_db()
        assert site.status == Site.Status.ORDERED
        assert site.contract_amount == Decimal("9800000")
        assert site.customer == customer
        assert site.code == "S-001"

    def test_won_alone_creates_and_links_site(self, company_a, user_a):
        bid = _bid(company_a, budget=Decimal("10000000"), our_bid_amount=Decimal("9500000"))

        site, created = mark_as_won(bid, created_by=user_a)

        assert created is True
        bid.refresh_from_db()
        assert bid.site_id == site.pk
        assert site.code == f"BID-{bid.pk}"
        assert site.status == Site.Status.ORDERED
        assert site.contract_amount == Decimal("9500000")
        assert "自動作成されました" in _won_notices(company_a).get(recipient=user_a).body
        # 参照の保存も履歴に残る
        assert bid.history.first().site_id == site.pk

    def test_start_estimation_twice_keeps_one_site(self, company_a):
        bid = _bid(company_a)

        first, _ = start_estimation(bid)
        second, created = start_estimation(bid)

        assert created is False
        assert second.pk == first.pk
        assert Site.unscoped.filter(company=company_a).count() == 1

    def test_won_twice_keeps_one_site_and_one_notice(self, company_a, user_a):
        bid = _bid(company_a)

        first, _ = mark_as_won(bid)
        second, created = mark_as_won(bid)

        assert created is False
        assert second.pk == first.pk
        assert Site.unscoped.filter(company=company_a).count() == 1
        assert _won_notices(company_a).filter(recipient=user_a).count() == 1

    def test_won_does_not_move_site_backwards(self, company_a):
        site = _site(company_a, "S-002", status=Site.Status.IN_PROGRESS)
        bid = _bid(company_a, site=site)

        mark_as_won(bid)

        site.refresh_from_db()
        assert site.status == Site.Status.IN_PROGRESS

    def test_views_do_not_create_second_site(self, client, company_a, user_a):
        bid = _bid(company_a)
        client.force_login(user_a)

        assert client.post(f"/bids/{bid.pk}/start-estimation/").status_code == 302
        assert client.post(f"/bids/{bid.pk}/mark-won/").status_code == 302
        assert client.post(f"/bids/{bid.pk}/mark-won/").status_code == 302

        bid.refresh_from_db()
        assert Site.unscoped.filter(company=company_a).count() == 1
        assert bid.site.status == Site.Status.ORDERED

    def test_other_company_site_is_never_used(self, company_a, company_b):
        bid_b = _bid(company_b)
        est_a = _site(company_a, f"EST-{bid_b.pk}")
        bid_a_site = _site(company_a, f"BID-{bid_b.pk}")

        site, _ = start_estimation(bid_b)
        won, _ = mark_as_won(bid_b)

        assert won.pk == site.pk
        assert site.company == company_b
        assert Site.unscoped.filter(company=company_b).count() == 1
        est_a.refresh_from_db()
        bid_a_site.refresh_from_db()
        assert est_a.status == Site.Status.ESTIMATING
        assert bid_a_site.status == Site.Status.ESTIMATING


@pytest.mark.django_db
class TestBackfillBidSites:
    def _run(self):
        return backfill.link_bid_sites(BidProject, Site)

    def test_links_est_site_when_only_est_exists(self, company_a):
        bid = _bid(company_a)
        est = _site(company_a, f"EST-{bid.pk}")

        assert self._run() == 1
        bid.refresh_from_db()
        assert bid.site_id == est.pk

    def test_links_bid_site_when_only_bid_exists(self, company_a):
        bid = _bid(company_a)
        won = _site(company_a, f"BID-{bid.pk}", status=Site.Status.ORDERED)

        assert self._run() == 1
        bid.refresh_from_db()
        assert bid.site_id == won.pk

    def test_prefers_bid_site_and_leaves_est_site_alone(self, company_a):
        bid = _bid(company_a)
        est = _site(
            company_a, f"EST-{bid.pk}", name="見積中の現場", contract_amount=Decimal("100"),
        )
        won = _site(company_a, f"BID-{bid.pk}", status=Site.Status.ORDERED)

        assert self._run() == 1
        bid.refresh_from_db()
        assert bid.site_id == won.pk
        est.refresh_from_db()
        assert est.name == "見積中の現場"
        assert est.status == Site.Status.ESTIMATING
        assert est.contract_amount == Decimal("100")

    def test_leaves_bid_without_matching_site(self, company_a):
        bid = _bid(company_a)
        _site(company_a, "S-003")
        _site(company_a, f"EST-0{bid.pk}")  # 先頭ゼロは自動作成のコードではない

        assert self._run() == 0
        bid.refresh_from_db()
        assert bid.site_id is None

    def test_does_not_link_other_company_site(self, company_a, company_b):
        bid_b = _bid(company_b)
        _site(company_a, f"BID-{bid_b.pk}")

        assert self._run() == 0
        bid_b.refresh_from_db()
        assert bid_b.site_id is None

    def test_keeps_site_already_linked(self, company_a):
        chosen = _site(company_a, "S-004")
        bid = _bid(company_a, site=chosen)
        _site(company_a, f"BID-{bid.pk}")

        assert self._run() == 0
        bid.refresh_from_db()
        assert bid.site_id == chosen.pk

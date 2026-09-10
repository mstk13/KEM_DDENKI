"""notifications の定期チェックが、実在する状態値で対象を拾うこと。

以前は Site を status="active"、BidProject を "NEW" 等の大文字で絞っていたため、
どの現場・入札案件にも一致せず、アラートが1件も出なかった。
ここでは発火履歴（AlertLog）に対象の ID が残るかで確かめる。
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bids.models import BidProject
from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import CostCategory, WorkType
from apps.notifications.models import AlertLog, AlertRule
from apps.notifications.services import (
    check_bid_deadline_alerts,
    check_cost_alerts,
    check_schedule_delay_alerts,
)
from apps.sites.models import Site


def _rule(company, alert_type, threshold):
    return AlertRule.unscoped.create(
        company=company, name="テスト", alert_type=alert_type, threshold_value=threshold,
    )


def _alerted_ids(rule):
    return set(AlertLog.unscoped.filter(alert_rule=rule).values_list("reference_id", flat=True))


def _sites_by_status(company, **fields):
    return {
        status: Site.unscoped.create(
            company=company, code=f"S-{status}", name=f"現場-{status}", status=status, **fields,
        )
        for status in Site.Status.values
    }


@pytest.mark.django_db
class TestCostAlerts:
    def test_受注済と施工中の現場だけを対象にする(self, company_a):
        category, _ = CostCategory.objects.get_or_create(
            code="material", defaults={"name": "材料費", "display_order": 1},
        )
        work_type = WorkType.unscoped.create(company=company_a, code="E01", name="電気幹線")
        rule = _rule(company_a, AlertRule.AlertType.COST_THRESHOLD, 90)
        sites = _sites_by_status(company_a)
        for site in sites.values():
            common = {"company": company_a, "site": site, "work_type": work_type,
                      "cost_category": category}
            BudgetItem.unscoped.create(**common, name="材料費", amount=Decimal("1000000"))
            CostTransaction.unscoped.create(
                **common, amount=Decimal("950000"), transaction_date=date.today(),
                source_type=CostTransaction.SourceType.PO_ITEM,
            )

        check_cost_alerts(company_a)

        assert _alerted_ids(rule) == {
            sites[Site.Status.ORDERED].pk,
            sites[Site.Status.IN_PROGRESS].pk,
        }


@pytest.mark.django_db
class TestScheduleDelayAlerts:
    def test_受注済と施工中で終了日が近い現場だけを対象にする(self, company_a):
        rule = _rule(company_a, AlertRule.AlertType.SCHEDULE_DELAY, 14)
        sites = _sites_by_status(company_a, end_date=date.today() + timedelta(days=7))

        check_schedule_delay_alerts(company_a)

        assert _alerted_ids(rule) == {
            sites[Site.Status.ORDERED].pk,
            sites[Site.Status.IN_PROGRESS].pk,
        }


@pytest.mark.django_db
class TestBidDeadlineAlerts:
    def test_新着_検討中_入札済で期限が近い案件だけを対象にする(self, company_a, user_a):
        rule = _rule(company_a, AlertRule.AlertType.BID_DEADLINE, 7)
        deadline = timezone.now() + timedelta(days=3)
        bids = {
            status: BidProject.unscoped.create(
                company=company_a, created_by=user_a, title=f"案件-{status}",
                status=status, deadline=deadline,
            )
            for status in BidProject.Status.values
        }

        check_bid_deadline_alerts(company_a)

        assert _alerted_ids(rule) == {
            bids[BidProject.Status.NEW].pk,
            bids[BidProject.Status.CONSIDERING].pk,
            bids[BidProject.Status.BID].pk,
        }

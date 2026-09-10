"""workers.EvaluatorAssignment — 評価者割当の越境・一意性・履歴（ADR-0028）。

evaluation.EvaluatorTarget を作業員 FK で持ち直す expand の段階。
評価画面の対象者の絞り込みにはまだ使っていないので、ここではモデルとしての
約束だけを固定する。
"""

import pytest
from django.db import IntegrityError, transaction

from apps.core.tenant_context import set_current_company
from apps.workers.models import EvaluatorAssignment, Worker


def _workers(company, *names):
    return [
        Worker.unscoped.create(company=company, name=name, hourly_cost=3000)
        for name in names
    ]


@pytest.mark.django_db
class TestEvaluatorAssignment:
    def test_他社の割当は見えない(self, company_a, company_b):
        evaluator_a, target_a = _workers(company_a, "評価者A", "対象A")
        evaluator_b, target_b = _workers(company_b, "評価者B", "対象B")
        EvaluatorAssignment.unscoped.create(
            company=company_a, evaluator=evaluator_a, target=target_a,
        )
        EvaluatorAssignment.unscoped.create(
            company=company_b, evaluator=evaluator_b, target=target_b,
        )

        set_current_company(company_a)
        try:
            names = list(EvaluatorAssignment.objects.values_list("target__name", flat=True))
        finally:
            set_current_company(None)

        assert names == ["対象A"]

    def test_同じ組は二重に登録できない(self, company_a):
        evaluator, target = _workers(company_a, "評価者", "対象")
        EvaluatorAssignment.unscoped.create(
            company=company_a, evaluator=evaluator, target=target,
        )

        with pytest.raises(IntegrityError), transaction.atomic():
            EvaluatorAssignment.unscoped.create(
                company=company_a, evaluator=evaluator, target=target,
            )

    def test_役員の自己評価のため同じ作業員の組も登録できる(self, company_a):
        (executive,) = _workers(company_a, "役員")

        assignment = EvaluatorAssignment.unscoped.create(
            company=company_a, evaluator=executive, target=executive,
        )

        assert assignment.pk is not None

    def test_変更履歴が残る(self, company_a):
        evaluator, target = _workers(company_a, "評価者", "対象")

        assignment = EvaluatorAssignment.unscoped.create(
            company=company_a, evaluator=evaluator, target=target,
        )

        assert assignment.history.count() == 1

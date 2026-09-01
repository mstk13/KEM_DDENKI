"""既存の名寄せを再マッチしたときの上書き条件のテスト。

match_item は当初 get_or_create だったため、一度作られた名寄せは
再マッチしても更新されなかった。マッチング手段が増えても
過去の「手動・信頼度0」がそのまま残り続ける問題があった。

ただし無条件の上書きは2つの事故を招く。
- 人間のレビュー結果が消える
- Ollama 障害中の再マッチで既存の紐付けが失われる
その両方を防げていることを検証する。
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.estimation.models import EstimationItem, ItemAlias
from apps.estimation.services import matching
from apps.estimation.services.matching import _should_update


def _item(company, code="A-001", name="VVFケーブル 1.6mm 2芯"):
    return EstimationItem.unscoped.create(
        company=company, code=code, canonical_name=name, unit="m",
    )


def _alias(company, item=None, *, status=ItemAlias.Status.PENDING,
           confidence="0", matched_by=ItemAlias.MatchMethod.MANUAL,
           raw_name="VVF 1.6-2C"):
    return ItemAlias.unscoped.create(
        company=company,
        source_type=ItemAlias.SourceType.ORDERER_BOQ,
        source_key="",
        raw_name=raw_name,
        estimation_item=item,
        confidence=Decimal(confidence),
        matched_by=matched_by,
        status=status,
    )


@pytest.mark.django_db
class TestShouldUpdate:
    """上書き判定そのもの。"""

    def test_updates_unmatched_pending_alias(self, company_a):
        item = _item(company_a)
        alias = _alias(company_a)
        assert _should_update(alias, item, Decimal("70"), force=False) is True

    def test_updates_when_confidence_improves(self, company_a):
        item = _item(company_a)
        alias = _alias(company_a, item, confidence="70")
        assert _should_update(alias, item, Decimal("85"), force=False) is True

    def test_does_not_downgrade_confidence(self, company_a):
        item = _item(company_a)
        alias = _alias(company_a, item, confidence="85")
        assert _should_update(alias, item, Decimal("70"), force=False) is False

    def test_does_not_clear_link_when_match_fails(self, company_a):
        """Ollama 障害等で今回マッチしなくても既存の紐付けを消さない。"""
        item = _item(company_a)
        alias = _alias(company_a, item, confidence="85")
        assert _should_update(alias, None, Decimal("0"), force=False) is False

    @pytest.mark.parametrize("status", [
        ItemAlias.Status.REVIEWED,
        ItemAlias.Status.APPROVED,
        ItemAlias.Status.REJECTED,
    ])
    def test_never_touches_human_decisions(self, company_a, status):
        item = _item(company_a)
        alias = _alias(company_a, status=status)
        assert _should_update(alias, item, Decimal("100"), force=False) is False

    @pytest.mark.parametrize("status", [
        ItemAlias.Status.REVIEWED,
        ItemAlias.Status.APPROVED,
        ItemAlias.Status.REJECTED,
    ])
    def test_force_overrides_everything(self, company_a, status):
        item = _item(company_a)
        alias = _alias(company_a, status=status)
        assert _should_update(alias, item, Decimal("0"), force=True) is True


@pytest.mark.django_db
class TestMatchItemUpdatesExisting:
    """match_item を通した挙動。"""

    def test_existing_pending_alias_is_upgraded(self, company_a):
        """手段が増えて紐付いたら、既存の未確認レコードが更新される。"""
        item = _item(company_a, code="A-001", name="VVFケーブル 1.6mm 2芯")
        _alias(company_a, None, raw_name="VVFケーブル 1.6mm 2芯")

        alias = matching.match_item(
            raw_name="VVFケーブル 1.6mm 2芯",
            source_type=ItemAlias.SourceType.ORDERER_BOQ,
            source_key="",
            company=company_a,
        )

        alias.refresh_from_db()
        assert alias.estimation_item == item
        assert alias.matched_by == ItemAlias.MatchMethod.NORMALIZED
        assert alias.confidence == Decimal("90")
        # 1レコードのままであること（重複を作らない）
        assert ItemAlias.unscoped.filter(company=company_a).count() == 1

    def test_reviewed_alias_is_left_alone(self, company_a):
        """レビュー済みは再マッチしても変わらない。"""
        _item(company_a, code="A-001", name="VVFケーブル 1.6mm 2芯")
        original = _alias(
            company_a, None, raw_name="VVFケーブル 1.6mm 2芯",
            status=ItemAlias.Status.APPROVED,
            matched_by=ItemAlias.MatchMethod.MANUAL,
        )

        matching.match_item(
            raw_name="VVFケーブル 1.6mm 2芯",
            source_type=ItemAlias.SourceType.ORDERER_BOQ,
            source_key="",
            company=company_a,
        )

        original.refresh_from_db()
        assert original.estimation_item_id is None
        assert original.status == ItemAlias.Status.APPROVED
        assert original.matched_by == ItemAlias.MatchMethod.MANUAL

    def test_force_overwrites_reviewed_alias(self, company_a):
        item = _item(company_a, code="A-001", name="VVFケーブル 1.6mm 2芯")
        original = _alias(
            company_a, None, raw_name="VVFケーブル 1.6mm 2芯",
            status=ItemAlias.Status.APPROVED,
        )

        matching.match_item(
            raw_name="VVFケーブル 1.6mm 2芯",
            source_type=ItemAlias.SourceType.ORDERER_BOQ,
            source_key="",
            company=company_a,
            force=True,
        )

        original.refresh_from_db()
        assert original.estimation_item == item

    def test_update_existing_false_keeps_old_behaviour(self, company_a):
        """従来どおり既存レコードに触れない指定もできる。"""
        _item(company_a, code="A-001", name="VVFケーブル 1.6mm 2芯")
        original = _alias(company_a, None, raw_name="VVFケーブル 1.6mm 2芯")

        matching.match_item(
            raw_name="VVFケーブル 1.6mm 2芯",
            source_type=ItemAlias.SourceType.ORDERER_BOQ,
            source_key="",
            company=company_a,
            update_existing=False,
        )

        original.refresh_from_db()
        assert original.estimation_item_id is None
        assert original.matched_by == ItemAlias.MatchMethod.MANUAL

    def test_link_survives_embedding_outage(self, company_a):
        """埋め込みが使えない状態で再マッチしても紐付けが消えない。"""
        item = _item(company_a, code="A-001", name="VVFケーブル 1.6mm 2芯")
        original = _alias(
            company_a, item, raw_name="まったく別の表記",
            confidence="85", matched_by=ItemAlias.MatchMethod.EMBEDDING,
        )

        with patch.object(
            matching.embedding_service, "is_configured", return_value=False
        ):
            matching.match_item(
                raw_name="まったく別の表記",
                source_type=ItemAlias.SourceType.ORDERER_BOQ,
                source_key="",
                company=company_a,
            )

        original.refresh_from_db()
        assert original.estimation_item == item
        assert original.confidence == Decimal("85")

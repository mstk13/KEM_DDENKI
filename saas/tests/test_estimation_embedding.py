"""埋め込み類似度マッチングのテスト（ADR-0010 層A）。

- テナント越境テスト（ItemEmbedding）
- 閾値の振る舞い（自動確定 / 候補提示 / 不一致）
- Ollama 到達不可時のフォールバック
- confidence 上限（レビューを飛ばさないこと）

Ollama への実通信は行わない。embedding サービスをモックして
「どのベクトルが返るか」を固定し、判定ロジックだけを検証する。
"""

from decimal import Decimal
from unittest.mock import patch

import pytest

from apps.core.tenant_context import set_current_company
from apps.estimation.models import EstimationItem, ItemAlias, ItemEmbedding
from apps.estimation.services import embedding as embedding_service
from apps.estimation.services import matching
from apps.estimation.services.matching import _match_by_embedding


def _vec(*values) -> list[float]:
    """テスト用の短いベクトル。次元数は判定ロジックに影響しない。"""
    return [float(v) for v in values]


def _make_item(company, code, name, vector=None, *, unit="m"):
    item = EstimationItem.unscoped.create(
        company=company, code=code, canonical_name=name, unit=unit,
    )
    if vector is not None:
        ItemEmbedding.unscoped.create(
            company=company,
            estimation_item=item,
            vector=vector,
            model_tag="bge-m3",
            dim=len(vector),
            source_text=name,
            source_hash="dummy",
        )
    return item


# ---------------------------------------------------------------------------
# テナント越境テスト
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestItemEmbeddingIsolation:
    def test_embedding_isolation(self, company_a, company_b):
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))
        _make_item(company_b, "B-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        set_current_company(company_a)
        assert ItemEmbedding.objects.count() == 1
        assert ItemEmbedding.objects.first().company_id == company_a.id

        set_current_company(company_b)
        assert ItemEmbedding.objects.count() == 1
        assert ItemEmbedding.objects.first().company_id == company_b.id

        set_current_company(None)
        assert ItemEmbedding.unscoped.count() == 2

    def test_matching_does_not_cross_tenants(self, company_a, company_b):
        """B社の品目がA社のマッチング候補に出てはならない。"""
        _make_item(company_b, "B-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            item, confidence, candidates = _match_by_embedding(
                "VVFケーブル 1.6mm 2芯", "VVFケーブル1.6mm2芯", company_a,
            )

        assert item is None
        assert candidates == []
        assert confidence == Decimal("0")


# ---------------------------------------------------------------------------
# 閾値の振る舞い
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEmbeddingThresholds:
    def test_auto_confirm_above_085(self, company_a):
        """類似度 0.85 以上なら自動確定する。"""
        target = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            item, confidence, candidates = _match_by_embedding(
                "VVF 1.6-2C", "VVF1.6-2C", company_a,
            )

        assert item == target
        assert confidence > Decimal("0")
        assert candidates == []

    def test_middle_band_returns_candidates_without_confirming(self, company_a):
        """0.65〜0.85 は確定させず、候補だけ返す。

        実測で同一品目の略記(0.768)と別種ケーブル(0.668)の差が 0.10 しかない。
        この帯域を自動確定させると別品目を誤って結びつける。
        """
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))
        _make_item(company_a, "A-002", "CVケーブル 2.0mm 3芯", _vec(0, 1, 0))

        # cos((1,0.9,0),(1,0,0)) = 1/sqrt(1.81) ≒ 0.743 で中間帯に入る
        with patch.object(
            embedding_service, "embed_text", return_value=_vec(1, 0.9, 0),
        ):
            item, confidence, candidates = _match_by_embedding(
                "VVF 1.6-2C", "VVF1.6-2C", company_a,
            )

        assert item is None, "中間帯で自動確定してはならない"
        assert confidence == Decimal("0")
        assert len(candidates) >= 1
        assert all(isinstance(c, EstimationItem) for c in candidates)

    def test_below_065_returns_nothing(self, company_a):
        """0.65 未満は候補にもしない。"""
        _make_item(company_a, "A-001", "分電盤 20回路", _vec(0, 0, 1))

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            item, confidence, candidates = _match_by_embedding(
                "VVF 1.6-2C", "VVF1.6-2C", company_a,
            )

        assert item is None
        assert candidates == []

    def test_confidence_never_reaches_reviewed(self, company_a):
        """類似度がどれだけ高くても status=REVIEWED にしてはならない。

        confidence が 90 以上になると match_item がレビューを飛ばす。
        類似度一致は必ず人間の確認を要求する。
        """
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            _item, confidence, _candidates = _match_by_embedding(
                "VVFケーブル 1.6mm 2芯", "VVFケーブル1.6mm2芯", company_a,
            )

        assert confidence <= Decimal(str(matching.EMBEDDING_MAX_CONFIDENCE))
        assert confidence < Decimal("90")


# ---------------------------------------------------------------------------
# フォールバック
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestEmbeddingFallback:
    def test_unreachable_ollama_falls_through(self, company_a):
        """Ollama に到達できなくても例外を投げず、静かに諦める。"""
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        with patch.object(embedding_service, "embed_text", return_value=None):
            item, confidence, candidates = _match_by_embedding(
                "VVF 1.6-2C", "VVF1.6-2C", company_a,
            )

        assert item is None
        assert confidence == Decimal("0")
        assert candidates == []

    def test_disabled_feature_is_skipped(self, company_a):
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        with patch.object(embedding_service, "is_configured", return_value=False):
            item, _confidence, candidates = _match_by_embedding(
                "VVF 1.6-2C", "VVF1.6-2C", company_a,
            )

        assert item is None
        assert candidates == []

    def test_no_embeddings_generated_yet(self, company_a):
        """ベクトル未生成の品目しかない場合もフォールバックする。"""
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", vector=None)

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            item, _confidence, candidates = _match_by_embedding(
                "VVF 1.6-2C", "VVF1.6-2C", company_a,
            )

        assert item is None
        assert candidates == []


# ---------------------------------------------------------------------------
# カスケード統合
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCascadeIntegration:
    def test_match_item_records_embedding_method(self, company_a):
        """自動確定した場合 matched_by が embedding になり、status は未確認のまま。"""
        _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            alias = matching.match_item(
                raw_name="VVF 1.6-2C 100m",
                source_type=ItemAlias.SourceType.ORDERER_BOQ,
                source_key="",
                company=company_a,
                use_llm=False,
            )

        assert alias.matched_by == ItemAlias.MatchMethod.EMBEDDING
        assert alias.status == ItemAlias.Status.PENDING
        assert alias.estimation_item is not None

    def test_exact_code_still_wins(self, company_a):
        """コード完全一致は埋め込みより優先される。"""
        target = _make_item(company_a, "A-001", "VVFケーブル 1.6mm 2芯", _vec(1, 0, 0))
        _make_item(company_a, "A-999", "全く別の品目", _vec(1, 0, 0))

        with patch.object(embedding_service, "embed_text", return_value=_vec(1, 0, 0)):
            alias = matching.match_item(
                raw_name="なんらかの品名",
                source_type=ItemAlias.SourceType.ORDERER_BOQ,
                source_key="A-001",
                company=company_a,
            )

        assert alias.matched_by == ItemAlias.MatchMethod.EXACT_CODE
        assert alias.estimation_item == target


# ---------------------------------------------------------------------------
# ユーティリティ（DB不要）
# ---------------------------------------------------------------------------


class TestSimilarityHelpers:
    def test_cosine_identical(self):
        assert embedding_service.cosine_similarity(
            _vec(1, 2, 3), _vec(1, 2, 3)
        ) == pytest.approx(1.0, abs=1e-5)

    def test_cosine_orthogonal(self):
        assert embedding_service.cosine_similarity(
            _vec(1, 0), _vec(0, 1)
        ) == pytest.approx(0.0, abs=1e-5)

    def test_cosine_handles_empty(self):
        assert embedding_service.cosine_similarity([], [1.0]) == 0.0

    def test_rank_filters_by_min_score(self):
        ranked = embedding_service.rank_by_similarity(
            _vec(1, 0),
            [("near", _vec(1, 0.1)), ("far", _vec(0, 1))],
            min_score=0.65,
        )
        assert [obj for obj, _s in ranked] == ["near"]

    def test_rank_respects_top_k(self):
        candidates = [(f"item{i}", _vec(1, i * 0.01)) for i in range(10)]
        ranked = embedding_service.rank_by_similarity(
            _vec(1, 0), candidates, top_k=3, min_score=0.0,
        )
        assert len(ranked) == 3

    def test_rank_is_descending(self):
        ranked = embedding_service.rank_by_similarity(
            _vec(1, 0),
            [("far", _vec(1, 1)), ("near", _vec(1, 0.05))],
            min_score=0.0,
        )
        assert [obj for obj, _s in ranked] == ["near", "far"]


class TestSourceTextBuilder:
    """索引側と照会側で文字列の形を揃えること。

    照合相手は数量書の生の品名で、単位も仕様も付いていない。
    品目側だけを補強すると同一品目でも類似度が下がり、
    実測で 0.9036 → 0.8412 まで落ちて自動確定の閾値を割った。
    """

    def test_uses_canonical_name_only(self):
        from apps.estimation.management.commands.build_item_embeddings import (
            build_source_text,
        )

        item = EstimationItem(
            code="A-001",
            canonical_name="VVFケーブル 1.6mm 2芯 100m巻",
            unit="巻",
            spec={"type": "VVF", "size": "1.6", "cores": 2},
        )
        text = build_source_text(item)

        assert text == "VVFケーブル 1.6mm 2芯 100m巻"
        # 単位・仕様は混ぜない。照会側に同じものを付けられないため。
        assert "巻 VVF" not in text
        assert "1.6 2" not in text

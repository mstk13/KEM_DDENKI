"""労務単価表の抽出精度を、公開データのゴールデンフィクスチャで検証する。

CI で自動実行される。ネットワークもモデルも不要。

フィクスチャは国土交通省・農林水産省が無償公開している
「令和8年3月から適用する公共工事設計労務単価表」の3ページ目を
pdfplumber で抽出したもの（tests/fixtures/labor_rate_page03.json）。
再配布可の公的データであり、data_scope は public。

このテストが守っているもの:
- 決定論的パーサが実データで 100% 読めること（回帰検知）
- 単価なしセルを 0 ではなく None にすること
- _parse_json が途中で切れた JSON を握り潰さないこと
  （実データで max_tokens 到達 → 全件消失していた）
"""

import json
from pathlib import Path

import pytest

from apps.estimation.services import labor_table
from apps.estimation.services.labor_pdf import _parse_json

FIXTURE = Path(__file__).parent / "fixtures" / "labor_rate_page03.json"


@pytest.fixture(scope="module")
def page_fixture():
    with FIXTURE.open(encoding="utf-8") as f:
        return json.load(f)


class TestDeterministicParser:
    """実データに対する回帰検証。数値が動いたら気づけるようにする。"""

    def test_fixture_is_public_data(self, page_fixture):
        """再配布可の公的データであることを明示しておく。"""
        assert page_fixture["source"]["data_scope"] == "public"

    def test_extracts_expected_volume(self, page_fixture):
        rows = labor_table.parse_page(page_fixture["tables"])
        # 47都道府県 × 職種列。ページ構成が変わらない限りこの規模になる。
        assert len(rows) >= 400, f"抽出件数が急減している: {len(rows)}"

    def test_all_prefectures_present(self, page_fixture):
        rows = labor_table.parse_page(page_fixture["tables"])
        prefectures = {r.prefecture for r in rows}
        assert len(prefectures) == 47, f"都道府県が揃っていない: {len(prefectures)}"
        for expected in ("北海道", "東京都", "大阪府", "沖縄県"):
            assert expected in prefectures

    def test_known_values_are_exact(self, page_fixture):
        """既知の実値と一致すること。表の読み違いを検知する。"""
        rows = labor_table.parse_page(page_fixture["tables"])
        table = {(r.prefecture, r.occupation_name): r.unit_price for r in rows}

        assert table[("北海道", "特殊作業員")] == 26000
        assert table[("北海道", "普通作業員")] == 21500
        assert table[("北海道", "軽作業員")] == 19200
        assert table[("青森県", "特殊作業員")] == 30100
        assert table[("宮城県", "軽作業員")] == 20300

    def test_prices_are_int_or_none_never_zero(self, page_fixture):
        """単価なしは None。0 にすると集計を狂わせる。"""
        rows = labor_table.parse_page(page_fixture["tables"])
        for row in rows:
            assert row.unit_price is None or isinstance(row.unit_price, int)
            assert row.unit_price != 0

    def test_prices_are_plausible(self, page_fixture):
        """桁の取り違え（カンマ処理ミス等）を検知する。"""
        prices = [
            r.unit_price
            for r in labor_table.parse_page(page_fixture["tables"])
            if r.unit_price is not None
        ]
        assert prices, "単価が1件も取れていない"
        assert min(prices) >= 10000, f"単価が低すぎる: {min(prices)}"
        assert max(prices) <= 100000, f"単価が高すぎる: {max(prices)}"

    def test_recognises_rate_table(self, page_fixture):
        """このページは LLM を呼ばずに処理されるべき。"""
        assert labor_table.looks_like_rate_table(page_fixture["tables"]) is True

    def test_rejects_unstructured_page(self):
        """規則的でない表は LLM へ回す判定になること。"""
        assert labor_table.looks_like_rate_table([]) is False
        assert labor_table.looks_like_rate_table([[["備考"], ["※注記"]]]) is False


class TestParserEdgeCases:
    def test_empty_and_dash_cells_become_none(self):
        table = [
            ["地方連絡協議会名", "都道府県名", "電工", "溶接工"],
            ["関東", "13 東京都", "", "-"],
        ]
        rows = labor_table.parse_rate_table(table)
        assert {r.occupation_name: r.unit_price for r in rows} == {
            "電工": None, "溶接工": None,
        }

    def test_group_header_rows_are_skipped(self):
        table = [
            ["地方連絡協議会名", "都道府県名", "電工"],
            ["東 北", "", ""],
            ["", "02 青森県", "30,100"],
        ]
        rows = labor_table.parse_rate_table(table)
        assert len(rows) == 1
        assert rows[0].prefecture == "青森県"
        assert rows[0].unit_price == 30100

    def test_comma_separated_prices(self):
        table = [
            ["地方連絡協議会名", "都道府県名", "電工"],
            ["関東", "13 東京都", "1,234,567"],
        ]
        rows = labor_table.parse_rate_table(table)
        assert rows[0].unit_price == 1234567


class TestTruncatedJsonHandling:
    """max_tokens 到達で JSON が途中で切れた場合の挙動。

    旧実装は閉じフェンスを探して ValueError になり、
    呼び出し側がそれを握り潰して全件を捨てていた。
    実データ（正解422件）で 0 件になる事故が起きていた。
    """

    def test_parses_fenced_json(self):
        text = '```json\n{"prefecture": "東京都", "rates": []}\n```'
        assert _parse_json(text)["prefecture"] == "東京都"

    def test_parses_bare_json(self):
        assert _parse_json('{"prefecture": "東京都", "rates": []}')["rates"] == []

    def test_truncated_json_raises_not_silently_empty(self):
        """途中で切れていたら JSONDecodeError を上げること。

        ValueError("substring not found") で落ちるのは
        「閉じフェンスが無い」だけであり、パース不能とは違う。
        呼び出し側が原因を区別できるようにする。
        """
        truncated = '```json\n{"prefecture": "東京都", "rates": [{"occupation_name": "電'
        with pytest.raises(json.JSONDecodeError):
            _parse_json(truncated)

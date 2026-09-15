"""入札参加資格を原本（入札案件参加資格.pdf）と照らし合わせて直す（ADR-0063）。"""

import datetime
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.bids import qualification_source as src
from apps.bids.management.commands.verify_qualifications import row_key
from apps.bids.models import Qualification, UnifiedQualification


def _run(company, *args):
    out = StringIO()
    call_command("verify_qualifications", "--company", str(company.pk), *args, stdout=out)
    return out.getvalue()


def _register(company, rows=None):
    for row in src.ALL_ROWS if rows is None else rows:
        Qualification.unscoped.create(company=company, **row)


def _get(company, issuer, category):
    return Qualification.unscoped.get(company=company, issuer=issuer, category=category)


class TestSource:
    def test_原本の行数(self):
        assert len(src.LIST_ROWS) == 92
        assert len(src.UNIFIED_ROWS) == 3

    def test_発注機関と業種の組は重ならない(self):
        keys = [row_key(r["issuer"], r["category"]) for r in src.ALL_ROWS]
        assert len(keys) == len(set(keys))

    def test_原本の読み取りと判断(self):
        rows = {(r["issuer"], r["category"]): r for r in src.ALL_ROWS}
        assert rows[("財務省(北海道財務局)", "電気工事")]["keisin_score"] == 884
        assert rows[("国土交通省(関東地方整備局)", "電気設備")]["total_score"] == 2054
        assert rows[("内閣府(沖縄総合事務局)", "電気設備")]["total_score"] == 1947
        assert rows[("国土交通省(九州地方整備局)", "橋梁補修")]["vendor_number"] == "00024690000"
        assert rows[("法務省", "電気通信")]["grade"] == "○"
        assert rows[("全省庁統一資格", "物品の買受け")]["memo"] == "営業品目: その他"
        assert all(r["valid_until"] == datetime.date(2027, 3, 31) for r in src.LIST_ROWS)
        assert all(r["valid_until"] == datetime.date(2028, 3, 31) for r in src.UNIFIED_ROWS)


@pytest.mark.django_db
class TestVerifyCommand:
    def test_原本どおりなら違いなし(self, company_a):
        _register(company_a)
        assert "■ 違いはありません" in _run(company_a)

    def test_確認だけでは変えずに修正前と修正後を出す(self, company_a):
        _register(company_a)
        q = _get(company_a, "国土交通省(九州地方整備局)", "電気設備")
        q.vendor_number = "24690000"
        q.save()

        out = _run(company_a)

        target = f"- 国土交通省(九州地方整備局) / 電気設備（id={q.pk}）"
        assert f"{target} | 業者番号 | 24690000 → 00024690000" in out
        assert "確認だけです" in out
        q.refresh_from_db()
        assert q.vendor_number == "24690000"

    def test_applyで直して足りない行を登録し_もう一度見ると違いなし(self, company_a):
        _register(company_a)
        hokkaido = _get(company_a, "財務省(北海道財務局)", "電気工事")
        hokkaido.keisin_score = 8884
        hokkaido.save()
        tohoku = _get(company_a, "国土交通省(東北地方整備局)", "電気設備")
        tohoku.issuer = "国土交通省（東北地方整備局）"  # 括弧の違いは同じ機関とみなす
        tohoku.grade = "Ｂ"
        tohoku.valid_until = datetime.date(2027, 4, 1)
        tohoku.save()
        Qualification.unscoped.filter(company=company_a, issuer="国立印刷局").delete()

        out = _run(company_a, "--apply")

        assert "| 経審点 | 8884 → 884" in out
        assert "| 等級 | Ｂ → B" in out
        assert "| 有効期限 | 2027-04-01 → 2027-03-31" in out
        assert "- 国立印刷局 / 電気工事 | （行の追加） | （未登録） → 等級 B・経審 886" in out
        hokkaido.refresh_from_db()
        tohoku.refresh_from_db()
        assert hokkaido.keisin_score == 884
        assert (tohoku.grade, tohoku.valid_until) == ("B", datetime.date(2027, 3, 31))
        assert Qualification.unscoped.filter(company=company_a).count() == len(src.ALL_ROWS)
        assert "■ 違いはありません" in _run(company_a)

    def test_修正は履歴に理由付きで残る(self, company_a):
        _register(company_a)
        q = _get(company_a, "防衛省", "電気工事")
        q.grade = "B"
        q.save()

        _run(company_a, "--apply")

        latest = q.history.first()
        assert latest.grade == "A"
        assert "入札案件参加資格.pdf" in latest.history_change_reason

    def test_原本に無い行と重複はdelete_extraのときだけ消す(self, company_a):
        _register(company_a)
        dup = Qualification.unscoped.create(company=company_a, **src.LIST_ROWS[0])
        unknown = Qualification.unscoped.create(
            company=company_a, issuer="不明", category="電気工事", grade="A",
        )

        out = _run(company_a, "--apply")

        assert f"[重複] 国土交通省 / 電気工事（id={dup.pk}）" in out
        assert f"[原本に無い] 不明 / 電気工事（id={unknown.pk}）" in out
        assert Qualification.unscoped.filter(pk__in=[dup.pk, unknown.pk]).count() == 2

        _run(company_a, "--apply", "--delete-extra")

        assert not Qualification.unscoped.filter(pk__in=[dup.pk, unknown.pk]).exists()
        assert Qualification.unscoped.filter(company=company_a).count() == len(src.ALL_ROWS)

    def test_delete_extraはapplyと一緒でないと動かない(self, company_a):
        with pytest.raises(CommandError):
            _run(company_a, "--delete-extra")

    def test_省庁別の全省庁統一資格の等級_点数_営業品目(self, company_a):
        common = {
            "goods_sales_grade": "C", "goods_sales_score": 62,
            "services_grade": "C", "services_score": 62,
            "services_items": "賃貸借/建物管理等各種保守管理/その他",
        }
        UnifiedQualification.unscoped.create(
            company=company_a, agency="衆議院", sort_order=1, purchase_grade="B",
            purchase_score=62, **common,
            # 区切りが違うだけなら直さない
            goods_sales_items="電気・通信用機器類／精密機器類／その他機器類／土木・建設・建築材料／その他",
        )
        bad = UnifiedQualification.unscoped.create(
            company=company_a, agency="防衛省", sort_order=2, purchase_grade="C",
            purchase_score=None, goods_sales_items="電気・通信用機器類/その他", **common,
        )
        _register(company_a)

        out = _run(company_a, "--apply")

        assert "衆議院" not in out
        assert "| 物品の買受け 等級 | C → B" in out
        assert "| 物品の買受け 点数 | （空欄） → 62" in out
        bad.refresh_from_db()
        assert (bad.purchase_grade, bad.purchase_score) == ("B", 62)
        assert bad.goods_sales_items == (
            "電気・通信用機器類/精密機器類/その他機器類/土木・建設・建築材料/その他"
        )

    def test_他社の登録は見ないし変えない(self, company_a, company_b):
        _register(company_a)
        other = Qualification.unscoped.create(
            company=company_b, issuer="防衛省", category="電気工事", grade="C",
        )

        out = _run(company_a, "--apply", "--delete-extra")

        assert "■ 違いはありません" in out
        other.refresh_from_db()
        assert other.grade == "C"

    def test_登録コマンドの全省庁統一資格は原本どおり(self, company_a):
        _register(company_a, src.LIST_ROWS)
        call_command("seed_qualifications", stdout=StringIO())

        assert "■ 違いはありません" in _run(company_a)

"""候補から選び、無ければその場でマスタに登録する（ADR-0096）。

確かめること:

1. 候補に無い名前を入力すると、そのマスタにも登録される（工種・材料・顧客・
   発注先・積算品目・現場）
2. 既にある名前はそのまま引き当てる。同じものを2つ作らない
3. 空欄のままなら紐づけを付けない
4. 引き当ては完全一致だけ。似た名前を勝手に寄せない
5. 画面に候補の一覧（datalist）が出る
6. 他社のマスタには触れない・候補にも出ない（テナント越境）
"""
import datetime

import pytest

from apps.core.master_input import (
    name_choices,
    next_code,
    resolve_customer,
    resolve_estimation_item,
    resolve_material,
    resolve_site,
    resolve_work_type,
)
from apps.estimation.forms import (
    BoqLineForm,
    EstimationItemForm,
    OrdererForm,
    PurchaseRecordForm,
)
from apps.estimation.models import EstimationItem, EstimationProject, Orderer
from apps.masters.models import Customer, Supplier, WorkType
from apps.materials.models import Material
from apps.sites.forms import ProcessForm
from apps.sites.models import Process, Site

DAY = datetime.date(2026, 9, 18)


# ---------------------------------------------------------------------------
# 引き当てと登録
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestResolvers:
    def test_無ければ登録する(self, company_a):
        work_type = resolve_work_type(company_a, "高圧受電設備工事")

        assert work_type.pk is not None
        assert work_type.name == "高圧受電設備工事"
        assert work_type.code  # コードは自動で採番する

    def test_あればそのまま引き当てる(self, company_a):
        first = resolve_work_type(company_a, "電気工事")
        again = resolve_work_type(company_a, "電気工事")

        assert first.pk == again.pk
        assert WorkType.unscoped.filter(company=company_a).count() == 1

    def test_空なら何も作らない(self, company_a):
        assert resolve_work_type(company_a, "") is None
        assert resolve_work_type(company_a, "   ") is None
        assert WorkType.unscoped.filter(company=company_a).count() == 0

    def test_前後の空白は落とす(self, company_a):
        resolve_work_type(company_a, "  電気工事  ")

        assert WorkType.unscoped.get(company=company_a).name == "電気工事"

    def test_似た名前は寄せない(self, company_a):
        """「厚木市」と「厚木市教育委員会」は別物。寄せると取り違える（ADR-0080）。"""
        resolve_customer(company_a, "厚木市")
        resolve_customer(company_a, "厚木市教育委員会")

        assert Customer.unscoped.filter(company=company_a).count() == 2

    def test_コードは使われていない連番を振る(self, company_a):
        WorkType.unscoped.create(company=company_a, code="W0001", name="既存")

        work_type = resolve_work_type(company_a, "新しい工種")

        assert work_type.code == "W0002"

    def test_単位が要るマスタは渡した単位で作る(self, company_a):
        material = resolve_material(company_a, "CVT38sq", unit="m")
        item = resolve_estimation_item(company_a, "低圧ケーブル", unit="m")

        assert material.unit == "m"
        assert item.unit == "m"

    def test_単位が分からなければ式にする(self, company_a):
        """必須項目を人に聞き直すと、そこで入力が止まる。"""
        assert resolve_material(company_a, "雑材料").unit == "式"

    def test_候補は重複なく並ぶ(self, company_a):
        resolve_work_type(company_a, "電気工事")
        resolve_work_type(company_a, "通信工事")

        assert name_choices(WorkType.unscoped.filter(company=company_a)) == [
            "通信工事", "電気工事",
        ]

    def test_採番は空の一覧でも動く(self, company_a):
        assert next_code(WorkType.unscoped.filter(company=company_a), "W") == "W0001"


# ---------------------------------------------------------------------------
# 現場の工程 — 工種
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestProcessForm:
    def _data(self, **over):
        data = {"name": "受電設備更新", "status": "planned", "display_order": 10,
                "work_type_name": "高圧受電設備工事"}
        data.update(over)
        return data

    def test_候補に無い工種を入力すると工種マスタにも登録される(self, company_a):
        site = Site.unscoped.create(company=company_a, code="S001", name="七沢センター")
        form = ProcessForm(self._data(), company=company_a)

        assert form.is_valid(), form.errors
        process = form.save(commit=False)
        process.company = company_a
        process.site = site
        process.save()

        assert process.work_type.name == "高圧受電設備工事"
        assert WorkType.unscoped.filter(company=company_a, name="高圧受電設備工事").exists()

    def test_工種は空にできない(self, company_a):
        """自由入力にしても、必須の欄（Process.work_type）が空のままは通さない。"""
        form = ProcessForm(self._data(work_type_name=""), company=company_a)

        assert not form.is_valid()
        assert "work_type_name" in form.errors

    def test_編集画面には今の工種が初期値で入る(self, company_a):
        site = Site.unscoped.create(company=company_a, code="S001", name="七沢センター")
        work_type = WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
        process = Process.unscoped.create(
            company=company_a, site=site, name="工程", work_type=work_type, display_order=10,
        )

        form = ProcessForm(instance=process, company=company_a)

        assert form.fields["work_type_name"].initial == "電気工事"

    def test_候補が画面に出る(self, company_a):
        WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")

        form = ProcessForm(company=company_a)

        assert form.work_type_choices == ["電気工事"]


# ---------------------------------------------------------------------------
# 積算品目 — 材料・工種
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEstimationItemForm:
    def _data(self, **over):
        data = {
            "code": "I001", "canonical_name": "低圧ケーブル", "category": "wire",
            "unit": "m", "status": "draft",
            "material_name": "CVT38sq", "work_type_name": "電気工事",
        }
        data.update(over)
        return data

    def test_候補に無い材料と工種を入力すると両方のマスタに登録される(self, company_a):
        form = EstimationItemForm(self._data(), company=company_a)

        assert form.is_valid(), form.errors
        item = form.save(commit=False)
        item.company = company_a
        item.save()

        assert item.material.name == "CVT38sq"
        assert item.work_type.name == "電気工事"
        assert Material.unscoped.filter(company=company_a, name="CVT38sq").exists()

    def test_材料の単位は品目の単位を引き継ぐ(self, company_a):
        form = EstimationItemForm(self._data(unit="m"), company=company_a)
        assert form.is_valid(), form.errors
        item = form.save(commit=False)
        item.company = company_a
        item.save()

        assert item.material.unit == "m"

    def test_既にある材料は新しく作らない(self, company_a):
        Material.unscoped.create(company=company_a, code="M001", name="CVT38sq", unit="m")

        form = EstimationItemForm(self._data(), company=company_a)
        assert form.is_valid(), form.errors
        item = form.save(commit=False)
        item.company = company_a
        item.save()

        assert Material.unscoped.filter(company=company_a).count() == 1


# ---------------------------------------------------------------------------
# 発注機関 — 顧客
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestOrdererForm:
    def test_候補に無い顧客を入力すると顧客マスタにも登録される(self, company_a):
        form = OrdererForm(
            {"name": "厚木市", "kind": "city", "system_type": "eizen",
             "customer_name": "厚木市役所"},
            company=company_a,
        )

        assert form.is_valid(), form.errors
        orderer = form.save(commit=False)
        orderer.company = company_a
        orderer.save()

        assert orderer.customer.name == "厚木市役所"
        assert Customer.unscoped.filter(company=company_a, name="厚木市役所").exists()

    def test_空のままなら顧客を付けない(self, company_a):
        form = OrdererForm(
            {"name": "厚木市", "kind": "city", "system_type": "eizen", "customer_name": ""},
            company=company_a,
        )

        assert form.is_valid(), form.errors
        orderer = form.save(commit=False)
        orderer.company = company_a
        orderer.save()

        assert orderer.customer_id is None


# ---------------------------------------------------------------------------
# 仕入実績 — 発注先
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPurchaseRecordForm:
    def test_候補に無い発注先を入力すると発注先マスタにも登録される(self, company_a):
        form = PurchaseRecordForm(
            {"raw_name": "CVT38sq", "purchase_date": DAY.isoformat(),
             "quantity": "10", "unit_price": "1200", "supplier_name": "山田電材"},
            company=company_a,
        )

        assert form.is_valid(), form.errors
        record = form.save(commit=False)
        record.company = company_a
        record.save()

        assert record.supplier.name == "山田電材"
        assert Supplier.unscoped.filter(company=company_a, name="山田電材").exists()


# ---------------------------------------------------------------------------
# 内訳明細 — 積算品目
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBoqLineForm:
    def test_候補に無い品目を入力すると品目マスタにも登録される(self, company_a):
        orderer = Orderer.unscoped.create(company=company_a, name="厚木市")
        project = EstimationProject.unscoped.create(
            company=company_a, name="七沢センター改修", orderer=orderer,
        )
        form = BoqLineForm(
            {"level": "saimoku", "sort_order": 10, "name": "低圧ケーブル敷設",
             "unit": "m", "estimation_item_name": "低圧ケーブル"},
            company=company_a, project=project,
        )

        assert form.is_valid(), form.errors
        line = form.save(commit=False)
        line.company = company_a
        line.project = project
        line.save()

        assert line.estimation_item.canonical_name == "低圧ケーブル"
        assert line.estimation_item.unit == "m"

    def test_候補は品目の正式名称から作る(self, company_a):
        EstimationItem.unscoped.create(
            company=company_a, code="I001", canonical_name="低圧ケーブル", unit="m",
        )

        form = BoqLineForm(company=company_a)

        assert form.estimation_item_choices == ["低圧ケーブル"]


# ---------------------------------------------------------------------------
# 積算案件 — 現場
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestEstimationProjectSite:
    def test_候補に無い現場名を入力すると現場も登録される(self, company_a):
        site = resolve_site(company_a, "七沢センター改修")

        assert site.pk is not None
        assert Site.unscoped.filter(company=company_a, name="七沢センター改修").exists()

    def test_既にある現場は新しく作らない(self, company_a):
        """二重登録を作らないことが、この欄でいちばん大事。"""
        existing = Site.unscoped.create(company=company_a, code="S001", name="高橋住宅")

        again = resolve_site(company_a, "高橋住宅")

        assert again.pk == existing.pk
        assert Site.unscoped.filter(company=company_a).count() == 1

    def test_候補には既にある現場が並ぶ(self, company_a):
        """打ちかけで既存の現場が出るので、別名で二重に作る手前で気づける。"""
        from apps.estimation.forms import EstimationProjectForm

        Site.unscoped.create(company=company_a, code="S001", name="高橋住宅")

        form = EstimationProjectForm(company=company_a)

        assert "高橋住宅" in form.site_choices


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestScreens:
    def test_工程の画面に候補の一覧が出る(self, client, company_a, user_a):
        site = Site.unscoped.create(company=company_a, code="S001", name="七沢センター")
        WorkType.unscoped.create(company=company_a, code="W01", name="電気工事")
        client.force_login(user_a)

        html = client.get(f"/sites/{site.pk}/processes/new/").content.decode()

        assert 'id="work-type-name-options"' in html
        assert "電気工事" in html

    def test_積算品目の画面に候補の一覧が出る(self, client, company_a, user_a):
        Material.unscoped.create(company=company_a, code="M001", name="CVT38sq", unit="m")
        client.force_login(user_a)

        html = client.get("/estimation/items/new/").content.decode()

        assert 'id="material-name-options"' in html
        assert "CVT38sq" in html


# ---------------------------------------------------------------------------
# テナント越境
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の同名マスタは引き当てず自社に作る(self, company_a, company_b):
        resolve_work_type(company_b, "電気工事")

        mine = resolve_work_type(company_a, "電気工事")

        assert mine.company_id == company_a.pk
        assert WorkType.unscoped.filter(name="電気工事").count() == 2

    def test_他社のマスタは候補に出ない(self, company_a, company_b):
        Material.unscoped.create(company=company_b, code="M001", name="他社の材料", unit="m")

        form = EstimationItemForm(company=company_a)

        assert form.material_choices == []

    def test_他社の現場は候補に出ない(self, company_a, company_b):
        from apps.estimation.forms import EstimationProjectForm

        Site.unscoped.create(company=company_b, code="B001", name="他社の現場")

        form = EstimationProjectForm(company=company_a)

        assert form.site_choices == []

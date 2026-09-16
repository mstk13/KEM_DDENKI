"""入札案件 → 積算案件 → 現場管理 の引っ越しと、失注の記録（ADR-0076）。

確かめること:

- 積算を始めると積算案件ができ、入札案件は「積算中」になって一覧から消える
- 公告の手続き期限が積算工程として取り込まれ、二度押ししても増えない
- 受注すると現場が受注済になり、現場管理へ渡る
- 失注すると原因が残り、競合との差額が自社応札額から計算される
- 以上が他社のデータに触れない（テナント越境）
"""
import datetime
import json
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.bids.models import BidProject
from apps.bids.services import start_estimation
from apps.estimation.models import (
    EstimationCompetitor,
    EstimationPhase,
    EstimationProject,
    Orderer,
)
from apps.estimation.services.from_bid import (
    create_estimation_project_from_bid,
    import_phases_from_bid,
)
from apps.estimation.services.outcome import mark_lost, mark_won
from apps.sites.models import Site


def _aware(y, m, d, hh=17, mm=0):
    return timezone.make_aware(
        datetime.datetime(y, m, d, hh, mm), timezone.get_current_timezone(),
    )


def _bid(company, **kwargs):
    """公告の別表まで読めている入札案件を1件作る。"""
    fields = {
        "title": "七沢自然ふれあいセンター改修（電気）工事",
        "client": "厚木市",
        "announced_on": datetime.date(2026, 9, 1),
        "opening_on": datetime.date(2026, 11, 11),
        "deadline": _aware(2026, 10, 27),
        "budget": Decimal("65923000"),
        "bid_schedule": [
            {"label": "申請書及び資料の提出期限",
             "datetime": "2026-09-17T12:00", "detail": "電子入札システムで提出"},
            {"label": "入札書の受領期限",
             "datetime": "2026-10-27T17:00", "detail": ""},
            {"label": "開札の日時及び場所",
             "datetime": "2026-11-11T15:00", "detail": "第2会議室"},
        ],
    }
    fields.update(kwargs)
    return BidProject.unscoped.create(company=company, **fields)


def _inline_edit(client, obj, field, value):
    """一覧のインライン編集（ADR-0074）を叩く。ビューは JSON を受ける。"""
    return client.post(
        "/bids/inline-edit/",
        data=json.dumps({
            "model": "bids.BidProject", "pk": obj.pk,
            "field": field, "value": value,
        }),
        content_type="application/json",
    )


@pytest.mark.django_db
class TestMoveToEstimation:
    def test_積算開始で積算案件ができ入札案件は積算中になる(self, company_a, user_a):
        bid = _bid(company_a)

        site, created = start_estimation(bid, created_by=user_a)

        bid.refresh_from_db()
        assert created is True
        assert bid.status == BidProject.Status.ESTIMATING

        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        assert est.status == EstimationProject.Status.ESTIMATING
        assert est.site_id == site.pk
        assert est.name == bid.title
        assert est.bid_opening_date == bid.opening_on
        # 発注者名から発注機関を起こしている
        assert est.orderer.name == "厚木市"

    def test_公告の期限が積算工程として取り込まれる(self, company_a, user_a):
        bid = _bid(company_a)

        start_estimation(bid, created_by=user_a)

        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        phases = list(est.phases.all())
        assert len(phases) == 3

        names = [p.name for p in phases]
        assert "参加申請" in names
        assert "入札書提出" in names
        assert "開札・落札者決定" in names

        # 取り込んだ工程には出所が残り、日付は公告の期限に揃う
        opening = next(p for p in phases if p.name == "開札・落札者決定")
        assert opening.source_label == "開札の日時及び場所"
        assert opening.end_date == datetime.date(2026, 11, 11)
        assert opening.start_date is not None

    def test_二度押ししても積算案件も工程も増えない(self, company_a, user_a):
        bid = _bid(company_a)

        start_estimation(bid, created_by=user_a)
        start_estimation(bid, created_by=user_a)

        assert EstimationProject.unscoped.filter(
            company=company_a, bid_project=bid,
        ).count() == 1
        assert EstimationPhase.unscoped.filter(company=company_a).count() == 3
        assert Site.unscoped.filter(company=company_a).count() == 1

    def test_取り込み直しても手で直した日付は戻らない(self, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)

        phase = est.phases.get(source_label="入札書の受領期限")
        phase.end_date = datetime.date(2026, 10, 20)
        phase.name = "入札書提出（社内締切）"
        phase.save()

        added = import_phases_from_bid(est, bid, created_by=user_a)

        phase.refresh_from_db()
        assert added == 0
        assert phase.end_date == datetime.date(2026, 10, 20)
        assert phase.name == "入札書提出（社内締切）"

    def test_発注者名が同じなら発注機関は1件に寄る(self, company_a, user_a):
        first = _bid(company_a, title="1件目")
        second = _bid(company_a, title="2件目")

        start_estimation(first, created_by=user_a)
        start_estimation(second, created_by=user_a)

        assert Orderer.unscoped.filter(company=company_a, name="厚木市").count() == 1

    def test_別表が無くても入札期限から1本は引ける(self, company_a, user_a):
        bid = _bid(company_a, bid_schedule=[], opening_on=None)

        start_estimation(bid, created_by=user_a)

        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        assert est.phases.count() == 1


@pytest.mark.django_db
class TestBidListHidesMovedProjects:
    def test_積算中の案件は入札案件一覧の既定では出ない(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        client.force_login(user_a)

        res = client.get("/bids/?reset=1")

        assert res.status_code == 200
        assert bid.title not in res.content.decode()

    def test_積算中で絞り込めば入札側の経緯を追える(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        client.force_login(user_a)

        res = client.get("/bids/?status=estimating")

        assert res.status_code == 200
        assert bid.title in res.content.decode()


def _edit_post(bid, **overrides):
    """入札案件の編集画面に送る中身。必須項目を埋めておく。"""
    data = {
        "title": bid.title, "client": bid.client, "agency_dept": "",
        "region": "", "location": "", "category": "", "bid_method": "",
        "electronic_bid": "", "design_no": "",
        "announced_on": "", "deadline": "", "opening_on": "",
        "budget": "0", "source_url": "", "status": bid.status,
        "required_category": "", "required_grade": "", "required_grades": "",
        "required_score": "", "required_issuer_type": "",
        "work_outline": "", "requirements": "", "notes": "",
        "cost-estimate_amount": "0", "cost-actual_cost": "0", "cost-memo": "",
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
class TestEditFormMovesToo:
    """編集画面・新規登録で状態を「積算中」にしたときも引っ越す。

    状態は「積算開始」ボタン以外からも変えられる。どの経路でも積算案件を
    用意しないと、一覧から消えたのに引っ越し先が無い迷子の案件ができる。
    """

    def test_編集画面で積算中に変えると積算案件ができる(self, client, company_a, user_a):
        bid = _bid(company_a)
        client.force_login(user_a)

        res = client.post(
            f"/bids/{bid.pk}/edit/", _edit_post(bid, status="estimating"),
        )

        bid.refresh_from_db()
        assert bid.status == BidProject.Status.ESTIMATING
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        assert est.status == EstimationProject.Status.ESTIMATING
        assert est.phases.count() == 3
        # 引っ越し先を開く。入札案件一覧に戻してもこの案件はもう出ない
        assert res.status_code == 302
        assert res.url == f"/estimation/projects/{est.pk}/"

    def test_編集画面で別の状態に変えたときは作らない(self, client, company_a, user_a):
        bid = _bid(company_a)
        client.force_login(user_a)

        res = client.post(
            f"/bids/{bid.pk}/edit/", _edit_post(bid, status="considering"),
        )

        bid.refresh_from_db()
        assert res.status_code == 302
        assert res.url == f"/bids/{bid.pk}/"
        assert bid.status == BidProject.Status.CONSIDERING
        assert not EstimationProject.unscoped.filter(company=company_a).exists()

    def test_編集画面で積算中のまま保存しても増えない(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        bid.refresh_from_db()
        client.force_login(user_a)

        client.post(f"/bids/{bid.pk}/edit/", _edit_post(bid, notes="メモを足した"))

        assert EstimationProject.unscoped.filter(company=company_a).count() == 1
        assert Site.unscoped.filter(company=company_a).count() == 1
        assert EstimationPhase.unscoped.filter(company=company_a).count() == 3

    def test_新規登録で積算中を選んでも引っ越す(self, client, company_a, user_a):
        client.force_login(user_a)

        client.post("/bids/new/", {
            "title": "新しく積算する案件", "client": "厚木市",
            "agency_dept": "", "region": "", "location": "", "category": "",
            "bid_method": "", "electronic_bid": "", "design_no": "",
            "announced_on": "", "deadline": "", "opening_on": "",
            "budget": "0", "source_url": "", "status": "estimating",
            "required_category": "", "required_grade": "", "required_grades": "",
            "required_score": "", "required_issuer_type": "",
            "work_outline": "", "requirements": "", "notes": "",
            "cost-estimate_amount": "0", "cost-actual_cost": "0", "cost-memo": "",
        })

        bid = BidProject.unscoped.get(company=company_a, title="新しく積算する案件")
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        assert est.status == EstimationProject.Status.ESTIMATING


@pytest.mark.django_db
class TestInlineEditMovesToo:
    """一覧のインライン編集（ADR-0074）で状態を直したときも引っ越す。

    直しただけで積算案件ができないと、一覧から消えたのに引っ越し先が無い
    迷子の案件ができる。
    """

    def test_一覧で積算中に直すと積算案件ができる(self, client, company_a, user_a):
        bid = _bid(company_a)
        client.force_login(user_a)

        res = _inline_edit(client, bid, "status", "estimating")

        bid.refresh_from_db()
        assert res.status_code == 200
        assert bid.status == BidProject.Status.ESTIMATING
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        assert est.status == EstimationProject.Status.ESTIMATING
        assert est.phases.count() == 3

    def test_引っ越し済みの案件を直しても増えない(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        client.force_login(user_a)

        _inline_edit(client, bid, "status", "estimating")

        assert EstimationProject.unscoped.filter(company=company_a).count() == 1
        assert Site.unscoped.filter(company=company_a).count() == 1

    def test_別の状態に直したときは積算案件を作らない(self, client, company_a, user_a):
        bid = _bid(company_a)
        client.force_login(user_a)

        _inline_edit(client, bid, "status", "considering")

        assert not EstimationProject.unscoped.filter(company=company_a).exists()


@pytest.mark.django_db
class TestOutcome:
    def test_受注すると現場が受注済になり積算案件も落札になる(self, company_a, user_a):
        bid = _bid(company_a)
        site, _ = start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)

        won_site, created = mark_won(
            est, award_amount=Decimal("64000000"), created_by=user_a,
        )

        est.refresh_from_db()
        bid.refresh_from_db()
        won_site.refresh_from_db()
        assert created is False
        assert won_site.pk == site.pk
        assert won_site.status == Site.Status.ORDERED
        assert est.status == EstimationProject.Status.WON
        assert est.award_amount == Decimal("64000000")
        assert est.decided_on == datetime.date.today()
        # 入札案件にも結果が戻る（受注率が数え落とされない）
        assert bid.status == BidProject.Status.WON

    def test_受注で現場は増えない(self, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)

        mark_won(est, created_by=user_a)

        assert Site.unscoped.filter(company=company_a).count() == 1

    def test_失注すると原因が残り積算中の現場は中止になる(self, company_a, user_a):
        bid = _bid(company_a)
        site, _ = start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)

        mark_lost(est, reason=EstimationProject.LostReason.PRICE, note="単価で届かず")

        est.refresh_from_db()
        site.refresh_from_db()
        bid.refresh_from_db()
        assert est.status == EstimationProject.Status.LOST
        assert est.lost_reason == EstimationProject.LostReason.PRICE
        assert est.lost_note == "単価で届かず"
        assert est.decided_on == datetime.date.today()
        assert site.status == Site.Status.CANCELLED
        assert bid.status == BidProject.Status.LOST

    def test_競合との差額と差率を自社応札額から計算する(self, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        est.bid_amount = Decimal("65000000")
        est.save(update_fields=["bid_amount"])

        competitor = EstimationCompetitor.unscoped.create(
            company=company_a, project=est,
            name="◯◯電設", amount=Decimal("62000000"), is_winner=True,
        )

        # 自社のほうが 300万円高い＝負けた側なのでプラス
        assert competitor.difference == Decimal("3000000")
        assert competitor.difference_rate == Decimal("4.84")
        assert est.winning_competitor.pk == competitor.pk
        assert est.lowest_competitor_amount == Decimal("62000000")

    def test_金額が分からない競合では差額を出さない(self, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        est.bid_amount = Decimal("65000000")
        est.save(update_fields=["bid_amount"])

        competitor = EstimationCompetitor.unscoped.create(
            company=company_a, project=est, name="△△工業",
        )

        assert competitor.difference is None
        assert competitor.difference_rate is None

    def test_入札を経ない案件でも受注したら現場ができる(self, company_a, user_a):
        orderer = Orderer.unscoped.create(company=company_a, name="民間発注者")
        est = EstimationProject.unscoped.create(
            company=company_a, name="相対見積の改修工事", orderer=orderer,
            bid_amount=Decimal("3000000"),
        )

        site, created = mark_won(est, created_by=user_a)

        est.refresh_from_db()
        assert created is True
        assert site.status == Site.Status.ORDERED
        assert site.contract_amount == Decimal("3000000")
        assert est.site_id == site.pk


@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の入札案件から積算案件を作っても混ざらない(
        self, company_a, company_b, user_a, user_b,
    ):
        bid_a = _bid(company_a, title="A社の案件")
        bid_b = _bid(company_b, title="B社の案件")

        start_estimation(bid_a, created_by=user_a)
        start_estimation(bid_b, created_by=user_b)

        est_a = EstimationProject.unscoped.get(company=company_a, bid_project=bid_a)
        est_b = EstimationProject.unscoped.get(company=company_b, bid_project=bid_b)

        assert est_a.company_id == company_a.pk
        assert est_b.company_id == company_b.pk
        assert est_a.orderer.company_id == company_a.pk
        assert est_b.orderer.company_id == company_b.pk
        # 同名の発注者でも会社ごとに別レコードになる
        assert est_a.orderer.pk != est_b.orderer.pk

        for phase in est_a.phases.all():
            assert phase.company_id == company_a.pk
        assert EstimationPhase.unscoped.filter(company=company_b).count() == 3

    def test_他社の積算案件は一覧に出ない(self, client, company_a, company_b, user_a, user_b):
        bid_b = _bid(company_b, title="B社だけの案件")
        start_estimation(bid_b, created_by=user_b)
        client.force_login(user_a)

        res = client.get("/estimation/projects/")

        assert res.status_code == 200
        assert "B社だけの案件" not in res.content.decode()

    def test_他社の積算案件の詳細は開けない(self, client, company_a, company_b, user_a, user_b):
        bid_b = _bid(company_b)
        start_estimation(bid_b, created_by=user_b)
        est_b = EstimationProject.unscoped.get(company=company_b, bid_project=bid_b)
        client.force_login(user_a)

        res = client.get(f"/estimation/projects/{est_b.pk}/")

        assert res.status_code == 404

    def test_他社の積算案件に工程を足せない(self, client, company_a, company_b, user_a, user_b):
        bid_b = _bid(company_b)
        start_estimation(bid_b, created_by=user_b)
        est_b = EstimationProject.unscoped.get(company=company_b, bid_project=bid_b)
        client.force_login(user_a)

        res = client.post(
            f"/estimation/projects/{est_b.pk}/phases/new/",
            {"name": "割り込み", "progress": 0, "sort_order": 0, "color": "#000000"},
        )

        assert res.status_code == 404
        assert not EstimationPhase.unscoped.filter(name="割り込み").exists()

    def test_他社の積算案件に競合を足せない(self, client, company_a, company_b, user_a, user_b):
        bid_b = _bid(company_b)
        start_estimation(bid_b, created_by=user_b)
        est_b = EstimationProject.unscoped.get(company=company_b, bid_project=bid_b)
        client.force_login(user_a)

        res = client.post(
            f"/estimation/projects/{est_b.pk}/competitors/new/",
            {"name": "割り込み電設", "amount": "1"},
        )

        assert res.status_code == 404
        assert not EstimationCompetitor.unscoped.filter(name="割り込み電設").exists()

    def test_他社の積算案件を受注にできない(self, client, company_a, company_b, user_a, user_b):
        bid_b = _bid(company_b)
        start_estimation(bid_b, created_by=user_b)
        est_b = EstimationProject.unscoped.get(company=company_b, bid_project=bid_b)
        client.force_login(user_a)

        res = client.post(f"/estimation/projects/{est_b.pk}/won/", {})

        est_b.refresh_from_db()
        assert res.status_code == 404
        assert est_b.status == EstimationProject.Status.ESTIMATING


@pytest.mark.django_db
class TestViews:
    def test_積算開始のボタンは積算案件の画面へ送る(self, client, company_a, user_a):
        bid = _bid(company_a)
        client.force_login(user_a)

        res = client.post(f"/bids/{bid.pk}/start-estimation/")

        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        assert res.status_code == 302
        assert res.url == f"/estimation/projects/{est.pk}/"

    def test_積算案件の画面に日程と受注失注のボタンが出る(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        client.force_login(user_a)

        res = client.get(f"/estimation/projects/{est.pk}/")
        body = res.content.decode()

        assert res.status_code == 200
        assert "日程" in body
        assert "受注した" in body
        assert "失注した" in body
        assert "開札・落札者決定" in body

    def test_受注の確定で現場の画面へ送る(self, client, company_a, user_a):
        bid = _bid(company_a)
        site, _ = start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        client.force_login(user_a)

        res = client.post(
            f"/estimation/projects/{est.pk}/won/",
            {"award_amount": "64000000", "decided_on": "2026-11-11"},
        )

        est.refresh_from_db()
        assert res.status_code == 302
        assert res.url == f"/sites/{site.pk}/"
        assert est.status == EstimationProject.Status.WON
        assert est.decided_on == datetime.date(2026, 11, 11)

    def test_積算案件一覧に失注の原因と差額が出る(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        est.bid_amount = Decimal("65000000")
        est.save(update_fields=["bid_amount"])
        EstimationCompetitor.unscoped.create(
            company=company_a, project=est,
            name="◯◯電設", amount=Decimal("62000000"), is_winner=True,
        )
        mark_lost(est, reason=EstimationProject.LostReason.PRICE)
        client.force_login(user_a)

        res = client.get("/estimation/projects/")
        body = res.content.decode()

        assert res.status_code == 200
        assert "価格" in body
        assert "◯◯電設に 3000000 円差" in body

    def test_失注には原因の選択が要る(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        client.force_login(user_a)

        res = client.post(f"/estimation/projects/{est.pk}/lost/", {"lost_note": "惜しかった"})

        est.refresh_from_db()
        assert res.status_code == 200
        assert est.status == EstimationProject.Status.ESTIMATING

    def test_工程は画面から足して直せる(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        client.force_login(user_a)

        client.post(f"/estimation/projects/{est.pk}/phases/new/", {
            "name": "現地調査", "start_date": "2026-09-05", "end_date": "2026-09-08",
            "progress": 0, "sort_order": 5, "color": "#16a34a",
        })
        phase = EstimationPhase.unscoped.get(company=company_a, name="現地調査")
        assert phase.source_label == ""

        client.post(f"/estimation/phases/{phase.pk}/edit/", {
            "name": "現地調査（2回目）", "start_date": "2026-09-05",
            "end_date": "2026-09-10", "progress": 50, "sort_order": 5,
            "color": "#16a34a",
        })
        phase.refresh_from_db()
        assert phase.name == "現地調査（2回目）"
        assert phase.end_date == datetime.date(2026, 9, 10)
        assert phase.progress == 50

        client.post(f"/estimation/phases/{phase.pk}/delete/")
        assert not EstimationPhase.unscoped.filter(pk=phase.pk).exists()

    def test_終了日が開始日より前の工程は保存しない(self, client, company_a, user_a):
        bid = _bid(company_a)
        start_estimation(bid, created_by=user_a)
        est = EstimationProject.unscoped.get(company=company_a, bid_project=bid)
        client.force_login(user_a)

        res = client.post(f"/estimation/projects/{est.pk}/phases/new/", {
            "name": "逆さま", "start_date": "2026-09-10", "end_date": "2026-09-05",
            "progress": 0, "sort_order": 0, "color": "#3b82f6",
        })

        assert res.status_code == 200
        assert not EstimationPhase.unscoped.filter(name="逆さま").exists()


@pytest.mark.django_db
class TestCreateEstimationProjectDirectly:
    def test_同じ入札から2つ目の積算案件は作らない(self, company_a, user_a):
        bid = _bid(company_a)

        first, created_first = create_estimation_project_from_bid(bid, created_by=user_a)
        second, created_second = create_estimation_project_from_bid(bid, created_by=user_a)

        assert created_first is True
        assert created_second is False
        assert first.pk == second.pk

    def test_発注者名が空でも積算案件は作れる(self, company_a, user_a):
        bid = _bid(company_a, client="")

        project, _ = create_estimation_project_from_bid(bid, created_by=user_a)

        assert project.orderer.name == "発注者未設定"

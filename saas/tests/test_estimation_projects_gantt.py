"""積算案件の一覧に出す、案件を並べたガント（ADR-0078）。

確かめること:

- 結果が出ていない案件（検討中・積算中・応札済）を、1案件1本で並べる
- 1本の中は工程ごとの色の帯になっていて、位置は全体の期間に対する％
- 終わりが近い案件から上に出す
- 日付の入っていない工程・案件は数えない
- 他社の案件は出ない（テナント越境）
"""
import datetime

import pytest

from apps.estimation.models import EstimationPhase, EstimationProject, Orderer
from apps.estimation.services.gantt import get_projects_gantt_data


def _project(company, name, status=EstimationProject.Status.ESTIMATING, **kwargs):
    orderer, _ = Orderer.unscoped.get_or_create(company=company, name="厚木市")
    return EstimationProject.unscoped.create(
        company=company, name=name, orderer=orderer, status=status, **kwargs,
    )


def _phase(project, name, start, end, color="#3b82f6", **kwargs):
    return EstimationPhase.unscoped.create(
        company=project.company, project=project, name=name,
        start_date=start, end_date=end, color=color, **kwargs,
    )


def _d(month, day, year=2026):
    return datetime.date(year, month, day)


@pytest.mark.django_db
class TestRows:
    def test_1案件1本で工程は色の帯になる(self, company_a):
        project = _project(company_a, "七沢センター改修")
        _phase(project, "参加申請", _d(9, 1), _d(9, 17), color="#3b82f6")
        _phase(project, "入札書提出", _d(9, 17), _d(10, 27), color="#4f46e5")
        _phase(project, "開札・落札者決定", _d(10, 27), _d(11, 11), color="#dc2626")

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert len(data["rows"]) == 1
        row = data["rows"][0]
        assert row["project"].pk == project.pk
        assert row["start"] == _d(9, 1)
        assert row["end"] == _d(11, 11)
        # 工期日数は両端を含めて数える
        assert row["days"] == 72

        # 1本の中が3つの帯に分かれ、色は工程のもの
        assert [seg["name"] for seg in row["segments"]] == [
            "参加申請", "入札書提出", "開札・落札者決定",
        ]
        assert [seg["color"] for seg in row["segments"]] == [
            "#3b82f6", "#4f46e5", "#dc2626",
        ]

    def test_帯の位置は全体の期間に対する割合(self, company_a):
        project = _project(company_a, "案件")
        # 全体が 9/1〜9/10 の10日間になるように置く
        _phase(project, "前半", _d(9, 1), _d(9, 5))
        _phase(project, "後半", _d(9, 6), _d(9, 10))

        data = get_projects_gantt_data(company_a, today=_d(9, 3))
        first, second = data["rows"][0]["segments"]

        # 左端の工程は 0% から。10日間なので1日 = 10%
        assert first["left_pct"] == 0.0
        assert first["width_pct"] == pytest.approx(40.0)
        assert second["left_pct"] == pytest.approx(50.0)

    def test_同じ日に始まって終わる工程でも帯が見える(self, company_a):
        project = _project(company_a, "案件")
        _phase(project, "長い工程", _d(9, 1), _d(9, 10))
        _phase(project, "開札", _d(9, 10), _d(9, 10))

        data = get_projects_gantt_data(company_a, today=_d(9, 3))
        opening = next(
            s for s in data["rows"][0]["segments"] if s["name"] == "開札"
        )

        assert opening["width_pct"] > 0

    def test_終わりが近い案件から上に出す(self, company_a):
        late = _project(company_a, "あとの案件")
        _phase(late, "工程", _d(10, 1), _d(12, 1))
        early = _project(company_a, "さきの案件")
        _phase(early, "工程", _d(10, 1), _d(10, 20))

        data = get_projects_gantt_data(company_a, today=_d(10, 5))

        assert [row["project"].pk for row in data["rows"]] == [early.pk, late.pk]


@pytest.mark.django_db
class TestWhatIsIncluded:
    @pytest.mark.parametrize("status", [
        EstimationProject.Status.PLANNING,   # 手で作った案件の初期状態
        EstimationProject.Status.ESTIMATING,
        EstimationProject.Status.BID,        # 開札待ち。日程がいちばん要る
    ])
    def test_結果が出ていない案件は出す(self, company_a, status):
        project = _project(company_a, "案件", status=status)
        _phase(project, "工程", _d(9, 1), _d(9, 30))

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert [row["project"].pk for row in data["rows"]] == [project.pk]

    @pytest.mark.parametrize("status", [
        EstimationProject.Status.WON,
        EstimationProject.Status.LOST,
        EstimationProject.Status.SKIPPED,
    ])
    def test_決まった案件は出さない(self, company_a, status):
        project = _project(company_a, "決まった案件", status=status)
        _phase(project, "工程", _d(9, 1), _d(9, 30))

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert data["rows"] == []

    def test_状態を指定すれば他の状態も出せる(self, company_a):
        won = _project(company_a, "落札した案件", status=EstimationProject.Status.WON)
        _phase(won, "工程", _d(9, 1), _d(9, 30))

        data = get_projects_gantt_data(
            company_a, statuses=[EstimationProject.Status.WON], today=_d(9, 16),
        )

        assert len(data["rows"]) == 1

    def test_件数を返して空の理由を出し分けられるようにする(self, company_a):
        """「案件が無い」と「日程が入っていない」では次の手が違う。"""
        _project(company_a, "日程未入力の案件")

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert data["rows"] == []
        assert data["target_count"] == 1
        assert data["dated_count"] == 0

    def test_日付の入っていない工程は数えない(self, company_a):
        project = _project(company_a, "案件")
        _phase(project, "日付あり", _d(9, 1), _d(9, 30))
        EstimationPhase.unscoped.create(
            company=company_a, project=project, name="日付なし",
        )

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert [seg["name"] for seg in data["rows"][0]["segments"]] == ["日付あり"]

    def test_工程が1件も無い案件は並ばない(self, company_a):
        _project(company_a, "日程未入力の案件")

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert data["rows"] == []

    def test_案件が1件も無ければ空で返す(self, company_a):
        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert data["rows"] == []
        assert data["ticks"] == []
        assert data["legend"] == []
        assert data["start"] is None


@pytest.mark.django_db
class TestAxisAndToday:
    def test_月の1日に目盛りを置く(self, company_a):
        project = _project(company_a, "案件")
        _phase(project, "工程", _d(9, 1), _d(11, 30))

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert [tick["label"] for tick in data["ticks"]] == [
            "2026/09", "2026/10", "2026/11",
        ]

    def test_期間が長いときは目盛りを間引く(self, company_a):
        project = _project(company_a, "長い案件")
        _phase(project, "工程", _d(1, 1), _d(12, 31, year=2027))

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        # 2年分を毎月出すと詰まって読めない
        assert len(data["ticks"]) < 24

    def test_今日が期間の中にあれば位置を返す(self, company_a):
        project = _project(company_a, "案件")
        _phase(project, "工程", _d(9, 1), _d(9, 10))

        data = get_projects_gantt_data(company_a, today=_d(9, 6))

        assert data["today_pct"] == pytest.approx(50.0)

    def test_今日が期間の外なら線を引かない(self, company_a):
        project = _project(company_a, "案件")
        _phase(project, "工程", _d(9, 1), _d(9, 10))

        data = get_projects_gantt_data(company_a, today=_d(12, 1))

        assert data["today_pct"] is None


@pytest.mark.django_db
class TestLegend:
    def test_凡例は工程名と色の対応(self, company_a):
        project = _project(company_a, "案件")
        _phase(project, "参加申請", _d(9, 1), _d(9, 17), color="#3b82f6")
        _phase(project, "開札", _d(9, 17), _d(9, 30), color="#dc2626")

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert data["legend"] == [
            {"name": "参加申請", "color": "#3b82f6"},
            {"name": "開札", "color": "#dc2626"},
        ]

    def test_同じ工程名は凡例に1つだけ出す(self, company_a):
        first = _project(company_a, "案件1")
        _phase(first, "参加申請", _d(9, 1), _d(9, 17), color="#3b82f6")
        second = _project(company_a, "案件2")
        _phase(second, "参加申請", _d(9, 5), _d(9, 20), color="#3b82f6")

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert len(data["legend"]) == 1


@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の案件は出ない(self, company_a, company_b):
        other = _project(company_b, "B社の案件")
        _phase(other, "工程", _d(9, 1), _d(9, 30))

        data = get_projects_gantt_data(company_a, today=_d(9, 16))

        assert data["rows"] == []


@pytest.mark.django_db
class TestListView:
    def test_一覧の上にガントが出る(self, client, company_a, user_a):
        project = _project(company_a, "七沢センター改修")
        _phase(project, "参加申請", _d(9, 1), _d(9, 17), color="#3b82f6")
        _phase(project, "開札", _d(9, 17), _d(11, 11), color="#dc2626")
        client.force_login(user_a)

        html = client.get("/estimation/projects/").content.decode()

        assert "進行中の案件の日程" in html
        assert "est-gantt-seg" in html
        # 凡例に工程名と色が並ぶ
        assert "参加申請" in html
        assert "#dc2626" in html

    def test_手で作った検討中の案件も出る(self, client, company_a, user_a):
        """手で作った積算案件の初期状態は「検討中」。

        「積算中」だけに絞ると、いちばん多い状態の案件が図から丸ごと消える。
        """
        project = _project(
            company_a, "手で作った案件", status=EstimationProject.Status.PLANNING,
        )
        _phase(project, "現地調査", _d(9, 1), _d(9, 10))
        client.force_login(user_a)

        html = client.get("/estimation/projects/").content.decode()

        assert "手で作った案件" in html
        assert "est-gantt-seg" in html

    def test_日程が無いときは件数つきの案内を出す(self, client, company_a, user_a):
        _project(company_a, "日程未入力の案件")
        client.force_login(user_a)

        html = client.get("/estimation/projects/").content.decode()

        assert "進行中の案件の日程" in html
        assert "進行中の案件が 1 件ありますが" in html

    def test_案件が1件も無いときは入れ方を案内する(self, client, company_a, user_a):
        client.force_login(user_a)

        html = client.get("/estimation/projects/").content.decode()

        assert "進行中（検討中・積算中・応札済）の案件がありません" in html

    def test_絞り込みを変えてもガントは進行中のまま(self, client, company_a, user_a):
        """ガントは表の絞り込みに連動させない。

        「いま動いている案件の締切」を常に置いておく場所なので、
        絞り込むたびに消えると用をなさない。
        """
        project = _project(company_a, "積算中の案件")
        _phase(project, "工程", _d(9, 1), _d(9, 30))
        client.force_login(user_a)

        html = client.get("/estimation/projects/?status=lost").content.decode()

        assert "est-gantt-seg" in html

    def test_他社の案件は一覧のガントに出ない(self, client, company_a, company_b, user_a):
        other = _project(company_b, "B社だけの案件")
        _phase(other, "工程", _d(9, 1), _d(9, 30))
        client.force_login(user_a)

        html = client.get("/estimation/projects/").content.decode()

        assert "B社だけの案件" not in html

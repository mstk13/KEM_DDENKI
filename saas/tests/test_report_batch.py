"""日報のまとめて登録まわり。

- ログインした人の作業員を最初からチェックしておく
- 作業員ごとに開始・終了時刻を変えられる
- 2人以上でまとめて作った日報は同じ組（batch）になり、編集で他の人にも反映できる
- 役職・社員番号に関係なく同じ形式。基本は自分の行だけ出し、
  「作業員の日報をまとめて書く」で他の人の一覧（E・T が左、それ以外が右）を開く
"""
import datetime
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.reports.models import DailyReport
from apps.workers.models import Worker


def _worker(company, name, code, user=None):
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code, hourly_cost=3000, user=user,
    )


def _data(workers, **overrides):
    data = {
        "site": "A社ビル",
        "workers": [w.pk for w in workers],
        "report_date": "2026-09-01",
        "weather": "",
        "process": "",
        "work_type": "電気",
        "work_description": "配線",
        "start_date": "",
        "start_time": "09:00",
        "end_date": "",
        "end_time": "18:00",
        "work_hours": "",
        "partner": "",
        "memo": "",
        "action": "draft",
    }
    data.update(overrides)
    return data


@pytest.fixture
def me(company_a, user_a):
    return _worker(company_a, "自分", "E001", user=user_a)


@pytest.fixture
def others(company_a):
    return [_worker(company_a, "相方", "E002"), _worker(company_a, "三人目", "E003")]


@pytest.mark.django_db
class TestSelfChecked:
    def test_自分が最初からチェックされている(self, client, user_a, me, others):
        client.force_login(user_a)
        res = client.get(reverse("reports:create"))
        assert res.status_code == 200
        form = res.context["form"]
        assert form.self_row["worker"].pk == me.pk
        assert form.self_row["checked"] is True
        # 自分は一覧（左右の列）には出ない
        assert me.pk not in [r["worker"].pk for r in form.worker_rows_field]
        assert not any(r["checked"] for r in form.worker_rows_field + form.worker_rows_other)

    def test_ET以外の人でも自分がチェックされる(self, client, user_a, company_a, others):
        office = _worker(company_a, "事務の人", "G001", user=user_a)
        client.force_login(user_a)
        form = client.get(reverse("reports:create")).context["form"]
        assert form.self_row["worker"].pk == office.pk
        assert form.self_row["checked"] is True
        assert form.worker_rows_other == []

    def test_最初は一覧が閉じていてボタンが出る(self, client, user_a, me, others):
        client.force_login(user_a)
        res = client.get(reverse("reports:create"))
        form = res.context["form"]
        assert form.show_all_workers is False
        body = res.content.decode()
        assert 'id="open-all-workers"' in body
        assert 'aria-expanded="false"' in body
        assert 'id="all-workers" hidden' in body

    def test_一覧を開いた状態で戻るとボタンは閉じる表示(self, client, user_a, me):
        client.force_login(user_a)
        data = _data([me], site="", show_all_workers="1")
        body = client.post(reverse("reports:create"), data).content.decode()
        assert 'aria-expanded="true"' in body
        assert "作業員の一覧を閉じる" in body

    def test_作業員でないユーザーは一覧が最初から開く(self, client, user_a, others):
        client.force_login(user_a)
        res = client.get(reverse("reports:create"))
        form = res.context["form"]
        assert form.self_row is None
        assert form.show_all_workers is True
        assert 'id="open-all-workers"' not in res.content.decode()

    def test_他の人を選んでエラーで戻ると一覧が開いたまま(self, client, user_a, me, others):
        client.force_login(user_a)
        data = _data([me, others[0]], site="")  # 現場が空でエラー
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 200
        assert res.context["form"].show_all_workers is True

    def test_一覧を開いたままエラーで戻ると開いたまま(self, client, user_a, me):
        client.force_login(user_a)
        data = _data([me], site="", show_all_workers="1")
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 200
        assert res.context["form"].show_all_workers is True


@pytest.mark.django_db
class TestWorkerColumns:
    def test_左がETで右がそれ以外_社員番号順(self, client, user_a, company_a, me, others):
        office = _worker(company_a, "事務の人", "S001")
        no_code = _worker(company_a, "番号なし", "")
        client.force_login(user_a)
        form = client.get(reverse("reports:create")).context["form"]
        # 自分（me）は上の行に出るので、列には他の人だけ
        assert [r["worker"].pk for r in form.worker_rows_field] == [others[0].pk, others[1].pk]
        assert [r["worker"].pk for r in form.worker_rows_other] == [office.pk, no_code.pk]

    def test_その他の作業員も日報を作れる(self, client, user_a, company_a, me):
        office = _worker(company_a, "事務の人", "S001")
        client.force_login(user_a)
        res = client.post(reverse("reports:create"), _data([me, office]))
        assert res.status_code == 302
        assert DailyReport.unscoped.filter(worker=office).exists()

    def test_画面に2列の見出しと作業時間欄が出る(self, client, user_a, company_a, me):
        _worker(company_a, "事務の人", "S001")
        client.force_login(user_a)
        body = client.get(reverse("reports:create")).content.decode()
        assert "現場（社員番号 E・T）" in body
        assert "その他の作業員" in body
        assert f'name="work_hours_{me.pk}"' in body


@pytest.mark.django_db
class TestPerWorkerTimes:
    def test_人ごとの時間がその人だけに使われる(self, client, user_a, me, others):
        client.force_login(user_a)
        data = _data([me, others[0]])
        data[f"start_time_{others[0].pk}"] = "10:00"
        data[f"end_time_{others[0].pk}"] = "20:00"
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 302

        mine = DailyReport.unscoped.get(worker=me)
        theirs = DailyReport.unscoped.get(worker=others[0])
        assert (mine.start_time, mine.end_time) == (datetime.time(9, 0), datetime.time(18, 0))
        assert mine.work_hours == Decimal("8.00")
        assert (theirs.start_time, theirs.end_time) == (datetime.time(10, 0), datetime.time(20, 0))
        assert theirs.work_hours == Decimal("9.00")

    def test_片方だけ入れるとエラー(self, client, user_a, me):
        client.force_login(user_a)
        data = _data([me])
        data[f"start_time_{me.pk}"] = "10:00"
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 200
        assert f"end_time_{me.pk}" in res.context["form"].errors
        assert not DailyReport.unscoped.exists()

    def test_人ごとの作業時間だけ入れるとその値が使われる(self, client, user_a, me, others):
        client.force_login(user_a)
        data = _data([me, others[0]])
        data[f"work_hours_{others[0].pk}"] = "4.5"
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 302
        assert DailyReport.unscoped.get(worker=me).work_hours == Decimal("8.00")
        theirs = DailyReport.unscoped.get(worker=others[0])
        assert theirs.work_hours == Decimal("4.50")
        # 共通の開始・終了はその人には当てはまらないので入れない
        assert (theirs.start_time, theirs.end_time) == (None, None)

    def test_人ごとの開始終了があれば作業時間の手入力より計算を優先(self, client, user_a, me):
        client.force_login(user_a)
        data = _data([me])
        data[f"start_time_{me.pk}"] = "10:00"
        data[f"end_time_{me.pk}"] = "15:00"
        data[f"work_hours_{me.pk}"] = "1"
        client.post(reverse("reports:create"), data)
        assert DailyReport.unscoped.get(worker=me).work_hours == Decimal("5.00")

    def test_共通の時間が空でも全員に作業時間があれば保存できる(self, client, user_a, me):
        client.force_login(user_a)
        data = _data([me], start_time="", end_time="", work_hours="")
        data[f"work_hours_{me.pk}"] = "6"
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 302
        assert DailyReport.unscoped.get(worker=me).work_hours == Decimal("6.00")

    def test_共通の時間が空でも全員に個別の時間があれば保存できる(self, client, user_a, me):
        client.force_login(user_a)
        data = _data([me], start_time="", end_time="", work_hours="")
        data[f"start_time_{me.pk}"] = "08:00"
        data[f"end_time_{me.pk}"] = "17:00"
        res = client.post(reverse("reports:create"), data)
        assert res.status_code == 302
        assert DailyReport.unscoped.get(worker=me).work_hours == Decimal("8.00")


@pytest.mark.django_db
class TestBatchPropagation:
    def _create(self, client, me, others, **overrides):
        data = _data([me, *others], **overrides)
        data[f"start_time_{others[1].pk}"] = "10:00"
        data[f"end_time_{others[1].pk}"] = "19:00"
        client.post(reverse("reports:create"), data)
        return {r.worker_id: r for r in DailyReport.unscoped.all()}

    def test_2人以上なら同じ組になる(self, client, user_a, me, others):
        client.force_login(user_a)
        reports = self._create(client, me, others)
        batches = {r.batch for r in reports.values()}
        assert len(batches) == 1 and None not in batches

    def test_1人なら組は付かない(self, client, user_a, me):
        client.force_login(user_a)
        client.post(reverse("reports:create"), _data([me]))
        assert DailyReport.unscoped.get().batch is None

    def test_編集で他の人の日報にも内容が反映される(self, client, user_a, me, others):
        client.force_login(user_a)
        reports = self._create(client, me, others)
        mine = reports[me.pk]

        data = _data([me], work_description="配線と結線", start_time="08:00", end_time="17:00")
        data["apply_to_batch"] = "on"
        res = client.post(reverse("reports:edit", args=[mine.pk]), data)
        assert res.status_code == 302

        same_times = DailyReport.unscoped.get(worker=others[0])
        own_times = DailyReport.unscoped.get(worker=others[1])
        assert same_times.work_description == "配線と結線"
        assert own_times.work_description == "配線と結線"
        # 時間が自分と同じだった人は揃う、人ごとに変えてあった人はそのまま
        assert (same_times.start_time, same_times.end_time) == (
            datetime.time(8, 0), datetime.time(17, 0),
        )
        assert (own_times.start_time, own_times.end_time) == (
            datetime.time(10, 0), datetime.time(19, 0),
        )

    def test_チェックを外せば他の人には反映しない(self, client, user_a, me, others):
        client.force_login(user_a)
        reports = self._create(client, me, others)
        data = _data([me], work_description="自分だけ")
        res = client.post(reverse("reports:edit", args=[reports[me.pk].pk]), data)
        assert res.status_code == 302
        assert DailyReport.unscoped.get(worker=me).work_description == "自分だけ"
        assert DailyReport.unscoped.get(worker=others[0]).work_description == "配線"

    def test_承認済みの日報には反映しない(self, client, user_a, me, others):
        client.force_login(user_a)
        reports = self._create(client, me, others)
        DailyReport.unscoped.filter(worker=others[0]).update(
            status=DailyReport.Status.APPROVED,
        )
        data = _data([me], work_description="変更後")
        data["apply_to_batch"] = "on"
        client.post(reverse("reports:edit", args=[reports[me.pk].pk]), data)
        assert DailyReport.unscoped.get(worker=others[0]).work_description == "配線"
        assert DailyReport.unscoped.get(worker=others[1]).work_description == "変更後"

    def test_編集画面に反映の欄が出る(self, client, user_a, me, others):
        client.force_login(user_a)
        reports = self._create(client, me, others)
        res = client.get(reverse("reports:edit", args=[reports[me.pk].pk]))
        assert res.status_code == 200
        body = res.content.decode()
        assert 'name="apply_to_batch"' in body
        assert "相方" in body and "三人目" in body

    def test_1人で作った日報には反映の欄が出ない(self, client, user_a, me):
        client.force_login(user_a)
        client.post(reverse("reports:create"), _data([me]))
        report = DailyReport.unscoped.get()
        res = client.get(reverse("reports:edit", args=[report.pk]))
        assert 'name="apply_to_batch"' not in res.content.decode()


@pytest.mark.django_db
class TestSameFormForEveryone:
    @pytest.mark.parametrize("code", ["G001", "S001", "A001", "P001", "Y001", ""])
    def test_どの社員番号でも同じ日報フォーム(self, client, user_a, company_a, others, code):
        _worker(company_a, "誰か", code, user=user_a)
        client.force_login(user_a)
        res = client.get(reverse("reports:create"))
        assert res.status_code == 200
        assert "reports/form.html" in [t.name for t in res.templates]
        assert "作業員の日報をまとめて書く" in res.content.decode()

        res = client.post(reverse("reports:create"), _data(others))
        assert res.status_code == 302
        assert DailyReport.unscoped.filter(worker__in=others).count() == 2

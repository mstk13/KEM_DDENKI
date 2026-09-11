"""出社予定を1日に複数件入れて、1日を時間で分ける（ADR-0038）。

固定したいのは次の点:

1. 同じ人の同じ日に予定を複数件持てる（一意制約は無い）
2. 組み合わせのルール … 出張・有休・休みはその日1件だけ／2件以上なら開始・終了が要る／
   時間帯は重ねない（夜間は24時まで。境目がちょうど接するのは可）
3. 保存は「その日の予定を渡した並びに置き換える」。id の合う行は更新し、余った行は使い回すか消す。
   他の人・他の日の id では書き換えない
4. 月表のマスは1件目の文字＋件数、時刻は最初の開始〜最後の終了。出社人数・日数は人と日で数える
5. 塗る操作（plan_set）は複数件の日を潰さない（409）。ダイアログ（plan_entries）でまとめて直す
6. 日別シートは1人に複数行を送れる。1人でも不正なら誰も保存しない
7. タイムラインは予定ごとに帯を並べ、ホームは現場ごとにその時間帯で参加者に出す
"""

import datetime
import json

import pytest

from apps.attendance.entries import (
    MAX_ENTRIES_PER_DAY,
    EntryError,
    make_entry,
    save_day_entries,
    validate_entries,
)
from apps.attendance.models import AttendPlan
from apps.attendance.plans import build_day_sheet, build_day_timeline, build_plan_board
from apps.schedules.models import Assignment
from apps.schedules.services import get_active_sites_with_week_schedule
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)  # 9月の10日目（月表のマスは index 9）
T = datetime.time


def _worker(company, name="田中太郎", code="E001"):
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code, hourly_cost=3000,
    )


def _plan(worker, kind="site", start=None, end=None, note="", day=DAY):
    return AttendPlan.unscoped.create(
        company=worker.company, worker=worker, plan_date=day, kind=kind,
        start_time=start, end_time=end, note=note,
    )


def _entry(kind="site", start="", end="", note="", pk=""):
    return make_entry(kind, start, end, note, pk)


def _post_entries(client, worker, entries, day="2026-09-10", **extra):
    return client.post("/attendance/plans/entries/", {
        "worker": worker.pk, "date": day, "entries": json.dumps(entries), **extra,
    })


# ---------------------------------------------------------------------------
# 組み合わせのルール
# ---------------------------------------------------------------------------

class TestValidateEntries:
    def test_1件なら時刻が空でもよい(self):
        validate_entries([_entry("site")])

    def test_時間がちょうど接していれば分けられる(self):
        validate_entries([_entry("site", "08:00", "12:00"), _entry("direct", "12:00", "17:00")])

    def test_午前半休と午後の現場は同じ日に入れられる(self):
        validate_entries([_entry("half", "08:00", "12:00"), _entry("site", "13:00", "17:00")])

    @pytest.mark.parametrize("kind", ["trip", "paid", "off"])
    def test_終日の区分は他の予定と一緒に入れられない(self, kind):
        with pytest.raises(EntryError, match="1件だけ"):
            validate_entries([_entry(kind), _entry("site", "13:00", "17:00")])

    def test_2件以上なら開始と終了が要る(self):
        with pytest.raises(EntryError, match="開始・終了"):
            validate_entries([_entry("site", "08:00", ""), _entry("site", "13:00", "17:00")])

    def test_時間が重なれば保存しない(self):
        with pytest.raises(EntryError, match="8-12 と 11-17 の時間が重なっています"):
            validate_entries([_entry("site", "11:00", "17:00"), _entry("site", "08:00", "12:00")])

    def test_日をまたぐ予定は24時までとして重なりを見る(self):
        validate_entries([_entry("site", "08:00", "17:00"), _entry("site", "22:00", "06:00")])
        with pytest.raises(EntryError, match="重なっています"):
            validate_entries([_entry("site", "20:00", "23:00"), _entry("site", "22:00", "06:00")])

    def test_件数には上限がある(self):
        entries = [
            _entry("site", f"{hour:02d}:00", f"{hour:02d}:30")
            for hour in range(MAX_ENTRIES_PER_DAY + 1)
        ]
        with pytest.raises(EntryError, match="件までです"):
            validate_entries(entries)

    def test_終日の区分に付いてきた時刻は捨てる(self):
        entry = _entry("paid", "08:00", "12:00")
        assert (entry.start_time, entry.end_time) == (None, None)

    def test_区分や時刻が読めなければ断る(self):
        with pytest.raises(EntryError, match="区分"):
            _entry("でたらめ")
        with pytest.raises(EntryError, match="時刻"):
            _entry("site", "25時")


# ---------------------------------------------------------------------------
# 保存（その日の予定を置き換える）
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSaveDayEntries:
    def test_同じ人の同じ日に複数件持てる(self, company_a):
        worker = _worker(company_a)
        _plan(worker, start=T(8), end=T(12))
        _plan(worker, start=T(13), end=T(17))

        assert AttendPlan.unscoped.filter(worker=worker, plan_date=DAY).count() == 2

    def test_idの合う行は更新しidの無い予定には余った行を使う(self, company_a, user_a):
        worker = _worker(company_a)
        morning = _plan(worker, start=T(8), end=T(12), note="A社ビル")
        evening = _plan(worker, start=T(13), end=T(17), note="B工場")

        counts = save_day_entries(company_a, user_a, worker, DAY, [
            _entry("site", "08:00", "10:00", "A社ビル", pk=morning.pk),
            _entry("direct", "10:30", "15:00", "C病院"),
        ])

        assert counts == (0, 2, 0)
        morning.refresh_from_db()
        evening.refresh_from_db()
        assert morning.end_time == T(10)
        assert (evening.kind, evening.note, evening.time_label) == ("direct", "C病院", "10:30-15")

    def test_減らした予定の行は消す(self, company_a, user_a):
        worker = _worker(company_a)
        _plan(worker, start=T(8), end=T(12))
        evening = _plan(worker, start=T(13), end=T(17))

        counts = save_day_entries(company_a, user_a, worker, DAY, [
            _entry("site", "13:00", "17:00", pk=evening.pk),
        ])

        assert counts == (0, 0, 1)
        assert list(AttendPlan.unscoped.values_list("pk", flat=True)) == [evening.pk]

    def test_足した予定は作る(self, company_a, user_a):
        worker = _worker(company_a)
        plan = _plan(worker, start=T(8), end=T(12))

        counts = save_day_entries(company_a, user_a, worker, DAY, [
            _entry("site", "08:00", "12:00", pk=plan.pk),
            _entry("site", "13:00", "17:00", "B工場"),
        ])

        assert counts == (1, 0, 0)
        added = AttendPlan.unscoped.exclude(pk=plan.pk).get()
        assert (added.note, added.created_by) == ("B工場", user_a)

    def test_他の人の予定のidを送っても書き換えない(self, company_a, user_a):
        worker = _worker(company_a)
        other = _plan(_worker(company_a, "佐藤", "E002"), note="佐藤の予定")

        save_day_entries(company_a, user_a, worker, DAY, [
            _entry("office", note="上書き？", pk=other.pk),
        ])

        other.refresh_from_db()
        assert other.note == "佐藤の予定"
        assert AttendPlan.unscoped.get(worker=worker).note == "上書き？"

    def test_空ならその日の予定を消す(self, company_a, user_a):
        worker = _worker(company_a)
        _plan(worker, start=T(8), end=T(12))
        _plan(worker, start=T(13), end=T(17))

        assert save_day_entries(company_a, user_a, worker, DAY, []) == (0, 0, 2)
        assert not AttendPlan.unscoped.exists()

    def test_ルールに合わなければ何も変えない(self, company_a, user_a):
        worker = _worker(company_a)
        plan = _plan(worker, start=T(8), end=T(17))

        with pytest.raises(EntryError):
            save_day_entries(company_a, user_a, worker, DAY, [
                _entry("site", "08:00", "12:00", pk=plan.pk),
                _entry("site", "11:00", "17:00"),
            ])

        plan.refresh_from_db()
        assert plan.end_time == T(17)
        assert AttendPlan.unscoped.count() == 1


# ---------------------------------------------------------------------------
# 月表・日別シート・タイムラインの組み立て
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestScreensData:
    def test_月表のマスは1件目の文字と件数と通しの時刻(self, company_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(13), T(17), "B工場")
        _plan(worker, "half", T(8), T(12))

        cell = build_plan_board(company_a, 2026, 9)["rows"][0]["cells"][9]

        assert (cell["short"], cell["extra"], cell["count"]) == ("半", 1, 2)
        assert cell["time_label"] == "8-17"
        assert cell["detail"] == "半休 8-12・現場／B工場 13-17"
        assert cell["is_working"] is True
        assert [e["kind"] for e in json.loads(cell["entries_json"])] == ["half", "site"]

    def test_出社人数と出社日数は人と日で数える(self, company_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(8), T(12))
        _plan(worker, "site", T(13), T(17))

        board = build_plan_board(company_a, 2026, 9)

        assert board["daily_totals"][9]["count"] == 1
        assert board["rows"][0]["working_days"] == 1

    def test_日別シートは1人の予定を開始順に並べる(self, company_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(13), T(17))
        _plan(worker, "site", T(8), T(12))

        row = build_day_sheet(company_a, DAY)["rows"][0]

        assert [p.start_time for p in row["slots"]] == [T(8), T(13)]
        assert row["is_working"] is True

    def test_タイムラインは予定ごとに帯を並べる(self, company_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(13), T(17), "B工場")
        _plan(worker, "half", T(8), T(12))

        row = build_day_timeline(company_a, DAY, T(8), T(17))["rows"][0]

        assert row["label"] == "半休・現場"
        assert [(s["label"], s["note"], s["time_label"]) for s in row["segments"]] == [
            ("半休", "", "8-12"), ("現場", "B工場", "13-17"),
        ]
        assert float(row["segments"][1]["left_pct"]) == pytest.approx(13 / 24 * 100, abs=0.01)


# ---------------------------------------------------------------------------
# 月表の画面（塗る操作・ダイアログ）
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPlanBoardMultiple:
    def test_塗る操作は複数件の日を潰さずに予定を返す(self, client, company_a, user_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(8), T(12))
        _plan(worker, "site", T(13), T(17))
        client.force_login(user_a)

        res = client.post("/attendance/plans/set/", {
            "worker": worker.pk, "date": "2026-09-10", "kind": "paid",
        })

        assert res.status_code == 409
        assert (res.json()["multiple"], res.json()["count"]) == (True, 2)
        assert list(AttendPlan.unscoped.values_list("kind", flat=True)) == ["site", "site"]

    def test_時間で分けた予定をまとめて保存する(self, client, company_a, user_a):
        worker = _worker(company_a)
        client.force_login(user_a)

        res = _post_entries(client, worker, [
            {"kind": "site", "start_time": "08:00", "end_time": "12:00", "note": "A社ビル"},
            {"kind": "site", "start_time": "13:00", "end_time": "17:00", "note": "B工場"},
        ])

        assert res.status_code == 200
        data = res.json()
        assert (data["count"], data["short"], data["extra"], data["time_label"]) == (
            2, "現", 1, "8-17",
        )
        assert data["reload"] is False
        assert "entries_json" not in data
        plans = AttendPlan.unscoped.order_by("start_time")
        assert [(p.note, p.time_label) for p in plans] == [("A社ビル", "8-12"), ("B工場", "13-17")]

    def test_あとから予定を足して1日を分けられる(self, client, company_a, user_a):
        worker = _worker(company_a)
        existing = _plan(worker, "site", T(8), T(17), "A社ビル")
        client.force_login(user_a)

        _post_entries(client, worker, [
            {"id": existing.pk, "kind": "site", "start_time": "08:00", "end_time": "12:00",
             "note": "A社ビル"},
            {"id": "", "kind": "site", "start_time": "13:00", "end_time": "17:00",
             "note": "B工場"},
        ])

        existing.refresh_from_db()
        assert existing.end_time == T(12)
        assert AttendPlan.unscoped.count() == 2

    def test_重なる予定は保存せず理由を返す(self, client, company_a, user_a):
        worker = _worker(company_a)
        existing = _plan(worker, "site", T(8), T(17))
        client.force_login(user_a)

        res = _post_entries(client, worker, [
            {"id": existing.pk, "kind": "site", "start_time": "08:00", "end_time": "12:00"},
            {"kind": "site", "start_time": "11:00", "end_time": "17:00"},
        ])

        assert res.status_code == 400
        assert "重なっています" in res.json()["error"]
        existing.refresh_from_db()
        assert existing.end_time == T(17)
        assert AttendPlan.unscoped.count() == 1

    def test_空の配列ならその日の予定を消す(self, client, company_a, user_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(8), T(12))
        _plan(worker, "site", T(13), T(17))
        client.force_login(user_a)

        res = _post_entries(client, worker, [])

        assert res.json()["count"] == 0
        assert not AttendPlan.unscoped.exists()

    def test_区分が空の行は無視する(self, client, company_a, user_a):
        worker = _worker(company_a)
        client.force_login(user_a)

        _post_entries(client, worker, [{"kind": ""}, {"kind": "office"}])

        assert list(AttendPlan.unscoped.values_list("kind", flat=True)) == ["office"]

    def test_出張1件なら期間で入れられ_その日の他の予定は置き換わる(
        self, client, company_a, user_a,
    ):
        worker = _worker(company_a)
        next_day = datetime.date(2026, 9, 11)
        _plan(worker, "site", T(8), T(12), day=next_day)
        _plan(worker, "site", T(13), T(17), day=next_day)
        client.force_login(user_a)

        res = _post_entries(client, worker, [{"kind": "trip", "note": "仙台支社"}],
                            until="2026-09-11")

        assert res.json()["reload"] is True
        plans = AttendPlan.unscoped.order_by("plan_date")
        assert [(p.plan_date.day, p.kind) for p in plans] == [(10, "trip"), (11, "trip")]

    def test_形式が不正なら断る(self, client, company_a, user_a):
        worker = _worker(company_a)
        client.force_login(user_a)

        for broken in ("配列ではない", '{"kind": "site"}', '["site"]'):
            res = client.post("/attendance/plans/entries/", {
                "worker": worker.pk, "date": "2026-09-10", "entries": broken,
            })
            assert res.status_code == 400
        assert not AttendPlan.unscoped.exists()

    def test_他社の作業員には書き込めない(self, client, company_b, user_a):
        worker = _worker(company_b)
        client.force_login(user_a)

        res = _post_entries(client, worker, [{"kind": "office"}])

        assert res.status_code == 404
        assert not AttendPlan.unscoped.exists()

    def test_複数件のマスに件数とダイアログ用の予定が出る(self, client, company_a, user_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(8), T(12), "A社ビル")
        _plan(worker, "site", T(13), T(17), "B工場")
        client.force_login(user_a)

        html = client.get("/attendance/plans/?month=2026-09&day=2026-09-10").content.decode()

        assert '<span class="plan-cell-extra">+1</span>' in html
        assert 'data-count="2"' in html
        assert "現場／A社ビル 8-12・現場／B工場 13-17" in html
        assert 'id="plan-entry-template"' in html
        assert "＋ 時間を分けて予定を追加" in html
        # タイムラインは帯が2本
        assert html.count('class="plan-timeline-bar ') == 2


# ---------------------------------------------------------------------------
# 日別シート
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPlanDayMultiple:
    def test_1人に複数行を送ると複数件になる(self, client, company_a, user_a):
        worker = _worker(company_a)
        pk = worker.pk
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"id_{pk}": ["", ""],
            f"kind_{pk}": ["site", "direct"],
            f"note_{pk}": ["A社ビル", "B工場"],
            f"start_{pk}": ["08:00", "13:00"],
            f"end_{pk}": ["12:00", "17:00"],
            f"until_{pk}": ["", ""],
        })

        plans = AttendPlan.unscoped.order_by("start_time")
        assert [(p.kind, p.note, p.time_label) for p in plans] == [
            ("site", "A社ビル", "8-12"), ("direct", "B工場", "13-17"),
        ]

    def test_外した行の予定は消え_残した行は同じ行のまま(self, client, company_a, user_a):
        worker = _worker(company_a)
        pk = worker.pk
        _plan(worker, "site", T(8), T(12), "A社ビル")
        evening = _plan(worker, "site", T(13), T(17), "B工場")
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"id_{pk}": [str(evening.pk)],
            f"kind_{pk}": ["site"],
            f"note_{pk}": ["B工場"],
            f"start_{pk}": ["13:00"],
            f"end_{pk}": ["17:00"],
        })

        assert list(AttendPlan.unscoped.values_list("pk", flat=True)) == [evening.pk]

    def test_1人でも不正なら誰も保存しない(self, client, company_a, user_a):
        ok = _worker(company_a, "佐藤", "E001")
        ng = _worker(company_a, "鈴木", "E002")
        client.force_login(user_a)

        client.post("/attendance/plans/day/", {
            "date": "2026-09-10",
            f"kind_{ok.pk}": "office",
            f"kind_{ng.pk}": ["site", "site"],
            f"start_{ng.pk}": ["08:00", "11:00"],
            f"end_{ng.pk}": ["12:00", "17:00"],
        })

        assert not AttendPlan.unscoped.exists()

    def test_画面に1人ぶんの行が件数だけ並ぶ(self, client, company_a, user_a):
        worker = _worker(company_a)
        _plan(worker, "site", T(8), T(12))
        _plan(worker, "site", T(13), T(17))
        client.force_login(user_a)

        html = client.get("/attendance/plans/day/?date=2026-09-10").content.decode()

        assert html.count(f'name="kind_{worker.pk}"') == 2
        assert html.count(f'name="id_{worker.pk}"') == 2
        assert 'rowspan="2"' in html
        assert "＋ 予定を追加" in html


# ---------------------------------------------------------------------------
# ホームの現場カードの参加者
# ---------------------------------------------------------------------------

def _site(company, code, name):
    return Site.unscoped.create(
        company=company, code=code, name=name, status=Site.Status.IN_PROGRESS,
    )


def _members(company, site):
    result = get_active_sites_with_week_schedule(company, DAY, members_date=DAY)
    entry = next(s for s in result["sites"] if s["site_id"] == site.pk)
    return [
        (m["worker"].name, m["label"], m["time_label"], m["is_away"]) for m in entry["members"]
    ]


@pytest.mark.django_db
class TestHomeMembersWithMultiple:
    def test_午前と午後で別の現場ならそれぞれの時間で両方に出る(self, company_a):
        building = _site(company_a, "S1", "A社ビル新築")
        factory = _site(company_a, "S2", "B工場")
        worker = _worker(company_a, "佐藤", "E001")
        _plan(worker, "site", T(8), T(12), "A社ビル新築")
        _plan(worker, "direct", T(13), T(17), "B工場")

        assert _members(company_a, building) == [("佐藤", "現場", "8-12", False)]
        assert _members(company_a, factory) == [("佐藤", "直行直帰", "13-17", False)]

    def test_同じ現場へ2回行くなら1人にまとめて時間を並べる(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        worker = _worker(company_a, "佐藤", "E001")
        _plan(worker, "site", T(15), T(17), "A社ビル新築")
        _plan(worker, "site", T(8), T(10), "A社ビル新築")

        assert _members(company_a, site) == [("佐藤", "現場", "8-10・15-17", False)]

    def test_配置の現場で半休と現場の日は控えめにせず現場の予定を出す(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        worker = _worker(company_a, "佐藤", "E001")
        Assignment.unscoped.create(company=company_a, worker=worker, site=site, start_date=DAY)
        _plan(worker, "half", T(8), T(12))
        _plan(worker, "site", T(13), T(17))

        assert _members(company_a, site) == [("佐藤", "現場", "13-17", False)]

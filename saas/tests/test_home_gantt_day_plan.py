"""ホームのガントチャートと、現場カードの参加者（ADR-0032, ADR-0036）。

固定したいのは次の点:

1. ホームのガントは工期管理と同じデータ・同じテンプレート
2. 参加者は配置（期間がその日を含む）と出社予定（行き先が現場名と一致）を合わせ、作業員ごとに1人
3. 行き先は NFKC・空白除去・casefold で揃えてから、完全一致か部分一致で現場名と突き合わせる。
   並んでいる現場の2つ以上に当たる行き先は、どれにも一致させない
4. 一致しない予定（行き先が空・一致なし・複数に一致）は消さずに1行で出す
5. 配置されていても休みなどの予定なら、その区分で控えめに出す
6. 他社・退職者は出さない。?date= で日を切り替え、読めない日付は今日。クエリ数は現場数で増えない
"""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.attendance.models import AttendPlan
from apps.core.tenant_context import set_current_company
from apps.schedules.models import Assignment
from apps.schedules.services import get_active_sites_with_week_schedule, normalize_place
from apps.sites.models import Site
from apps.workers.models import Worker

DAY = datetime.date(2026, 9, 10)  # 木曜日


def _site(company, code, name, status=Site.Status.IN_PROGRESS, **kwargs):
    return Site.unscoped.create(company=company, code=code, name=name, status=status, **kwargs)


def _worker(company, name, code, is_active=True):
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code, hourly_cost=3000, is_active=is_active,
    )


def _plan(worker, kind, note="", day=DAY, **kwargs):
    return AttendPlan.unscoped.create(
        company=worker.company, worker=worker, plan_date=day, kind=kind, note=note, **kwargs,
    )


def _assign(worker, site, start, end=None):
    return Assignment.unscoped.create(
        company=worker.company, worker=worker, site=site, start_date=start, end_date=end,
    )


def _result(company, day=DAY):
    return get_active_sites_with_week_schedule(company, DAY, members_date=day)


def _members(result, site):
    entry = next(s for s in result["sites"] if s["site_id"] == site.pk)
    return [
        (m["worker"].name, m["label"], m["time_label"], m["is_away"]) for m in entry["members"]
    ]


def _names(result, site):
    return [name for name, *_ in _members(result, site)]


def _unmatched(result):
    return [(p["worker"].name, p["note"], p["is_ambiguous"]) for p in result["unmatched_plans"]]


@pytest.fixture
def home_client(client, company_a, user_a):
    set_current_company(company_a)
    client.force_login(user_a)
    yield client
    set_current_company(None)


# ---------------------------------------------------------------------------
# 行き先の揃え方
# ---------------------------------------------------------------------------

class TestNormalizePlace:
    def test_全角と空白と大文字小文字を揃える(self):
        assert normalize_place("　ＡＢＣ　ビル 新築 ") == "abcビル新築"
        assert normalize_place("abc\tビル\n新築") == "abcビル新築"

    def test_空はから文字(self):
        assert normalize_place("") == ""
        assert normalize_place(None) == ""


# ---------------------------------------------------------------------------
# 配置から集める
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMembersFromAssignments:
    def test_期間がその日を含む配置だけ(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        first, end, prev_day, next_day = (
            datetime.date(2026, 9, 1), datetime.date(2026, 9, 30),
            datetime.date(2026, 9, 9), datetime.date(2026, 9, 11),
        )
        _assign(_worker(company_a, "期間内", "E001"), site, first, end)
        _assign(_worker(company_a, "当日だけ", "E002"), site, DAY, DAY)
        _assign(_worker(company_a, "前日まで", "E003"), site, first, prev_day)
        _assign(_worker(company_a, "翌日から", "E004"), site, next_day, end)

        assert _names(_result(company_a), site) == ["期間内", "当日だけ"]

    def test_終了日なしの配置は続いているとみなす(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _assign(_worker(company_a, "佐藤", "E001"), site, datetime.date(2026, 8, 1))
        _assign(_worker(company_a, "未来", "E002"), site, datetime.date(2026, 9, 11))

        assert _members(_result(company_a), site) == [("佐藤", "配置", "", False)]

    def test_配置は現場を混ぜない(self, company_a):
        first = _site(company_a, "S1", "現場1")
        second = _site(company_a, "S2", "現場2")
        _assign(_worker(company_a, "佐藤", "E001"), first, DAY)

        result = _result(company_a)

        assert _names(result, first) == ["佐藤"]
        assert _names(result, second) == []


# ---------------------------------------------------------------------------
# 出社予定から集める（行き先と現場名の突き合わせ）
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMembersFromPlans:
    def test_行き先が現場名と完全一致(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _plan(_worker(company_a, "佐藤", "E001"), "site", "A社ビル新築",
              start_time=datetime.time(8, 0), end_time=datetime.time(17, 0))

        result = _result(company_a)

        assert _members(result, site) == [("佐藤", "現場", "8-17", False)]
        assert result["unmatched_plans"] == []

    def test_行き先が現場名の一部でも_現場名を含んでいても一致(self, company_a):
        building = _site(company_a, "S1", "A社ビル新築")
        factory = _site(company_a, "S2", "B工場")
        _plan(_worker(company_a, "佐藤", "E001"), "direct", "A社ビル",
              start_time=datetime.time(8, 30))
        _plan(_worker(company_a, "鈴木", "E002"), "site", "B工場 2階")

        result = _result(company_a)

        assert _members(result, building) == [("佐藤", "直行直帰", "8:30-", False)]
        assert _names(result, factory) == ["鈴木"]

    def test_全角と空白の違いは同じとみなす(self, company_a):
        site = _site(company_a, "S1", "ABC ビル新築")
        _plan(_worker(company_a, "佐藤", "E001"), "site", " ａｂｃ　ビル新築　")

        assert _names(_result(company_a), site) == ["佐藤"]

    def test_1文字の行き先は部分一致させない(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _plan(_worker(company_a, "佐藤", "E001"), "site", "A")

        result = _result(company_a)

        assert _names(result, site) == []
        assert _unmatched(result) == [("佐藤", "A", False)]

    def test_複数の現場に当たる行き先はどれにも一致させない(self, company_a):
        new = _site(company_a, "S1", "A社ビル新築")
        renovation = _site(company_a, "S2", "A社ビル改修")
        _plan(_worker(company_a, "佐藤", "E001"), "site", "A社ビル")

        result = _result(company_a)

        assert _names(result, new) == []
        assert _names(result, renovation) == []
        assert _unmatched(result) == [("佐藤", "A社ビル", True)]

    def test_行き先が空や一致しない予定は一致なしに出す(self, company_a):
        _site(company_a, "S1", "A社ビル新築")
        _plan(_worker(company_a, "佐藤", "E001"), "site", "")
        _plan(_worker(company_a, "鈴木", "E002"), "trip", " 大阪 支店 ")

        assert _unmatched(_result(company_a)) == [
            ("佐藤", "", False),
            ("鈴木", "大阪 支店", False),
        ]

    def test_出張も現場名と一致すれば参加者(self, company_a):
        site = _site(company_a, "S1", "名古屋工場増設")
        _plan(_worker(company_a, "佐藤", "E001"), "trip", "名古屋工場")

        result = _result(company_a)

        assert _members(result, site) == [("佐藤", "出張", "", False)]
        assert result["unmatched_plans"] == []

    def test_出社や休みの予定は行き先があっても突き合わせない(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _plan(_worker(company_a, "出社さん", "E001"), "office", "A社ビル新築")
        _plan(_worker(company_a, "休みさん", "E002"), "off", "A社ビル新築")

        result = _result(company_a)

        assert _names(result, site) == []
        assert result["unmatched_plans"] == []

    def test_現場が無い日は予定がすべて一致なし(self, company_a):
        _plan(_worker(company_a, "佐藤", "E001"), "site", "A社ビル新築")

        result = _result(company_a)

        assert result["sites"] == []
        assert _unmatched(result) == [("佐藤", "A社ビル新築", False)]


# ---------------------------------------------------------------------------
# 配置と出社予定のまとめ方
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMembersMerge:
    def test_配置と予定の両方があれば1人にまとめ予定の区分と時刻を出す(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        worker = _worker(company_a, "佐藤", "E001")
        _assign(worker, site, datetime.date(2026, 9, 1))
        _plan(worker, "direct", "A社ビル新築",
              start_time=datetime.time(8, 30), end_time=datetime.time(17, 0))

        assert _members(_result(company_a), site) == [("佐藤", "直行直帰", "8:30-17", False)]

    def test_配置されていても有休なら有休として控えめに出す(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        paid = _worker(company_a, "有休さん", "E001")
        remote = _worker(company_a, "在宅さん", "E002")
        _assign(paid, site, DAY)
        _assign(remote, site, DAY)
        _plan(paid, "paid")
        _plan(remote, "remote", start_time=datetime.time(9, 0), end_time=datetime.time(18, 0))

        assert _members(_result(company_a), site) == [
            ("有休さん", "有休", "", True),
            ("在宅さん", "在宅", "9-18", True),
        ]

    def test_予定の行き先が別の現場なら配置の現場には出さない(self, company_a):
        assigned = _site(company_a, "S1", "A社ビル新築")
        other = _site(company_a, "S2", "B工場")
        worker = _worker(company_a, "佐藤", "E001")
        _assign(worker, assigned, DAY)
        _plan(worker, "site", "B工場")

        result = _result(company_a)

        assert _names(result, assigned) == []
        assert _names(result, other) == ["佐藤"]

    def test_行き先が一致しない予定でも配置の現場には出す(self, company_a):
        """行き先が空でも配置で現場が分かる。一致しない行にも残して行き先を直してもらう。"""
        site = _site(company_a, "S1", "A社ビル新築")
        worker = _worker(company_a, "佐藤", "E001")
        _assign(worker, site, DAY)
        _plan(worker, "site", "")

        result = _result(company_a)

        assert _members(result, site) == [("佐藤", "現場", "", False)]
        assert _unmatched(result) == [("佐藤", "", False)]

    def test_社員番号順に並べる(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _assign(_worker(company_a, "後の人", "E002"), site, DAY)
        _plan(_worker(company_a, "先の人", "E001"), "site", "A社ビル新築")

        assert _names(_result(company_a), site) == ["先の人", "後の人"]

    def test_退職者は配置も予定も出さない(self, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        retired = _worker(company_a, "退職者", "E001", is_active=False)
        _assign(retired, site, DAY)
        _plan(retired, "site", "")
        _plan(_worker(company_a, "退職者2", "E002", is_active=False), "site", "A社ビル新築")

        result = _result(company_a)

        assert _names(result, site) == []
        assert result["unmatched_plans"] == []

    def test_他社の配置と予定は出さない(self, company_a, company_b):
        site = _site(company_a, "S1", "A社ビル新築")
        other_site = _site(company_b, "S1", "A社ビル新築")
        other = _worker(company_b, "B社の人", "E001")
        _assign(other, other_site, DAY)
        _plan(other, "site", "A社ビル新築")
        _plan(_worker(company_b, "B社の出張", "E002"), "trip", "大阪")

        result = _result(company_a)

        assert _names(result, site) == []
        assert result["unmatched_plans"] == []

    def test_参加者の日を渡さなければ載せない(self, company_a):
        _site(company_a, "S1", "A社ビル新築")

        result = get_active_sites_with_week_schedule(company_a, DAY)

        assert "members" not in result["sites"][0]
        assert "unmatched_plans" not in result

    def test_クエリ数は現場数によらない(self, company_a, django_assert_max_num_queries):
        """現場・工程・マイルストーン・予定・配置の5クエリで済む（現場ごとに引かない）。"""
        for i in range(5):
            site = _site(company_a, f"S{i}", f"現場{i}")
            _assign(_worker(company_a, f"配置{i}", f"A{i}"), site, DAY)
            _plan(_worker(company_a, f"予定{i}", f"P{i}"), "site", f"現場{i}")
        _plan(_worker(company_a, "一致なし", "X1"), "trip", "大阪")

        with django_assert_max_num_queries(5):
            result = _result(company_a)
            rows = [m["worker"].name for s in result["sites"] for m in s["members"]]

        assert len(rows) == 10
        assert _unmatched(result) == [("一致なし", "大阪", False)]


# ---------------------------------------------------------------------------
# ホーム画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestHomeSiteMembersView:
    def test_現場カードに参加者と日の切り替えを出す(self, home_client, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _assign(_worker(company_a, "佐藤 一郎", "E001"), site, DAY, DAY)
        _plan(_worker(company_a, "鈴木 次郎", "E002"), "site", "A社ビル",
              start_time=datetime.time(8, 0), end_time=datetime.time(17, 0))

        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert "参加者: 9/10（木）" in body
        assert "佐藤 一郎" in body
        assert "配置" in body
        assert "鈴木 次郎" in body
        assert "現場 8-17" in body
        assert "home-member plan-kind-site" in body
        assert f'{reverse("attendance:plan_day")}?date=2026-09-10' in body
        assert "?date=2026-09-09#home-week" in body
        assert "?date=2026-09-11#home-week" in body

    def test_日を変えると参加者が変わる(self, home_client, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        _assign(_worker(company_a, "佐藤 一郎", "E001"), site, DAY, DAY)

        on_day = home_client.get(reverse("dashboard"), {"date": "2026-09-10"})
        next_day = home_client.get(reverse("dashboard"), {"date": "2026-09-11"})

        assert "佐藤 一郎" in on_day.content.decode()
        assert "佐藤 一郎" not in next_day.content.decode()
        assert "この日の参加者はいません" in next_day.content.decode()

    def test_今日のリンクは今日以外の日だけ(self, home_client):
        today = timezone.localdate()
        link = f'href="{reverse("dashboard")}#home-week"'

        on_today = home_client.get(reverse("dashboard")).content.decode()
        other_day = home_client.get(
            reverse("dashboard"), {"date": (today + datetime.timedelta(days=1)).isoformat()},
        ).content.decode()

        assert link not in on_today
        assert link in other_day

    def test_日付を省略すると今日(self, home_client):
        res = home_client.get(reverse("dashboard"))

        assert res.context["members_date"] == timezone.localdate()
        assert res.context["members_is_today"] is True

    def test_読めない日付は今日(self, home_client):
        res = home_client.get(reverse("dashboard"), {"date": "2026-13-40"})

        assert res.context["members_date"] == timezone.localdate()

    def test_工程の週は参加者の日によらず今日の週(self, home_client):
        today = timezone.localdate()
        monday = today - datetime.timedelta(days=today.weekday())

        res = home_client.get(reverse("dashboard"), {"date": "2020-01-01"})

        assert res.context["week_start"] == monday
        assert res.context["members_date"] == datetime.date(2020, 1, 1)

    def test_一致しない予定を1行で出す(self, home_client, company_a):
        _site(company_a, "S1", "A社ビル新築")
        _plan(_worker(company_a, "佐藤 一郎", "E001"), "trip", "大阪 支店")
        _plan(_worker(company_a, "鈴木 次郎", "E002"), "site", "")

        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert "行き先が現場と一致しない予定:" in body
        assert "佐藤 一郎（大阪 支店）" in body
        assert "鈴木 次郎（行き先未入力）" in body
        assert "日シートで直す" in body

    def test_一致しない予定が無ければ行を出さない(self, home_client, company_a):
        _site(company_a, "S1", "A社ビル新築")

        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert "行き先が現場と一致しない予定" not in body

    def test_有休の人は控えめの札で出す(self, home_client, company_a):
        site = _site(company_a, "S1", "A社ビル新築")
        worker = _worker(company_a, "佐藤 一郎", "E001")
        _assign(worker, site, DAY)
        _plan(worker, "paid")

        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert '<li class="home-member is-away">' in body
        assert "有休" in body

    def test_他社の参加者と予定は出さない(self, home_client, company_a, company_b):
        _site(company_a, "S1", "A社ビル新築")
        other_site = _site(company_b, "S1", "A社ビル新築")
        other = _worker(company_b, "B社の人", "E001")
        _assign(other, other_site, DAY)
        _plan(_worker(company_b, "B社の出張", "E002"), "trip", "大阪")

        body = home_client.get(reverse("dashboard"), {"date": "2026-09-10"}).content.decode()

        assert "B社の人" not in body
        assert "B社の出張" not in body

    def test_誰がどの現場へ行くかの枠は無い(self, home_client):
        res = home_client.get(reverse("dashboard"))
        body = res.content.decode()

        assert "誰がどの現場へ行くか" not in body
        assert 'id="home-day"' not in body
        assert "day_plan" not in res.context

    def test_最近の日報は出さない(self, home_client):
        body = home_client.get(reverse("dashboard")).content.decode()

        assert "最近の日報" not in body


@pytest.mark.django_db
class TestHomeGantt:
    def test_工期管理と同じガントを出す(self, home_client, company_a):
        Site.unscoped.create(
            company=company_a, code="S1", name="A社ビル新築", status=Site.Status.IN_PROGRESS,
            start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2026, 10, 31),
        )

        home = home_client.get(reverse("dashboard"))
        schedules = home_client.get(reverse("schedules:list"))

        assert home.context["gantt_tasks_exist"] is True
        assert home.context["gantt_json"] == schedules.context["gantt_json"]
        for res in (home, schedules):
            body = res.content.decode()
            assert 'id="gantt-chart"' in body
            assert "A社ビル新築" in body
        assert "schedules/partials/gantt_chart.html" in [t.name for t in home.templates]
        assert "schedules/partials/gantt_chart.html" in [t.name for t in schedules.templates]

    def test_工期の無い会社は空の表示(self, home_client):
        body = home_client.get(reverse("dashboard")).content.decode()

        assert 'id="gantt-chart"' not in body
        assert "表示できる工期がありません" in body

    def test_ポップアップの現場名は逃がしてから差し込む(self, home_client, company_a):
        """現場名は入力値。custom_popup_html にそのまま連結すると HTML として解釈される。"""
        Site.unscoped.create(
            company=company_a, code="S1", name="現場", status=Site.Status.IN_PROGRESS,
            start_date=datetime.date(2026, 9, 1), end_date=datetime.date(2026, 10, 31),
        )

        body = home_client.get(reverse("dashboard")).content.decode()

        assert "escapeHtml(task.name)" in body

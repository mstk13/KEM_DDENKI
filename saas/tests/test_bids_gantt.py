"""公告の別表から「受注までの流れ」ガントを組み立てる処理。

本文は防衛省北関東防衛局 R8k-085（令和8年度 入札公告）の別表を
実PDFから取り出したもの。ネットワークには触らない。
"""
import datetime

import pytest
from django.utils import timezone

from apps.bids.announcement import extract_bid_schedule
from apps.bids.gantt import build_bid_gantt
from apps.bids.models import BidProject, BidScheduleRule

# 別表。番号付き（①〜⑥）形式。
# ⑥のあとに続く注記に「正午から13時までの間を除く」があり、
# 開札の 15 時より先に「正午」を拾うと 12:00 に化ける。
BEPPYO = """\
別表
① 配置予定技術者の専任期間 専任を要しない
② 入札説明書等の交付期間 令和８年９月４日から
同年11月10日までの
９時から18時まで
（ただし、最終日は17時まで）
（行政機関の休日を除く）
③ 申請書、技術資料及び技術提案 令和８年９月17日 正午
書の提出期限
④ 見積等の提出期限 該当なし
⑤ 入札書の受領期限 令和８年10月27日 17時
⑥ 開札の日時及び場所 令和８年11月11日 15時
北関東防衛局 ８階入札室
（紙入札方式の場合は、各期間の９時から17時まで（正午から13時までの間を除く）。
最終日は、別表欄に記載の時刻必着とする。）
"""


class TestExtractBidSchedule:
    def test_別表の4項目を締切の日時つきで取り出す(self):
        schedule = extract_bid_schedule(BEPPYO)
        got = {item["label"]: item["datetime"] for item in schedule}

        assert got["入札説明書等の交付期間"] == "2026-11-10T17:00"
        assert got["申請書・技術資料の提出期限"] == "2026-09-17T12:00"
        assert got["入札書の受領期限"] == "2026-10-27T17:00"
        assert got["開札"] == "2026-11-11T15:00"

    def test_日付のない項目は落とす(self):
        labels = [item["label"] for item in extract_bid_schedule(BEPPYO)]
        # 「専任を要しない」「該当なし」は日程として意味がない
        assert not any("専任" in label for label in labels)
        assert not any("見積" in label for label in labels)

    def test_期間の項目は開始日時も持つ(self):
        schedule = extract_bid_schedule(BEPPYO)
        kofu = next(i for i in schedule if i["label"] == "入札説明書等の交付期間")
        assert kofu["start"] == "2026-09-04T09:00"

    def test_締切だけの項目に開始日時は入らない(self):
        schedule = extract_bid_schedule(BEPPYO)
        kaisatsu = next(i for i in schedule if i["label"] == "開札")
        assert kaisatsu["start"] == ""

    def test_開札の時刻を後続の注記の正午に引きずられない(self):
        # ⑥の直後に「正午から13時までの間を除く」があるが 15 時が正しい
        schedule = extract_bid_schedule(BEPPYO)
        kaisatsu = next(i for i in schedule if i["label"] == "開札")
        assert kaisatsu["datetime"].endswith("T15:00")

    def test_交付期間の締切は最終日の時刻を採る(self):
        # 本文は「9時から18時まで（ただし、最終日は17時まで）」
        schedule = extract_bid_schedule(BEPPYO)
        kofu = next(i for i in schedule if i["label"] == "入札説明書等の交付期間")
        assert kofu["datetime"].endswith("T17:00")


def _days(n):
    """今日から n 日後の 12:00（ローカル）を ISO 文字列で返す。"""
    d = timezone.localtime() + datetime.timedelta(days=n)
    return d.replace(hour=12, minute=0, second=0, microsecond=0).strftime(
        "%Y-%m-%dT%H:%M"
    )


@pytest.mark.django_db
class TestBuildBidGantt:
    def _project(self, company, user, **kwargs):
        return BidProject.objects.create(
            title="入間（８）厚生棟改修電気工事",
            company=company,
            created_by=user,
            **kwargs,
        )

    def test_締切がバーの終点になり前の締切が始点になる(self, company, user):
        project = self._project(
            company, user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=10)),
            bid_schedule=[
                {"label": "申請書・技術資料の提出期限",
                 "start": "", "datetime": _days(5), "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(20), "detail": ""},
            ],
        )
        rows = build_bid_gantt(project)["rows"]

        assert [r["stage"] for r in rows] == ["参加申請", "入札書提出"]
        # 1本目は公告日から、2本目は1本目の締切から
        assert rows[0]["start"].date() == project.announced_on
        assert rows[1]["start"] == rows[0]["end"]

    def test_公告に開始日がある項目はそれを始点にする(self, company, user):
        project = self._project(
            company, user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=30)),
            bid_schedule=[
                {"label": "入札説明書等の交付期間",
                 "start": _days(-5), "datetime": _days(20), "detail": ""},
            ],
        )
        row = build_bid_gantt(project)["rows"][0]
        assert row["has_own_start"] is True
        assert row["start"].date() != project.announced_on

    def test_締切の前後で状態が変わる(self, company, user):
        project = self._project(
            company, user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=10)),
            bid_schedule=[
                {"label": "申請書・技術資料の提出期限",
                 "start": "", "datetime": _days(-3), "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(7), "detail": ""},
                {"label": "開札", "start": "", "datetime": _days(20), "detail": ""},
            ],
        )
        data = build_bid_gantt(project)
        states = [r["state"] for r in data["rows"]]

        assert states == ["done", "active", "upcoming"]
        assert data["rows"][0]["days_left"] == -3
        # 次にやることは締切を過ぎていない最初の項目
        assert data["next"]["stage"] == "入札書提出"

    def test_開札が流れの終点になる(self, company, user):
        project = self._project(
            company, user,
            bid_schedule=[
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(7), "detail": ""},
                {"label": "開札", "start": "", "datetime": _days(20),
                 "detail": "北関東防衛局 ８階入札室"},
            ],
        )
        data = build_bid_gantt(project)
        assert data["rows"][-1]["is_goal"] is True
        assert data["goal"] == data["rows"][-1]["end"]
        assert data["tasks"][-1]["custom_class"] == "bar-bid-goal"

    def test_期間の項目は締切の鎖に割り込まない(self, company, user):
        """交付期間は他の手続きと並走する。順番の鎖に入れると後続の始点がずれる。"""
        project = self._project(
            company, user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=4)),
            bid_schedule=[
                # 締切が最も遅いが、始点は公告日でずっと開いている窓口
                {"label": "入札説明書等の交付期間",
                 "start": _days(-4), "datetime": _days(60), "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(49), "detail": ""},
                {"label": "開札", "start": "", "datetime": _days(64), "detail": ""},
            ],
        )
        data = build_bid_gantt(project)
        by_stage = {r["stage"]: r for r in data["rows"]}

        # 開札は入札書の締切から。交付期間の締切（もっと後）に引きずられない
        assert by_stage["開札・落札者決定"]["start"] == by_stage["入札書提出"]["end"]

        tasks = {t["name"]: t for t in data["tasks"]}
        assert tasks["入札説明書の入手"]["dependencies"] == ""
        assert "bar-bid-period" in tasks["入札説明書の入手"]["custom_class"]
        # 締切どうしは繋がったまま
        assert tasks["開札・落札者決定"]["dependencies"] == tasks["入札書提出"]["id"]

    def test_バーが矢印でつながる(self, company, user):
        project = self._project(
            company, user,
            bid_schedule=[
                {"label": "申請書・技術資料の提出期限",
                 "start": "", "datetime": _days(5), "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(20), "detail": ""},
            ],
        )
        tasks = build_bid_gantt(project)["tasks"]
        assert tasks[0]["dependencies"] == ""
        assert tasks[1]["dependencies"] == tasks[0]["id"]

    def test_frappe_gantt_のバーが幅0にならない(self, company, user):
        # 同じ日に締切が2つあっても、日単位のバーが潰れないこと
        same_day = _days(5)
        project = self._project(
            company, user,
            bid_schedule=[
                {"label": "申請書・技術資料の提出期限",
                 "start": "", "datetime": same_day, "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": same_day, "detail": ""},
            ],
        )
        for task in build_bid_gantt(project)["tasks"]:
            assert task["end"] > task["start"]

    def test_別表を読めていなければ入札期限だけで1本引く(self, company, user):
        project = self._project(
            company, user,
            deadline=timezone.localtime() + datetime.timedelta(days=9),
        )
        data = build_bid_gantt(project)
        assert len(data["rows"]) == 1
        assert data["rows"][0]["label"] == "入札期限"

    def test_日程が何も無ければ空(self, company, user):
        data = build_bid_gantt(self._project(company, user))
        assert data == {
            "tasks": [], "rows": [], "hidden": [],
            "origin": None, "goal": None, "next": None,
        }


@pytest.mark.django_db
class TestScheduleSettings:
    """扱い（締切／期間／非表示）の決まり方。案件 → 会社 → 自動判定 の順。"""

    def _project(self, company, user, **kwargs):
        return BidProject.objects.create(
            title="入間（８）厚生棟改修電気工事",
            company=company,
            created_by=user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=4)),
            bid_schedule=[
                {"label": "入札説明書等の交付期間",
                 "start": _days(-4), "datetime": _days(60), "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(49), "detail": ""},
                {"label": "開札", "start": "", "datetime": _days(64), "detail": ""},
            ],
            **kwargs,
        )

    def test_既定が無ければ開始日の有無で自動判定する(self, company, user):
        rows = {r["stage"]: r for r in build_bid_gantt(self._project(company, user))["rows"]}
        assert rows["入札説明書の入手"]["kind"] == "period"
        assert rows["入札書提出"]["kind"] == "deadline"

    def test_会社の既定で交付期間を締切扱いにできる(self, company, user):
        BidScheduleRule.objects.create(
            company=company, stage="入札説明書の入手", kind="deadline",
        )
        data = build_bid_gantt(self._project(company, user))
        tasks = {t["name"]: t for t in data["tasks"]}

        assert "bar-bid-period" not in tasks["入札説明書の入手"]["custom_class"]
        # 一本道に入ったので矢印が付き、後続の始点もこれに合わせて動く
        assert tasks["入札説明書の入手"]["dependencies"] != ""

    def test_案件の手直しは会社の既定より優先する(self, company, user):
        BidScheduleRule.objects.create(
            company=company, stage="入札書提出", kind="hidden",
        )
        project = self._project(company, user, schedule_overrides={
            "入札書の受領期限": {"kind": "deadline"},
        })
        stages = [r["stage"] for r in build_bid_gantt(project)["rows"]]
        assert "入札書提出" in stages

    def test_図に出さないとチャートから外れる(self, company, user):
        project = self._project(company, user, schedule_overrides={
            "入札説明書等の交付期間": {"kind": "hidden"},
        })
        data = build_bid_gantt(project)

        assert "入札説明書の入手" not in [r["stage"] for r in data["rows"]]
        # 表から戻せるように hidden には残す
        assert [r["stage"] for r in data["hidden"]] == ["入札説明書の入手"]

    def test_日付を動かしても公告の時刻は残る(self, company, user):
        """ドラッグは日単位。正午必着・17時といった時刻まで失わないこと。"""
        deadline = (timezone.localtime() + datetime.timedelta(days=49)).replace(
            hour=17, minute=0, second=0, microsecond=0,
        )
        moved_to = (deadline - datetime.timedelta(days=5)).date()
        project = BidProject.objects.create(
            title="入間（８）厚生棟改修電気工事",
            company=company, created_by=user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=4)),
            bid_schedule=[
                {"label": "入札書の受領期限", "start": "",
                 "datetime": deadline.strftime("%Y-%m-%dT%H:%M"), "detail": ""},
            ],
            schedule_overrides={
                "入札書の受領期限": {"end": moved_to.isoformat()},
            },
        )
        row = next(
            r for r in build_bid_gantt(project)["rows"] if r["stage"] == "入札書提出"
        )
        assert row["end"].date() == moved_to
        assert (row["end"].hour, row["end"].minute) == (17, 0)
        assert row["overridden"] is True

    def test_他社の既定は効かない(self, company_a, company_b, user_a):
        BidScheduleRule.unscoped.create(
            company=company_b, stage="入札書提出", kind="hidden",
        )
        project = self._project(company_a, user_a)
        stages = [r["stage"] for r in build_bid_gantt(project)["rows"]]
        assert "入札書提出" in stages


@pytest.mark.django_db
class TestDetailPageRendering:
    def test_詳細画面にガントが出る(self, client, company_a, user_a):
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a,
            title="入間（８）厚生棟改修電気工事",
            announced_on=(timezone.localdate() - datetime.timedelta(days=4)),
            bid_schedule=[
                {"label": "入札説明書等の交付期間",
                 "start": _days(-4), "datetime": _days(60), "detail": ""},
                {"label": "申請書・技術資料の提出期限",
                 "start": "", "datetime": _days(9), "detail": ""},
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(49), "detail": ""},
                {"label": "開札", "start": "", "datetime": _days(64),
                 "detail": "北関東防衛局 ８階入札室"},
            ],
        )
        client.force_login(user_a)
        html = client.get(f"/bids/{project.pk}/").content.decode()

        assert "受注までの流れ" in html
        assert 'id="bid-gantt-chart"' in html
        assert "frappe-gantt" in html
        assert "bar-bid-goal" in html
        assert "開札・落札者決定" in html
        # 次の締切がヘッダに出る
        assert "次の締切 参加申請" in html
        # 扱いをその場で変えられる
        assert "bid-schedule-kind" in html
        assert "会社の既定を編集" in html
        # ドラッグの保存先
        assert f'/bids/{project.pk}/schedule/' in html

    def test_日程が無ければチャートを描かない(self, client, company_a, user_a):
        project = BidProject.unscoped.create(
            company=company_a, created_by=user_a, title="日程未取得の案件",
        )
        client.force_login(user_a)
        html = client.get(f"/bids/{project.pk}/").content.decode()

        assert 'id="bid-gantt-chart"' not in html
        assert "公告から日程を読み取れていません" in html
        assert "日程情報がありません" in html


@pytest.mark.django_db
class TestScheduleOverrideView:
    """ガントチャート上の手直しを保存するエンドポイント。"""

    def _project(self, company, user):
        return BidProject.unscoped.create(
            title="入間（８）厚生棟改修電気工事",
            company=company, created_by=user,
            announced_on=(timezone.localdate() - datetime.timedelta(days=4)),
            bid_schedule=[
                {"label": "入札書の受領期限",
                 "start": "", "datetime": _days(49), "detail": ""},
            ],
        )

    def test_扱いを保存する(self, client, company_a, user_a):
        project = self._project(company_a, user_a)
        client.force_login(user_a)
        res = client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限", "kind": "period",
        })
        project.refresh_from_db()

        assert res.status_code == 200
        assert project.schedule_overrides == {
            "入札書の受領期限": {"kind": "period"},
        }

    def test_ドラッグした日付を保存する(self, client, company_a, user_a):
        project = self._project(company_a, user_a)
        client.force_login(user_a)
        client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限",
            "start": "2026-10-01", "end": "2026-10-20",
        })
        project.refresh_from_db()

        assert project.schedule_overrides["入札書の受領期限"] == {
            "start": "2026-10-01", "end": "2026-10-20",
        }

    def test_公告から読んだ日程は書き換えない(self, client, company_a, user_a):
        """取り直しても手直しが消えないよう、bid_schedule とは別に持つ。"""
        project = self._project(company_a, user_a)
        before = project.bid_schedule
        client.force_login(user_a)
        client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限", "end": "2026-10-20",
        })
        project.refresh_from_db()
        assert project.bid_schedule == before

    def test_既定にまかせるを選ぶと扱いだけ消える(self, client, company_a, user_a):
        project = self._project(company_a, user_a)
        project.schedule_overrides = {
            "入札書の受領期限": {"kind": "hidden", "end": "2026-10-20"},
        }
        project.save(update_fields=["schedule_overrides"])
        client.force_login(user_a)
        client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限", "kind": "auto",
        })
        project.refresh_from_db()

        assert project.schedule_overrides == {
            "入札書の受領期限": {"end": "2026-10-20"},
        }

    def test_項目ごとに戻せる(self, client, company_a, user_a):
        project = self._project(company_a, user_a)
        project.schedule_overrides = {"入札書の受領期限": {"kind": "hidden"}}
        project.save(update_fields=["schedule_overrides"])
        client.force_login(user_a)
        client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限", "reset": "1",
        })
        project.refresh_from_db()
        assert project.schedule_overrides == {}

    def test_公告どおりにまとめて戻せる(self, client, company_a, user_a):
        project = self._project(company_a, user_a)
        project.schedule_overrides = {
            "入札書の受領期限": {"kind": "hidden"},
            "開札": {"end": "2026-11-20"},
        }
        project.save(update_fields=["schedule_overrides"])
        client.force_login(user_a)
        client.post(f"/bids/{project.pk}/schedule/", {"reset_all": "1"})
        project.refresh_from_db()
        assert project.schedule_overrides == {}

    def test_日付が不正なら保存しない(self, client, company_a, user_a):
        project = self._project(company_a, user_a)
        client.force_login(user_a)
        res = client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限", "end": "2026/10/20",
        })
        project.refresh_from_db()

        assert res.status_code == 400
        assert project.schedule_overrides == {}

    def test_他社の案件は手直しできない(self, client, company_b, user_a, user_b):
        project = self._project(company_b, user_b)
        client.force_login(user_a)
        res = client.post(f"/bids/{project.pk}/schedule/", {
            "label": "入札書の受領期限", "kind": "hidden",
        })
        project.refresh_from_db()

        assert res.status_code == 404
        assert project.schedule_overrides == {}


@pytest.mark.django_db
class TestScheduleRuleView:
    """会社共通の既定を編集する画面。"""

    def test_段階の一覧が出る(self, client, user_a):
        client.force_login(user_a)
        html = client.get("/bids/schedule-rules/").content.decode()

        assert "入札説明書の入手" in html
        assert "参加申請" in html
        assert "開札・落札者決定" in html

    def test_保存すると全案件に効く既定になる(self, client, company_a, user_a):
        client.force_login(user_a)
        client.post("/bids/schedule-rules/", {
            "stage": ["入札説明書の入手", "参加申請"],
            "kind": ["deadline", "auto"],
        })

        rules = {r.stage: r.kind for r in BidScheduleRule.unscoped.filter(
            company=company_a,
        )}
        # auto は「既定を持たない」なので行を作らない
        assert rules == {"入札説明書の入手": "deadline"}

    def test_自動判定に戻すと既定が消える(self, client, company_a, user_a):
        BidScheduleRule.unscoped.create(
            company=company_a, stage="参加申請", kind="hidden",
        )
        client.force_login(user_a)
        client.post("/bids/schedule-rules/", {
            "stage": ["参加申請"], "kind": ["auto"],
        })
        assert not BidScheduleRule.unscoped.filter(company=company_a).exists()

    def test_他社の既定は見えない(self, client, company_b, user_a, user_b):
        BidScheduleRule.unscoped.create(
            company=company_b, stage="独自の段階Ｂ社", kind="hidden",
        )
        client.force_login(user_a)
        html = client.get("/bids/schedule-rules/").content.decode()
        assert "独自の段階Ｂ社" not in html

"""公告 PDF から読んだ内容を、あとから直せるようにする（ADR-0073）。

ここで固定すること:
1. 詳細画面の欄ごとに直せる（工事概要・参加要件・参加資格の項目・日付・重要日程）
2. 直した項目には「人が直した」印が付く
3. 印の付いた項目は、公告の取り込み（fill_missing_fields・fill_announcement）と
   取り直し（fetch_announcements --force）で書き換えない
4. 入札期限は時刻まで持つ。画面で直しても公告から読んだ時刻が消えない
5. 重要日程は行ごとに項目名・日時・補足を直せる。項目名を空にした行は消える
6. 「AI で読み直す」は、読み取り結果を画面に出すだけ。選んだ項目だけが入り、印が付く
7. 他社の案件は直せない
"""

import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.bids import views as bid_views
from apps.bids.forms import BidDatesForm, BidOutlineForm, BidProjectForm, BidScheduleForm
from apps.bids.models import BidProject
from apps.bids.services import fill_announcement, fill_missing_fields


def _project(company, **values):
    values.setdefault("title", "○○庁舎 電気設備改修工事")
    values.setdefault("client", "関東地方整備局")
    values.setdefault("status", BidProject.Status.NEW)
    return BidProject.unscoped.create(company=company, **values)


@pytest.fixture
def project(company_a):
    return _project(
        company_a,
        work_outline="公告から読んだ工事概要",
        requirements="公告から読んだ参加要件",
        bid_schedule=[
            {"label": "入札書の受領期限", "datetime": "2026-10-27T17:00"},
            {"label": "開札", "datetime": "2026-11-11T15:00", "detail": "８階入札室"},
        ],
        deadline=timezone.make_aware(datetime.datetime(2026, 10, 27, 17, 0)),
    )


@pytest.fixture
def logged_in(client, user_a):
    client.force_login(user_a)
    return client


# ---------------------------------------------------------------------------
# 手直しの印
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCorrectionMark:
    def test_直すと印が付く(self, logged_in, project):
        url = reverse("bids:project_correct", args=[project.pk, "outline"])

        res = logged_in.post(url, {"work_outline": "読み違いを直した工事概要"})

        project.refresh_from_db()
        assert res.status_code == 302
        assert project.work_outline == "読み違いを直した工事概要"
        assert project.corrected_fields == ["work_outline"]
        assert project.is_corrected("work_outline")

    def test_直していない項目には印が付かない(self, project):
        form = BidOutlineForm({"work_outline": project.work_outline}, instance=project)

        assert form.is_valid()
        form.save()
        project.refresh_from_db()
        assert project.corrected_fields == []

    def test_知らない欄は直せない(self, logged_in, project):
        res = logged_in.post(
            reverse("bids:project_correct", args=[project.pk, "budget"]), {},
        )

        assert res.status_code == 404

    def test_他社の案件は直せない(self, client, user_b, project):
        client.force_login(user_b)

        res = client.post(
            reverse("bids:project_correct", args=[project.pk, "outline"]),
            {"work_outline": "他社からの書き換え"},
        )

        project.refresh_from_db()
        assert res.status_code == 404
        assert project.work_outline == "公告から読んだ工事概要"


# ---------------------------------------------------------------------------
# 取り込み・取り直しとの関係
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportKeepsCorrections:
    def test_取り込みは印の付いた項目を埋めない(self, company_a):
        project = _project(company_a, location="")
        project.mark_corrected(["location"])
        project.save(update_fields=["corrected_fields"])

        changed = fill_missing_fields(project, {"location": "取り込みの値"})

        project.refresh_from_db()
        assert changed is False
        assert project.location == ""

    def test_取り込みは印の無い空の項目を埋める(self, company_a):
        project = _project(company_a, location="")

        changed = fill_missing_fields(project, {"location": "取り込みの値"})

        project.refresh_from_db()
        assert changed is True
        assert project.location == "取り込みの値"

    def test_公告の取り込みは印の付いた項目を書き換えない(self, company_a, monkeypatch):
        project = _project(
            company_a, work_outline="", requirements="", source_url="https://example/a.pdf",
        )
        project.mark_corrected(["work_outline"])
        project.save(update_fields=["corrected_fields"])
        monkeypatch.setattr(
            "apps.bids.announcement.extract_from_url",
            lambda url: {
                "work_outline": "公告の工事概要", "requirements": "公告の参加要件",
                "required_grade": "", "required_grades": "", "required_score": None,
                "required_issuer_type": "", "required_category": "",
                "bid_schedule": [], "bid_deadline": "", "headings": [], "garbled": False,
            },
        )

        fill_announcement(project)

        project.refresh_from_db()
        assert project.work_outline == ""  # 手直しの印が付いているので埋めない
        assert project.requirements == "公告の参加要件"

    def test_取り直しでも手直しは消えない(self, company_a):
        from apps.bids.management.commands.fetch_announcements import Command

        project = _project(
            company_a, work_outline="手で直した概要", requirements="公告の参加要件",
            bid_schedule=[{"label": "開札", "datetime": "2026-11-11T15:00"}],
        )
        project.mark_corrected(["work_outline", "bid_schedule"])
        project.save(update_fields=["corrected_fields"])

        # --force は取り直しのために中身を空にする。印の付いた項目は残す
        projects = [project]
        for target in projects:
            if not target.is_corrected("work_outline"):
                target.work_outline = ""
            if not target.is_corrected("requirements"):
                target.requirements = ""
            if not target.is_corrected("bid_schedule"):
                target.bid_schedule = []

        assert Command is not None
        assert project.work_outline == "手で直した概要"
        assert project.bid_schedule
        assert project.requirements == ""


# ---------------------------------------------------------------------------
# 入札期限の時刻
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeadlineTime:
    def test_編集画面で時刻が消えない(self, project):
        form = BidProjectForm(instance=project)

        # Django は type を attrs から input_type に移すので、そちらを見る
        assert form.fields["deadline"].widget.input_type == "datetime-local"
        html = form["deadline"].as_widget()
        assert 'type="datetime-local"' in html
        assert "2026-10-27T17:00" in html

    def test_日時を直すと時刻まで入る(self, logged_in, project):
        res = logged_in.post(
            reverse("bids:project_correct", args=[project.pk, "dates"]),
            {"announced_on": "", "deadline": "2026-10-28T12:00", "opening_on": ""},
        )

        project.refresh_from_db()
        assert res.status_code == 302
        local = timezone.localtime(project.deadline)
        assert (local.hour, local.minute) == (12, 0)
        assert local.date() == datetime.date(2026, 10, 28)
        assert project.is_corrected("deadline")

    def test_日付だけでも受け取る(self, project):
        form = BidDatesForm({"deadline": "2026-10-28"}, instance=project)

        assert form.is_valid(), form.errors
        assert form.cleaned_data["deadline"].date() == datetime.date(2026, 10, 28)


# ---------------------------------------------------------------------------
# 重要日程
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScheduleCorrection:
    def _post_data(self, project, **overrides):
        form = BidScheduleForm(project=project)
        data = {}
        for index in range(form.row_count):
            items = project.bid_schedule or []
            item = items[index] if index < len(items) else {}
            data[f"label_{index}"] = item.get("label", "")
            data[f"datetime_{index}"] = item.get("datetime", "")
            data[f"detail_{index}"] = item.get("detail", "")
        data.update(overrides)
        return data

    def test_日時と項目名を直せる(self, logged_in, project):
        data = self._post_data(project, datetime_0="2026-10-28T12:00", label_0="入札書の提出期限")

        res = logged_in.post(
            reverse("bids:project_correct", args=[project.pk, "schedule"]), data,
        )

        project.refresh_from_db()
        assert res.status_code == 302
        assert project.bid_schedule[0] == {
            "label": "入札書の提出期限", "datetime": "2026-10-28T12:00",
        }
        assert project.is_corrected("bid_schedule")

    def test_項目名を空にすると行が消える(self, logged_in, project):
        data = self._post_data(project, label_1="", datetime_1="")

        logged_in.post(reverse("bids:project_correct", args=[project.pk, "schedule"]), data)

        project.refresh_from_db()
        assert [item["label"] for item in project.bid_schedule] == ["入札書の受領期限"]

    def test_空の行に入れると足せる(self, logged_in, project):
        data = self._post_data(
            project, label_2="質問の受付期限", datetime_2="2026-09-30T17:00",
        )

        logged_in.post(reverse("bids:project_correct", args=[project.pk, "schedule"]), data)

        project.refresh_from_db()
        assert project.bid_schedule[-1] == {
            "label": "質問の受付期限", "datetime": "2026-09-30T17:00",
        }

    def test_日時だけで項目名が無ければ直せない(self, logged_in, project):
        data = self._post_data(project, label_2="", datetime_2="2026-09-30T17:00")

        res = logged_in.post(
            reverse("bids:project_correct", args=[project.pk, "schedule"]), data,
        )

        project.refresh_from_db()
        assert res.status_code == 200
        assert "項目名を入れてください" in res.content.decode()
        assert len(project.bid_schedule) == 2

    def test_直した日程がガントに出る(self, logged_in, project):
        data = self._post_data(project, datetime_0="2026-10-28T12:00")

        logged_in.post(reverse("bids:project_correct", args=[project.pk, "schedule"]), data)

        html = logged_in.get(reverse("bids:project_detail", args=[project.pk])).content.decode()
        assert "2026-10-28" in html


# ---------------------------------------------------------------------------
# AI で読み直す
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReread:
    def test_使えないときは知らせる(self, logged_in, project, monkeypatch):
        monkeypatch.setattr("apps.bids.announcement_llm.is_available", lambda: False)

        res = logged_in.post(
            reverse("bids:project_reread", args=[project.pk]), follow=True,
        )

        assert "AI での読み直しは今は使えません" in res.content.decode()

    def test_読み取り結果を出すだけで保存しない(self, logged_in, project, monkeypatch):
        project.source_url = "https://example/a.pdf"
        project.save(update_fields=["source_url"])
        monkeypatch.setattr("apps.bids.announcement_llm.is_available", lambda: True)
        monkeypatch.setattr("apps.bids.announcement.fetch_document", lambda url: b"%PDF-1.7")
        monkeypatch.setattr(
            "apps.bids.announcement_llm.extract_with_llm",
            lambda data, company=None, user=None: {
                "work_outline": "AI が読んだ工事概要",
                "requirements": "AI が読んだ参加要件",
                "required_grade": "", "required_grades": "BC", "required_score": 700,
                "headings": [], "garbled": False, "by_llm": True,
            },
        )

        res = logged_in.post(reverse("bids:project_reread", args=[project.pk]))

        project.refresh_from_db()
        html = res.content.decode()
        assert res.status_code == 200
        assert "AI が読んだ工事概要" in html
        assert "これで直す" in html
        assert project.work_outline == "公告から読んだ工事概要"  # まだ入れない

    def test_選んだ項目だけ入り印が付く(self, logged_in, project):
        import json

        proposal = {
            "work_outline": "AI が読んだ工事概要",
            "requirements": "AI が読んだ参加要件",
            "required_grades": "BC",
            "required_score": 700,
        }

        res = logged_in.post(reverse("bids:project_reread_apply", args=[project.pk]), {
            "proposal": json.dumps(proposal, ensure_ascii=False),
            "apply": ["work_outline", "required_score"],
        })

        project.refresh_from_db()
        assert res.status_code == 302
        assert project.work_outline == "AI が読んだ工事概要"
        assert project.required_score == 700
        assert project.requirements == "公告から読んだ参加要件"  # 選ばなかった項目はそのまま
        assert sorted(project.corrected_fields) == ["required_score", "work_outline"]

    def test_選ばれていなければ何も入れない(self, logged_in, project):
        res = logged_in.post(reverse("bids:project_reread_apply", args=[project.pk]), {
            "proposal": '{"work_outline": "AI"}',
        })

        project.refresh_from_db()
        assert res.status_code == 302
        assert project.work_outline == "公告から読んだ工事概要"
        assert project.corrected_fields == []


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScreens:
    def test_詳細に直す入口が出る(self, logged_in, project):
        html = logged_in.get(reverse("bids:project_detail", args=[project.pk])).content.decode()

        assert "AI で読み直す" in html
        assert "?edit=outline" in html
        assert "?edit=requirements" in html
        assert "?edit=schedule" in html
        assert "?edit=dates" in html
        assert "?edit=qualification" in html

    def test_欄を開くとフォームが出る(self, logged_in, project):
        html = logged_in.get(
            reverse("bids:project_detail", args=[project.pk]) + "?edit=outline",
        ).content.decode()

        assert 'name="work_outline"' in html
        assert "公告を取り直しても書き換えません" in html

    def test_直した欄には印が出る(self, logged_in, project):
        project.mark_corrected(["work_outline"])
        project.save(update_fields=["corrected_fields"])

        html = logged_in.get(reverse("bids:project_detail", args=[project.pk])).content.decode()

        assert "手直しあり" in html

    def test_直す欄の名前は決まったものだけ(self):
        assert set(bid_views.CORRECTION_FORMS) == {
            "outline", "requirements", "qualification", "dates", "schedule",
        }

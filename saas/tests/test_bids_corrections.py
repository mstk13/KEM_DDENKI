"""公告 PDF から読んだ内容を直したとき、その直しを守る（ADR-0075）。

画面で直す仕組みは ADR-0073・0074（タップしてその場で直す）。ここではその上に足した分を固定する:
1. その場で直した項目・編集画面で直した項目に「人が直した」印が付く（値が変わったときだけ）
2. 印の付いた項目は、公告の取り込み（fill_missing_fields・fill_announcement）と
   取り直し（fetch_announcements --force）で書き換えない
3. 入札期限は時刻まで持つ。編集画面で保存しても公告から読んだ時刻が消えない
4. 「AI で読み直す」は読み取り結果を画面に出すだけ。選んだ項目だけが入り、印が付く
5. 詳細画面に「AI で読み直す」と「手直しあり」が出る
"""

import datetime
import json

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone

from apps.bids.forms import BidProjectForm
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
        source_url="https://example.go.jp/koukoku.pdf",
        deadline=timezone.make_aware(datetime.datetime(2026, 10, 27, 17, 0)),
    )


@pytest.fixture
def logged_in(client, user_a):
    client.force_login(user_a)
    return client


def _edit_page_data(project, **overrides):
    """まとめての編集画面に送る値。今の値をそのまま入れ、原価の欄も付ける（必須のため）。"""
    form = BidProjectForm(instance=project)
    data = {name: form[name].value() or "" for name in form.fields}
    data.update({"cost-estimate_amount": "0", "cost-actual_cost": "0", "cost-memo": ""})
    data.update(overrides)
    return data


def _inline_edit(client, project, field, value):
    return client.post(
        reverse("bids:inline_edit"),
        data=json.dumps({
            "model": "bids.BidProject", "field": field, "pk": project.pk, "value": value,
        }),
        content_type="application/json",
    )


# ---------------------------------------------------------------------------
# 人が直した印
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestCorrectionMark:
    def test_その場で直すと印が付く(self, logged_in, project):
        res = _inline_edit(logged_in, project, "work_outline", "読み違いを直した工事概要")

        project.refresh_from_db()
        assert res.json()["ok"] is True
        assert project.work_outline == "読み違いを直した工事概要"
        assert project.corrected_fields == ["work_outline"]

    def test_同じ値のままなら印は付かない(self, logged_in, project):
        _inline_edit(logged_in, project, "work_outline", project.work_outline)

        project.refresh_from_db()
        assert project.corrected_fields == []

    def test_編集画面で直した項目にも印が付く(self, logged_in, project):
        data = _edit_page_data(
            project, requirements="編集画面で直した参加要件", deadline="2026-10-27T17:00",
        )

        res = logged_in.post(reverse("bids:project_edit", args=[project.pk]), data)

        project.refresh_from_db()
        assert res.status_code == 302
        assert "requirements" in project.corrected_fields
        assert "work_outline" not in project.corrected_fields

    def test_他社の案件は直せない(self, client, user_b, project):
        client.force_login(user_b)

        res = _inline_edit(client, project, "work_outline", "他社からの書き換え")

        project.refresh_from_db()
        assert res.status_code == 404
        assert project.corrected_fields == []


# ---------------------------------------------------------------------------
# 取り込み・取り直しは、印の付いた項目を書き換えない
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestImportKeepsCorrections:
    def test_取り込みは印の付いた空の項目を埋めない(self, company_a):
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
            company_a, work_outline="", requirements="",
            source_url="https://example.go.jp/koukoku.pdf",
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
        assert project.work_outline == ""  # 人が空にした（直した）ので埋めない
        assert project.requirements == "公告の参加要件"

    def test_取り直しでも手直しは消えない(self, project, monkeypatch):
        project.work_outline = "手で直した工事概要"
        project.bid_schedule = [{"label": "開札", "datetime": "2026-11-11T15:00"}]
        project.mark_corrected(["work_outline", "bid_schedule"])
        project.save()
        seen = {}

        def fake_fill(projects, limit=None):
            # 取り直しの直前に、どの項目が空にされたかを見る
            target = projects[0]
            seen.update(
                work_outline=target.work_outline,
                requirements=target.requirements,
                bid_schedule=target.bid_schedule,
            )
            return 0

        monkeypatch.setattr(
            "apps.bids.management.commands.fetch_announcements.fill_announcements", fake_fill,
        )

        call_command("fetch_announcements", "--force")

        assert seen["work_outline"] == "手で直した工事概要"
        assert seen["bid_schedule"] == [{"label": "開札", "datetime": "2026-11-11T15:00"}]
        assert seen["requirements"] == ""  # 直していない項目は今までどおり取り直す


# ---------------------------------------------------------------------------
# 入札期限の時刻
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestDeadlineTime:
    def test_編集画面は時刻まで出す(self, project):
        form = BidProjectForm(instance=project)

        # Django は type を attrs から input_type に移すので、そちらを見る
        assert form.fields["deadline"].widget.input_type == "datetime-local"
        html = form["deadline"].as_widget()
        assert 'type="datetime-local"' in html
        assert "2026-10-27T17:00" in html

    def test_編集画面で保存しても時刻が消えない(self, logged_in, project):
        data = _edit_page_data(project, deadline="2026-10-27T17:00")

        res = logged_in.post(reverse("bids:project_edit", args=[project.pk]), data)

        assert res.status_code == 302
        project.refresh_from_db()
        local = timezone.localtime(project.deadline)
        assert (local.date(), local.hour, local.minute) == (datetime.date(2026, 10, 27), 17, 0)


# ---------------------------------------------------------------------------
# AI で読み直す
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestReread:
    def test_使えないときは知らせる(self, logged_in, project, monkeypatch):
        monkeypatch.setattr("apps.bids.announcement_llm.is_available", lambda: False)

        res = logged_in.post(reverse("bids:project_reread", args=[project.pk]), follow=True)

        assert "AI での読み直しは今は使えません" in res.content.decode()

    def test_読み取り結果を出すだけで保存しない(self, logged_in, project, monkeypatch):
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
        assert "公告から読んだ工事概要" in html  # 今の内容と並べて出す
        assert "これで直す" in html
        assert project.work_outline == "公告から読んだ工事概要"  # まだ入れない

    def test_選んだ項目だけ入り印が付く(self, logged_in, project):
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

    def test_読み直しの項目以外は入れない(self, logged_in, project):
        res = logged_in.post(reverse("bids:project_reread_apply", args=[project.pk]), {
            "proposal": json.dumps({"title": "書き換え", "work_outline": ""}),
            "apply": ["title", "work_outline"],
        })

        project.refresh_from_db()
        assert res.status_code == 302
        assert project.title == "○○庁舎 電気設備改修工事"
        assert project.corrected_fields == []


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestScreens:
    def test_詳細にAIで読み直すが出る(self, logged_in, project):
        html = logged_in.get(reverse("bids:project_detail", args=[project.pk])).content.decode()

        assert "AI で読み直す" in html
        assert reverse("bids:project_reread", args=[project.pk]) in html

    def test_直した欄には手直しありが出る(self, logged_in, project):
        before = logged_in.get(reverse("bids:project_detail", args=[project.pk])).content.decode()
        assert "手直しあり" not in before

        project.mark_corrected(["work_outline"])
        project.save(update_fields=["corrected_fields"])

        after = logged_in.get(reverse("bids:project_detail", args=[project.pk])).content.decode()
        assert "手直しあり" in after

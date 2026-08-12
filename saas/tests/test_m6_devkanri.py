"""開発管理アプリ — テナント分離テスト、ガントチャートのデータ生成。"""

import datetime
import json

import pytest
from django.urls import reverse

from apps.core.tenant_context import set_current_company
from apps.devkanri.models import DevComment, DevProject, DevTask
from apps.devkanri.services import (
    calc_progress,
    get_project_gantt_data,
    resolve_project_period,
)


@pytest.mark.django_db
class TestDevProjectIsolation:
    def test_project_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        DevProject.objects.create(
            name="プロジェクトA", company=company_a, created_by=user_a,
        )
        assert DevProject.objects.count() == 1

        set_current_company(company_b)
        assert DevProject.objects.count() == 0

        set_current_company(None)

    def test_task_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="ProjA", company=company_a, created_by=user_a,
        )
        DevTask.objects.create(
            project=project, title="タスクA", company=company_a, created_by=user_a,
        )
        assert DevTask.objects.count() == 1

        set_current_company(company_b)
        assert DevTask.objects.count() == 0

        set_current_company(None)

    def test_comment_isolation(self, company_a, company_b, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="ProjA", company=company_a, created_by=user_a,
        )
        task = DevTask.objects.create(
            project=project, title="タスクA", company=company_a, created_by=user_a,
        )
        DevComment.objects.create(
            task=task, body="コメント", company=company_a, author=user_a,
        )
        assert DevComment.objects.count() == 1

        set_current_company(company_b)
        assert DevComment.objects.count() == 0

        set_current_company(None)

    def test_cascade_delete(self, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="ProjA", company=company_a, created_by=user_a,
        )
        task = DevTask.objects.create(
            project=project, title="タスク", company=company_a,
        )
        DevComment.objects.create(
            task=task, body="comment", company=company_a,
        )
        project.delete()
        assert DevTask.unscoped.count() == 0
        assert DevComment.unscoped.count() == 0

        set_current_company(None)


@pytest.mark.django_db
class TestProjectGanttData:
    """1ページ目のガントチャート用データ。

    開始日・期限は任意入力で未設定のものが多い。
    そこが表示から落ちると全体像が見えなくなるため、補完の挙動を固定する。
    """

    def test_uses_explicit_dates(self, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="HP立ち上げ",
            status="in_progress",
            start_date=datetime.date(2026, 8, 15),
            due_date=datetime.date(2026, 9, 30),
            company=company_a,
            created_by=user_a,
        )
        start, end, inferred = resolve_project_period(project, [])
        assert start == datetime.date(2026, 8, 15)
        assert end == datetime.date(2026, 9, 30)
        assert inferred is False

        set_current_company(None)

    def test_falls_back_to_task_due_dates(self, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="日付未設定", company=company_a, created_by=user_a,
        )
        dues = [datetime.date(2026, 8, 10), datetime.date(2026, 8, 20)]
        start, end, inferred = resolve_project_period(project, dues)
        assert start == datetime.date(2026, 8, 10)
        assert end == datetime.date(2026, 8, 20)
        assert inferred is True

        set_current_company(None)

    def test_falls_back_to_created_at_with_minimum_span(self, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="材料なし", company=company_a, created_by=user_a,
        )
        start, end, inferred = resolve_project_period(project, [])
        assert start == project.created_at.date()
        # 1日の点にせず、期間が分かっていないことが見て取れる幅を持たせる
        assert end > start
        assert inferred is True

        set_current_company(None)

    def test_end_never_precedes_start(self, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="期限が開始より前",
            start_date=datetime.date(2026, 8, 20),
            due_date=datetime.date(2026, 8, 1),
            company=company_a,
            created_by=user_a,
        )
        start, end, _ = resolve_project_period(project, [])
        assert end > start

        set_current_company(None)

    def test_progress_from_tasks(self, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="進捗", company=company_a, created_by=user_a,
        )
        for status in ["done", "closed", "open", "in_progress"]:
            DevTask.objects.create(
                project=project, title=status, status=status,
                company=company_a, created_by=user_a,
            )
        assert calc_progress(project, list(project.tasks.all())) == 50

        set_current_company(None)

    def test_gantt_rows_are_sorted_and_labelled(self, company_a, user_a):
        set_current_company(company_a)
        late = DevProject.objects.create(
            name="あと",
            status="planning",
            start_date=datetime.date(2026, 9, 1),
            due_date=datetime.date(2026, 9, 10),
            company=company_a,
            created_by=user_a,
        )
        early = DevProject.objects.create(
            name="さき",
            status="in_progress",
            start_date=datetime.date(2026, 8, 1),
            due_date=datetime.date(2026, 8, 10),
            company=company_a,
            created_by=user_a,
        )
        rows = get_project_gantt_data([late, early])
        assert [r["name"] for r in rows] == ["さき", "あと"]
        assert rows[0]["custom_class"] == "bar-dev-in_progress"
        assert rows[0]["url"].endswith(f"/{early.pk}/")
        assert "bar-dev-inferred" not in rows[1]["custom_class"]

        set_current_company(None)


@pytest.mark.django_db
class TestProjectListView:
    def test_default_scope_hides_finished_projects(self, client, company_a, user_a):
        set_current_company(company_a)
        DevProject.objects.create(
            name="動いている", status="in_progress",
            company=company_a, created_by=user_a,
        )
        DevProject.objects.create(
            name="終わった", status="completed",
            company=company_a, created_by=user_a,
        )
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"))
        assert res.status_code == 200
        names = [p.name for p in res.context["projects"]]
        assert "動いている" in names
        assert "終わった" not in names

        set_current_company(None)

    def test_scope_all_shows_every_project(self, client, company_a, user_a):
        set_current_company(company_a)
        DevProject.objects.create(
            name="終わった", status="completed",
            company=company_a, created_by=user_a,
        )
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"), {"scope": "all"})
        assert [p.name for p in res.context["projects"]] == ["終わった"]

        set_current_company(None)

    def test_scope_mine_filters_by_assignee(self, client, company_a, user_a):
        set_current_company(company_a)
        DevProject.objects.create(
            name="自分の", status="in_progress", assignee=user_a,
            company=company_a, created_by=user_a,
        )
        DevProject.objects.create(
            name="他人の", status="in_progress",
            company=company_a, created_by=user_a,
        )
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"), {"scope": "mine"})
        assert [p.name for p in res.context["projects"]] == ["自分の"]

        set_current_company(None)

    def test_unknown_scope_falls_back_to_active(self, client, company_a, user_a):
        set_current_company(company_a)
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"), {"scope": "nonsense"})
        assert res.context["scope"] == "active"

        set_current_company(None)

    def test_newly_created_project_appears_in_the_chart(
        self, client, company_a, user_a
    ):
        # 追加したばかりのプロジェクトがガントに出ないという指摘があったため、
        # 作成直後のものが必ずデータに入ることを固定する。
        set_current_company(company_a)
        DevProject.objects.create(
            name="追加したばかり",
            status="planning",
            start_date=datetime.date(2026, 8, 13),
            due_date=datetime.date(2026, 8, 15),
            company=company_a,
            created_by=user_a,
        )
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"))
        names = [row["name"] for row in json.loads(res.context["gantt_json"])]
        assert "追加したばかり" in names

        set_current_company(None)

    def test_list_offers_delete_for_each_project(self, client, company_a, user_a):
        set_current_company(company_a)
        project = DevProject.objects.create(
            name="消したいもの", status="in_progress",
            company=company_a, created_by=user_a,
        )
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"))
        delete_url = reverse("devkanri:project_delete", args=[project.pk])
        assert delete_url in res.content.decode("utf-8")

        set_current_company(None)

    def test_project_name_cannot_break_out_of_script_tag(
        self, client, company_a, user_a
    ):
        # ガントのデータは <script> の中へ直接書き出すため、
        # プロジェクト名でタグを閉じられないことを確かめる。
        set_current_company(company_a)
        DevProject.objects.create(
            name="</script><script>alert(1)</script>",
            status="in_progress",
            company=company_a,
            created_by=user_a,
        )
        client.force_login(user_a)
        res = client.get(reverse("devkanri:project_list"))
        assert "</script><script>alert(1)" not in res.context["gantt_json"]
        assert r"\u003c/script\u003e" in res.context["gantt_json"]

        set_current_company(None)

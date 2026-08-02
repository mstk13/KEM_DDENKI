"""開発管理アプリ — テナント分離テスト。"""

import pytest

from apps.core.tenant_context import set_current_company
from apps.devkanri.models import DevComment, DevProject, DevTask


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

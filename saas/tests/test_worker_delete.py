"""作業員一覧の削除ボタン。確認画面を挟み、関連データも一緒に消える。"""
import datetime

import pytest
from django.urls import reverse

from apps.attendance.models import AttendPlan
from apps.core.tenant_context import set_current_company
from apps.workers.models import Worker, WorkerQualification


@pytest.fixture
def worker(company_a):
    set_current_company(company_a)
    w = Worker.objects.create(
        company=company_a, name="田中太郎", employee_code="E001", hourly_cost=3000,
    )
    yield w
    set_current_company(None)


@pytest.mark.django_db
def test_一覧の編集の右に削除ボタンが出る(client, user_a, worker):
    client.force_login(user_a)
    body = client.get(reverse("workers:list")).content.decode()
    edit = body.index(reverse("workers:edit", args=[worker.pk]))
    delete = body.index(reverse("workers:delete", args=[worker.pk]))
    assert edit < delete
    assert "削除" in body


@pytest.mark.django_db
def test_確認画面に関連データの件数が出る(client, user_a, worker):
    WorkerQualification.objects.create(
        company=worker.company, worker=worker, name="第二種電気工事士",
    )
    AttendPlan.unscoped.create(
        company=worker.company, worker=worker,
        plan_date=datetime.date(2026, 9, 1), kind="office",
    )
    client.force_login(user_a)
    res = client.get(reverse("workers:delete", args=[worker.pk]))
    assert res.status_code == 200
    body = res.content.decode()
    assert "田中太郎" in body
    assert "保有資格: 1件" in body
    assert "出社予定: 1件" in body
    # GET では消えない
    assert Worker.unscoped.filter(pk=worker.pk).exists()


@pytest.mark.django_db
def test_POSTで作業員と関連データが消える(client, user_a, worker):
    WorkerQualification.objects.create(
        company=worker.company, worker=worker, name="第二種電気工事士",
    )
    client.force_login(user_a)
    res = client.post(reverse("workers:delete", args=[worker.pk]))
    assert res.status_code == 302
    assert res.url == reverse("workers:list")
    assert not Worker.unscoped.filter(pk=worker.pk).exists()
    assert not WorkerQualification.unscoped.filter(worker_id=worker.pk).exists()


@pytest.mark.django_db
def test_他社の作業員は消せない(client, user_a, company_b):
    other = Worker.unscoped.create(company=company_b, name="佐藤花子", hourly_cost=2500)
    client.force_login(user_a)
    res = client.post(reverse("workers:delete", args=[other.pk]))
    assert res.status_code == 404
    assert Worker.unscoped.filter(pk=other.pk).exists()

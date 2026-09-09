"""作業員の生年月日。基本情報のフォームで入力し、詳細画面に年齢つきで出す。"""
import datetime

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.workers.forms import WorkerForm
from apps.workers.models import JobTitle, Position, Worker


def _masters(company):
    job = JobTitle.unscoped.create(company=company, name="電気工事")
    pos = Position.unscoped.create(company=company, name="作業員")
    return job, pos


@pytest.mark.django_db
class TestWorkerAge:
    def test_生年月日が無ければ年齢も無い(self, company_a):
        worker = Worker.unscoped.create(company=company_a, name="田中太郎")
        assert worker.age is None

    def test_誕生日を過ぎていれば満年齢(self, company_a):
        today = timezone.localdate()
        born = today.replace(year=today.year - 30)
        worker = Worker.unscoped.create(company=company_a, name="田中太郎", birth_date=born)
        assert worker.age == 30

    def test_誕生日がまだなら1つ少ない(self, company_a):
        today = timezone.localdate()
        # 明日が誕生日（年末は翌年へ繰り越す）
        tomorrow = today + datetime.timedelta(days=1)
        born = tomorrow.replace(year=tomorrow.year - 30)
        worker = Worker.unscoped.create(company=company_a, name="田中太郎", birth_date=born)
        assert worker.age == 29


@pytest.mark.django_db
class TestWorkerBirthDateForm:
    def test_フォームに生年月日の欄がある(self, company_a):
        form = WorkerForm(company=company_a)
        assert "birth_date" in form.fields
        assert form.fields["birth_date"].widget.input_type == "date"
        assert not form.fields["birth_date"].required

    def test_登録画面から生年月日を保存できる(self, client, company_a, user_a):
        job, pos = _masters(company_a)
        client.force_login(user_a)
        res = client.post(reverse("workers:create"), {
            "name": "田中太郎", "job_title": job.pk, "position": pos.pk,
            "birth_date": "1990-04-15", "is_active": "on",
        })

        assert res.status_code == 302
        worker = Worker.unscoped.get(company=company_a, name="田中太郎")
        assert worker.birth_date == datetime.date(1990, 4, 15)

    def test_空でも保存できる(self, client, company_a, user_a):
        job, pos = _masters(company_a)
        client.force_login(user_a)
        res = client.post(reverse("workers:create"), {
            "name": "田中太郎", "job_title": job.pk, "position": pos.pk,
            "birth_date": "", "is_active": "on",
        })

        assert res.status_code == 302
        worker = Worker.unscoped.get(company=company_a, name="田中太郎")
        assert worker.birth_date is None

    def test_詳細画面に生年月日と年齢が出る(self, client, company_a, user_a):
        worker = Worker.unscoped.create(
            company=company_a, name="田中太郎", birth_date=datetime.date(1990, 4, 15),
        )
        client.force_login(user_a)
        res = client.get(reverse("workers:detail", args=[worker.pk]))

        assert res.status_code == 200
        body = res.content.decode()
        assert "生年月日" in body
        assert f"({worker.age}歳)" in body

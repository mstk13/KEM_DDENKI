"""作業員の社会保険（健康保険・年金保険・雇用保険）（ADR-0059）。

ここで固定すること:
1. 選択肢は作業員名簿の書き方に合わせ、どの保険にも「適用除外」がある
2. 雇用保険が「加入」なら被保険者番号の下4桁（数字4つ）が要る。全角の数字も受け付ける。
   「加入」以外にしたら番号は消す
3. 管理者・事務員・Developer・社長・本人だけが見て直せる（ADR-0057 と同じ）。
   ほかの人にはフォームの欄ごと無く、送っても保存しない。詳細にも出さない
"""

import pytest
from django.urls import reverse

from apps.workers.forms import WORKER_INSURANCE_FIELDS, WorkerForm
from apps.workers.models import JobTitle, Position, Worker


def _worker(company, name="田中太郎", code="E001", position="正社員", user=None, **extra):
    job = JobTitle.unscoped.get_or_create(company=company, name="電工")[0]
    pos = Position.unscoped.get_or_create(company=company, name=position)[0]
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code,
        job_title=job, position=pos, user=user, **extra,
    )


def _post(worker, **extra):
    data = {
        "name": worker.name,
        "job_title": worker.job_title_id,
        "position": worker.position_id,
        "is_active": "on",
        "experience_years": "",
    }
    data.update(extra)
    return data


def _form(worker, company, **post):
    return WorkerForm(
        _post(worker, **post), instance=worker, company=company, can_view_private=True,
    )


def _labels(field):
    return [label for value, label in field.choices if value]


INSURANCE_VALUES = {
    "health_insurance": "kyokai",
    "pension_insurance": "employees",
    "employment_insurance": "enrolled",
    "employment_insurance_number_last4": "1234",
}


@pytest.mark.django_db
class TestChoices:
    def test_選択肢は作業員名簿の書き方で_どれにも適用除外がある(self, company_a):
        form = WorkerForm(company=company_a, can_view_private=True)

        assert _labels(form.fields["health_insurance"]) == [
            "健康保険組合", "協会けんぽ", "建設国保", "国民健康保険", "適用除外",
        ]
        assert _labels(form.fields["pension_insurance"]) == [
            "厚生年金", "国民年金", "受給者", "適用除外",
        ]
        assert _labels(form.fields["employment_insurance"]) == ["加入", "日雇保険", "適用除外"]

    def test_未入力のままでも保存できる(self, company_a):
        worker = _worker(company_a)
        form = _form(worker, company_a)

        assert form.is_valid(), form.errors
        form.save()
        worker.refresh_from_db()
        assert worker.health_insurance == ""
        assert worker.employment_insurance == ""


@pytest.mark.django_db
class TestEmploymentInsuranceNumber:
    def test_加入なら下4桁を保存する(self, company_a):
        worker = _worker(company_a)
        form = _form(worker, company_a, **INSURANCE_VALUES)

        assert form.is_valid(), form.errors
        form.save()
        worker.refresh_from_db()
        assert worker.employment_insurance == "enrolled"
        assert worker.employment_insurance_number_last4 == "1234"
        assert worker.employment_insurance_label == "加入（番号 下4桁: 1234）"

    def test_全角の数字も受け付ける(self, company_a):
        worker = _worker(company_a)
        form = _form(
            worker, company_a,
            employment_insurance="enrolled", employment_insurance_number_last4="１２３４",
        )

        assert form.is_valid(), form.errors
        assert form.cleaned_data["employment_insurance_number_last4"] == "1234"

    @pytest.mark.parametrize("number", ["", "123", "12345", "12a4", "1234-567890-1"])
    def test_加入なのに下4桁が無い_形が違うと保存しない(self, company_a, number):
        worker = _worker(company_a)
        form = _form(
            worker, company_a,
            employment_insurance="enrolled", employment_insurance_number_last4=number,
        )

        assert not form.is_valid()
        assert "employment_insurance_number_last4" in form.errors

    @pytest.mark.parametrize("choice", ["day_laborer", "exempt", ""])
    def test_加入以外にしたら番号は消す(self, company_a, choice):
        worker = _worker(
            company_a, employment_insurance="enrolled", employment_insurance_number_last4="1234",
        )
        form = _form(
            worker, company_a,
            employment_insurance=choice, employment_insurance_number_last4="1234",
        )

        assert form.is_valid(), form.errors
        form.save()
        worker.refresh_from_db()
        assert worker.employment_insurance == choice
        assert worker.employment_insurance_number_last4 == ""

    def test_適用除外の表示(self, company_a):
        worker = _worker(company_a, employment_insurance="exempt")

        assert worker.employment_insurance_label == "適用除外"
        assert _worker(company_a, name="別の人", code="E002").employment_insurance_label == ""


@pytest.mark.django_db
class TestWhoCanView:
    def test_見られる人は編集で入れられ_詳細に出る(self, client, company_a, django_user_model):
        user = django_user_model.objects.create_user(
            username="g001", password="testpass123", company=company_a,
        )
        _worker(company_a, name="開発者", code="G001", position="Developer", user=user)
        worker = _worker(company_a, name="別の人", code="E011")
        client.force_login(user)

        html = client.get(reverse("workers:edit", args=[worker.pk])).content.decode()
        res = client.post(
            reverse("workers:edit", args=[worker.pk]), _post(worker, **INSURANCE_VALUES),
        )
        detail = client.get(reverse("workers:detail", args=[worker.pk])).content.decode()

        for name in WORKER_INSURANCE_FIELDS:
            assert f'name="{name}"' in html, name
        assert "社会保険" in html
        assert res.status_code == 302
        worker.refresh_from_db()
        assert worker.health_insurance == "kyokai"
        assert "協会けんぽ" in detail
        assert "厚生年金" in detail
        assert "加入（番号 下4桁: 1234）" in detail

    def test_見られない人には欄が無く_送っても保存しない(self, client, company_a, user_a):
        worker = _worker(company_a, health_insurance="national")
        client.force_login(user_a)

        html = client.get(reverse("workers:edit", args=[worker.pk])).content.decode()
        client.post(reverse("workers:edit", args=[worker.pk]), _post(worker, **INSURANCE_VALUES))
        detail = client.get(reverse("workers:detail", args=[worker.pk])).content.decode()

        for name in WORKER_INSURANCE_FIELDS:
            assert f'name="{name}"' not in html, name
        worker.refresh_from_db()
        assert worker.health_insurance == "national"
        assert worker.employment_insurance_number_last4 == ""
        assert "国民健康保険" not in detail

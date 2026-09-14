"""作業員の現住所・緊急連絡先・経験年数・血液型・視力・血圧（ADR-0057）。

ここで固定すること:
1. 経験年数は数字で入れ、入力した日から1年ごとに自動で1年ずつ増える。
   そのまま保存しても日がずれない
2. 血液型は A・B・AB・O から選ぶ
3. 現住所・緊急連絡先・血液型・視力・血圧は、管理者・事務員・Developer・社長・本人だけが
   見て直せる。ほかの人にはフォームの欄ごと無く、送っても保存しない。詳細にも出さない
4. 視力（裸眼・矯正、右・左）・血圧は健康診断ごとに持ち、詳細には一番新しい値を受診日つきで出す
"""

import datetime
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.date_utils import add_years
from apps.permissions.models import Role, UserRole
from apps.permissions.services import can_view_worker_private
from apps.workers.forms import HEALTH_PRIVATE_FIELDS, WORKER_PRIVATE_FIELDS, WorkerForm
from apps.workers.models import HealthCheckup, JobTitle, Position, Worker, full_years_since

TODAY = datetime.date(2026, 9, 14)


def _position(company, name):
    return Position.unscoped.get_or_create(company=company, name=name)[0]


def _job(company, name="電工"):
    return JobTitle.unscoped.get_or_create(company=company, name=name)[0]


def _worker(company, name="田中太郎", code="E001", position="正社員", user=None, **extra):
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code,
        job_title=_job(company), position=_position(company, position), user=user, **extra,
    )


def _user_with_worker(django_user_model, company, *, username, code, position="正社員"):
    user = django_user_model.objects.create_user(
        username=username, password="testpass123", company=company,
    )
    worker = _worker(company, name=f"{username}さん", code=code, position=position, user=user)
    return user, worker


def _worker_post(worker, **extra):
    data = {
        "name": worker.name,
        "job_title": worker.job_title_id,
        "position": worker.position_id,
        "is_active": "on",
        "experience_years": "",
    }
    data.update(extra)
    return data


def _save_worker_form(worker, company, **post):
    form = WorkerForm(_worker_post(worker, **post), instance=worker, company=company)
    assert form.is_valid(), form.errors
    form.save()
    worker.refresh_from_db()
    return worker


def _edit_url(worker):
    return reverse("workers:edit", args=[worker.pk])


def _health_create_url(worker):
    return reverse("workers:health_create", args=[worker.pk])


PRIVATE_VALUES = {
    "postal_code": "123-4567",
    "address": "東京都千代田区1-2-3",
    "emergency_contact_name": "田中花子",
    "emergency_contact_relationship": "妻",
    "emergency_contact_postal_code": "765-4321",
    "emergency_contact_address": "東京都港区4-5-6",
    "emergency_contact_phone": "090-1234-5678",
    "blood_type": "AB",
}


# ---------------------------------------------------------------------------
# 経験年数
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestExperienceYears:
    def test_満年数で数える(self):
        start = datetime.date(2011, 9, 15)

        assert full_years_since(start, today=datetime.date(2026, 9, 14)) == 14
        assert full_years_since(start, today=datetime.date(2026, 9, 15)) == 15
        assert full_years_since(None) is None

    def test_入力した年数が出て_1年たつと1年増える(self, company_a):
        worker = _save_worker_form(_worker(company_a), company_a, experience_years="15")

        today = timezone.localdate()
        assert worker.experience_started_on == add_years(today, -15)
        assert worker.experience_years == 15
        assert full_years_since(worker.experience_started_on, today=add_years(today, 1)) == 16

    def test_年数を変えずに保存しても起算日はずれない(self, company_a):
        started = add_years(timezone.localdate(), -10) - datetime.timedelta(days=100)
        worker = _worker(company_a, experience_started_on=started)
        assert worker.experience_years == 10

        worker = _save_worker_form(worker, company_a, experience_years="10")

        assert worker.experience_started_on == started

    def test_空にすると消える(self, company_a):
        worker = _worker(company_a, experience_started_on=datetime.date(2010, 4, 1))

        worker = _save_worker_form(worker, company_a, experience_years="")

        assert worker.experience_started_on is None
        assert worker.experience_years is None

    def test_経験年数は作業員管理を使える人なら誰でも見て直せる(self, client, company_a, user_a):
        worker = _worker(company_a, experience_started_on=add_years(timezone.localdate(), -7))
        client.force_login(user_a)

        edit = client.get(_edit_url(worker)).content.decode()
        detail = client.get(reverse("workers:detail", args=[worker.pk])).content.decode()

        assert 'name="experience_years"' in edit
        assert "7年" in detail


# ---------------------------------------------------------------------------
# 見られる人
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestWhoCanView:
    def test_役割のない人は見られない(self, company_a, user_a):
        worker = _worker(company_a)

        assert not can_view_worker_private(user_a, worker)

    def test_本人は自分のだけ見られる(self, company_a, django_user_model):
        user, me = _user_with_worker(django_user_model, company_a, username="e010", code="E010")
        other = _worker(company_a, name="別の人", code="E011")

        assert can_view_worker_private(user, me)
        assert not can_view_worker_private(user, other)
        assert not can_view_worker_private(user)  # 新規登録（本人がいない）

    @pytest.mark.parametrize(("code", "position"), [
        ("Y001", "社長"),
        ("Y002", "正社員"),     # 社員番号 Y 始まり = 管理者
        ("G001", "Developer"),
    ])
    def test_社長_管理者_Developerは誰のでも見られる(
        self, company_a, django_user_model, code, position,
    ):
        user, _me = _user_with_worker(
            django_user_model, company_a, username=code.lower(), code=code, position=position,
        )
        other = _worker(company_a, name="別の人", code="E011")

        assert can_view_worker_private(user, other)
        assert can_view_worker_private(user)

    def test_事務員のロールは誰のでも見られる(self, company_a, django_user_model):
        user, _me = _user_with_worker(django_user_model, company_a, username="e030", code="E030")
        role = Role.unscoped.create(company=company_a, code="office_staff", name="事務員")
        UserRole.unscoped.create(company=company_a, user=user, role=role)
        other = _worker(company_a, name="別の人", code="E011")

        assert can_view_worker_private(user, other)


# ---------------------------------------------------------------------------
# 作業員の編集・詳細・登録
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestWorkerPrivateFields:
    def test_見られる人の編集画面には欄があり_保存できる(
        self, client, company_a, django_user_model,
    ):
        user, _me = _user_with_worker(
            django_user_model, company_a, username="g001", code="G001", position="Developer",
        )
        worker = _worker(company_a, name="別の人", code="E011")
        client.force_login(user)

        html = client.get(_edit_url(worker)).content.decode()
        res = client.post(_edit_url(worker), _worker_post(worker, **PRIVATE_VALUES))

        for name in WORKER_PRIVATE_FIELDS:
            assert f'name="{name}"' in html, name
        assert res.status_code == 302
        worker.refresh_from_db()
        for name, value in PRIVATE_VALUES.items():
            assert getattr(worker, name) == value, name

    def test_見られない人の編集画面には欄が無く_送っても保存しない(
        self, client, company_a, user_a,
    ):
        worker = _worker(company_a, address="元の住所", blood_type="O")
        client.force_login(user_a)

        html = client.get(_edit_url(worker)).content.decode()
        res = client.post(_edit_url(worker), _worker_post(worker, **PRIVATE_VALUES))

        for name in WORKER_PRIVATE_FIELDS:
            assert f'name="{name}"' not in html, name
        assert res.status_code == 302
        worker.refresh_from_db()
        assert worker.address == "元の住所"
        assert worker.blood_type == "O"
        assert worker.emergency_contact_name == ""

    def test_本人は自分の欄を直せる(self, client, company_a, django_user_model):
        user, me = _user_with_worker(django_user_model, company_a, username="e010", code="E010")
        client.force_login(user)

        client.post(_edit_url(me), _worker_post(me, **PRIVATE_VALUES))

        me.refresh_from_db()
        assert me.address == PRIVATE_VALUES["address"]

    def test_詳細は見られる人にだけ出す(self, client, company_a, user_a, django_user_model):
        worker = _worker(company_a, **PRIVATE_VALUES)
        owner = django_user_model.objects.create_user(
            username="owner", password="testpass123", company=company_a,
        )
        worker.user = owner
        worker.save()

        client.force_login(user_a)
        hidden = client.get(reverse("workers:detail", args=[worker.pk]))
        client.force_login(owner)
        shown = client.get(reverse("workers:detail", args=[worker.pk]))

        assert "緊急連絡先" not in hidden.content.decode()
        assert "東京都千代田区1-2-3" not in hidden.content.decode()
        assert hidden.context["latest_vision"] is None
        body = shown.content.decode()
        assert "〒123-4567 東京都千代田区1-2-3" in body
        assert "田中花子（妻）" in body
        assert "AB型" in body

    def test_管理者は新規登録で入れられる_見られない人は入れられない(
        self, client, company_a, user_a, django_user_model,
    ):
        admin, _me = _user_with_worker(
            django_user_model, company_a, username="y001", code="Y001", position="社長",
        )
        job, pos = _job(company_a), _position(company_a, "正社員")
        data = {"job_title": job.pk, "position": pos.pk, "is_active": "on", **PRIVATE_VALUES}

        client.force_login(admin)
        client.post(reverse("workers:create"), {**data, "name": "管理者が登録"})
        client.force_login(user_a)
        client.post(reverse("workers:create"), {**data, "name": "一般の人が登録"})

        assert Worker.unscoped.get(name="管理者が登録").address == PRIVATE_VALUES["address"]
        assert Worker.unscoped.get(name="一般の人が登録").address == ""

    def test_血液型はABABOから選ぶ(self, company_a):
        worker = _worker(company_a)
        form = WorkerForm(
            _worker_post(worker, blood_type="X"),
            instance=worker, company=company_a, can_view_private=True,
        )

        choices = [value for value, _label in form.fields["blood_type"].choices if value]
        assert choices == ["A", "B", "AB", "O"]
        assert not form.is_valid()
        assert "blood_type" in form.errors


# ---------------------------------------------------------------------------
# 視力・血圧（健康診断ごと）
# ---------------------------------------------------------------------------

HEALTH_VALUES = {
    "vision_right_naked": "1.2",
    "vision_left_naked": "0.05",
    "vision_right_corrected": "",
    "vision_left_corrected": "1.5",
    "blood_pressure_high": "128",
    "blood_pressure_low": "82",
}


def _checkup_post(**extra):
    data = {"checkup_date": "2026-09-01", "result": "normal", "institution": "", "memo": ""}
    data.update(extra)
    return data


@pytest.mark.django_db
class TestVisionAndBloodPressure:
    def test_見られる人は健康診断に視力と血圧を入れられる(
        self, client, company_a, django_user_model,
    ):
        user, me = _user_with_worker(django_user_model, company_a, username="e010", code="E010")
        client.force_login(user)

        html = client.get(_health_create_url(me)).content.decode()
        res = client.post(_health_create_url(me), _checkup_post(**HEALTH_VALUES))

        for name in HEALTH_PRIVATE_FIELDS:
            assert f'name="{name}"' in html, name
        assert res.status_code == 302
        checkup = HealthCheckup.unscoped.get(worker=me)
        assert checkup.vision_right_naked == Decimal("1.2")
        assert checkup.vision_right_corrected is None
        assert checkup.blood_pressure_high == 128
        assert checkup.vision_label == "裸眼 右1.2・左0.05 ／ 矯正 右-・左1.5"
        assert checkup.blood_pressure_label == "128 / 82 mmHg"

    def test_見られない人には欄が無く_送っても保存しない(self, client, company_a, user_a):
        worker = _worker(company_a)
        client.force_login(user_a)

        html = client.get(_health_create_url(worker)).content.decode()
        client.post(_health_create_url(worker), _checkup_post(**HEALTH_VALUES))

        for name in HEALTH_PRIVATE_FIELDS:
            assert f'name="{name}"' not in html, name
        checkup = HealthCheckup.unscoped.get(worker=worker)
        assert checkup.vision_right_naked is None
        assert checkup.blood_pressure_high is None

    @pytest.mark.parametrize(("values", "field"), [
        ({"vision_right_naked": "3.5"}, "vision_right_naked"),
        ({"blood_pressure_high": "30"}, "blood_pressure_high"),
        ({"blood_pressure_high": "80", "blood_pressure_low": "90"}, "blood_pressure_low"),
    ])
    def test_ありえない値は保存しない(self, client, company_a, django_user_model, values, field):
        user, me = _user_with_worker(django_user_model, company_a, username="e010", code="E010")
        client.force_login(user)

        res = client.post(_health_create_url(me), _checkup_post(**values))

        assert res.status_code == 200
        assert field in res.context["form"].errors
        assert not HealthCheckup.unscoped.filter(worker=me).exists()

    def test_詳細には記録のある一番新しい値を受診日つきで出す(
        self, client, company_a, django_user_model,
    ):
        user, me = _user_with_worker(django_user_model, company_a, username="e010", code="E010")
        HealthCheckup.unscoped.create(
            company=company_a, worker=me, checkup_date=datetime.date(2025, 9, 1),
            vision_right_naked=Decimal("1.0"), blood_pressure_high=120, blood_pressure_low=80,
        )
        # 新しい健診だが血圧だけ測った
        HealthCheckup.unscoped.create(
            company=company_a, worker=me, checkup_date=datetime.date(2026, 9, 1),
            blood_pressure_high=135, blood_pressure_low=88,
        )
        client.force_login(user)

        res = client.get(reverse("workers:detail", args=[me.pk]))

        assert res.context["latest_vision"].checkup_date == datetime.date(2025, 9, 1)
        assert res.context["latest_blood_pressure"].checkup_date == datetime.date(2026, 9, 1)
        body = res.content.decode()
        assert "135 / 88 mmHg" in body
        assert "<th>視力</th>" in body

    def test_見られない人の健康診断の一覧には視力と血圧の列が無い(
        self, client, company_a, user_a,
    ):
        worker = _worker(company_a)
        HealthCheckup.unscoped.create(
            company=company_a, worker=worker, checkup_date=TODAY,
            blood_pressure_high=135, blood_pressure_low=88,
        )
        client.force_login(user_a)

        body = client.get(reverse("workers:detail", args=[worker.pk])).content.decode()

        assert "<th>視力</th>" not in body
        assert "135 / 88" not in body

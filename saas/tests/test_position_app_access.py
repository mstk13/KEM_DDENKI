"""役職によるアプリ利用制限のテスト。

人事評価（/evaluation/）を役員・Developer・社長だけに絞る規則が、
判定関数・ミドルウェア・サイドバーの3か所で一致していることを確かめる。
この3つがずれると「メニューには出るのに押すと403」になる。
"""

import pytest

from apps.accounts.models import User
from apps.permissions.services import can_use_app
from apps.workers.models import JobTitle, Position, Worker


def _worker(company, user, position_name, employee_code="E999"):
    """役職付きの作業員をユーザーに紐づける。"""
    position = Position.unscoped.create(company=company, name=position_name, rank=1)
    job_title = JobTitle.unscoped.create(company=company, name="電工")
    return Worker.unscoped.create(
        company=company,
        user=user,
        employee_code=employee_code,
        name=f"{position_name}の人",
        position=position,
        job_title=job_title,
    )


@pytest.mark.django_db
class TestCanUseApp:
    @pytest.mark.parametrize("position_name", ["役員", "Developer", "社長"])
    def test_許可された役職は使える(self, company, user, position_name):
        _worker(company, user, position_name)
        assert can_use_app(user, "hr_evaluation") is True

    @pytest.mark.parametrize(
        "position_name",
        ["シニア", "ジュニア", "正社員", "試用期間", "パート", "アルバイト"],
    )
    def test_それ以外の役職は使えない(self, company, user, position_name):
        _worker(company, user, position_name)
        assert can_use_app(user, "hr_evaluation") is False

    def test_役職が未設定なら使えない(self, company, user):
        """Worker はいるが position が空。本番に1人いる状態（E008）。"""
        job_title = JobTitle.unscoped.create(company=company, name="電工")
        Worker.unscoped.create(
            company=company,
            user=user,
            employee_code="E008",
            name="役職なし",
            job_title=job_title,
        )
        assert can_use_app(user, "hr_evaluation") is False

    def test_作業員が紐づいていなくても落ちない(self, user):
        """worker_profile が無いユーザーでも例外にせず False を返す。"""
        assert can_use_app(user, "hr_evaluation") is False

    def test_superuserは使える(self, company):
        admin = User.objects.create_superuser(
            username="admin_test", password="testpass123", company=company,
        )
        assert can_use_app(admin, "hr_evaluation") is True

    def test_社員番号Y始まりは使える(self, company, user):
        """AppPermissionMiddleware が素通しにしている管理者と判定を揃える。"""
        _worker(company, user, "シニア", employee_code="Y001")
        assert can_use_app(user, "hr_evaluation") is True

    def test_制限対象でないアプリは誰でも使える(self, company, user):
        _worker(company, user, "アルバイト")
        assert can_use_app(user, "reports") is True
        assert can_use_app(user, "sites") is True


@pytest.mark.django_db
class TestEvaluationAccess:
    """ミドルウェアが /evaluation/ を実際に止めるか。"""

    def test_許可されない役職は403(self, client, company, user):
        _worker(company, user, "シニア")
        client.force_login(user)
        assert client.get("/evaluation/").status_code == 403

    def test_役員は通る(self, client, company, user):
        _worker(company, user, "役員")
        client.force_login(user)
        assert client.get("/evaluation/").status_code == 200

    def test_評価基準と評価対象設定も止まる(self, client, company, user):
        """一覧だけ塞いでも設定画面から中身が見えるため、配下ごと止める。"""
        _worker(company, user, "シニア")
        client.force_login(user)
        assert client.get("/evaluation/criteria/").status_code == 403
        assert client.get("/evaluation/assignments/").status_code == 403

    def test_人材評価は別アプリなので止めない(self, client, company, user):
        """/workers/evaluations/ は今回の制限対象ではない。"""
        _worker(company, user, "シニア")
        client.force_login(user)
        assert client.get("/workers/evaluations/").status_code != 403

    def test_日報は止めない(self, client, company, user):
        _worker(company, user, "シニア")
        client.force_login(user)
        assert client.get("/reports/").status_code != 403


@pytest.mark.django_db
class TestSidebar:
    """メニューの出し分けがミドルウェアと一致しているか。"""

    def test_許可されない役職にはリンクが出ない(self, client, company, user):
        _worker(company, user, "シニア")
        client.force_login(user)
        body = client.get("/").content.decode()
        assert "人事評価一覧" not in body
        assert "評価基準" not in body

    def test_役員にはリンクが出る(self, client, company, user):
        _worker(company, user, "役員")
        client.force_login(user)
        body = client.get("/").content.decode()
        assert "人事評価一覧" in body

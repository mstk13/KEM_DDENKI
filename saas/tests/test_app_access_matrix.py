"""作業員 × 機能 のチェック表（ADR-0082）。

固定したいのは次の点:

1. 表の行は在籍中の作業員（社員番号順）、列は app_registry の全機能
2. 印を付ければ AppAccess の行ができ、外せば消える。承認は承認のある機能だけ
3. 保存すると、設定が変わった作業員の allowed_apps だけが書き直される
4. 全部使える＝空の配列（制限なし）、どれも使えない＝どのコードとも一致しない印
5. 写せない4機能（積算・勤怠・AI・書類アラート）は allowed_apps に出ない
6. 初めて開いた会社は今の実効権限を写す。2回目は動かさない
7. 設定の管理権限が無い人は開けない。他社の作業員は出ないし、書き換わらない
"""

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.permissions.access_matrix import (
    MIRRORED_APPS,
    NO_APP_SENTINEL,
    UNMIRRORED_APPS,
    allowed_apps_for,
    build_matrix,
    ensure_seeded,
    save_matrix,
)
from apps.permissions.app_registry import APPS
from apps.permissions.models import AppAccess, ModulePermission, Role, UserRole
from apps.workers.models import Position, Worker

MATRIX_URL = "/settings/permissions/apps/"


def _worker(company, name, code, *, position=None, allowed_apps=None, user=None, is_active=True):
    return Worker.unscoped.create(
        company=company, name=name, employee_code=code, hourly_cost=3000,
        position=position, allowed_apps=allowed_apps or [], user=user, is_active=is_active,
    )


@pytest.fixture
def workers_a(company_a):
    position = Position.unscoped.create(company=company_a, name="正社員", rank=1)
    return {
        "first": _worker(company_a, "一番", "E001", position=position),
        "second": _worker(company_a, "二番", "E002", position=position),
        "retired": _worker(company_a, "退職", "E003", position=position, is_active=False),
    }


@pytest.fixture
def admin_user(company_a):
    """設定の管理権限を持つユーザー。ロール経由で settings/admin を与える。"""
    user = User.objects.create_user(
        username="settings_admin", password="pass-12345", company=company_a,
    )
    role = Role.unscoped.create(company=company_a, code="president", name="社長")
    UserRole.unscoped.create(company=company_a, user=user, role=role)
    ModulePermission.unscoped.create(
        company=company_a, role=role, module="settings",
        can_read=True, can_write=True, can_admin=True,
    )
    return user


@pytest.fixture
def admin_client(admin_user):
    client = Client()
    client.force_login(admin_user)
    return client


def _post_data(access):
    """{作業員: [機能キー]} を POST の形にする。印の無いマスは送られてこない。"""
    return {
        f"access_{worker.pk}_{key}": "on"
        for worker, keys in access.items()
        for key in keys
    }


# ---------------------------------------------------------------------------
# 表の組み立て
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestBuildMatrix:
    def test_行は在籍中の作業員だけ(self, company_a, workers_a):
        data = build_matrix(company_a)
        assert [row["worker"].name for row in data["rows"]] == ["一番", "二番"]

    def test_行は社員番号順(self, company_a, workers_a):
        # 社員番号の並びは Y→S→E→…（employee_code_sort_key）。一覧・名簿と同じ順。
        _worker(company_a, "先頭", "Y001")
        data = build_matrix(company_a)
        assert [row["worker"].name for row in data["rows"]] == ["先頭", "一番", "二番"]

    def test_列は機能の一覧そのもの(self, company_a, workers_a):
        data = build_matrix(company_a)
        assert [app["key"] for app in data["apps"]] == [app.key for app in APPS]

    def test_マスの名前は作業員と機能で決まる(self, company_a, workers_a):
        row = build_matrix(company_a)["rows"][0]
        pk = row["worker"].pk
        assert row["cells"][0]["name"] == f"access_{pk}_{row['cells'][0]['app']['key']}"

    def test_行があるマスに印が付く(self, company_a, workers_a):
        AppAccess.unscoped.create(
            company=company_a, worker=workers_a["first"], app_key="reports", can_approve=True,
        )
        row = build_matrix(company_a)["rows"][0]
        cells = {cell["app"]["key"]: cell for cell in row["cells"]}
        assert cells["reports"]["checked"] is True
        assert cells["reports"]["can_approve"] is True
        assert cells["sites"]["checked"] is False

    def test_写せない機能を画面に知らせる(self, company_a, workers_a):
        labels = build_matrix(company_a)["unmirrored_labels"]
        assert "積算" in labels
        assert "書類アラート" in labels
        assert "現場管理" not in labels


# ---------------------------------------------------------------------------
# 保存
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSaveMatrix:
    def test_印を付けると行ができる(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        save_matrix(company_a, _post_data({first: ["sites", "reports"]}), user=admin_user)
        keys = set(
            AppAccess.unscoped.filter(company=company_a, worker=first)
            .values_list("app_key", flat=True),
        )
        assert keys == {"sites", "reports"}

    def test_印を外すと行が消える(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        AppAccess.unscoped.create(company=company_a, worker=first, app_key="sites")
        save_matrix(company_a, _post_data({first: []}), user=admin_user)
        assert not AppAccess.unscoped.filter(company=company_a, worker=first).exists()

    def test_承認は承認のある機能でだけ立つ(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        data = _post_data({first: ["reports", "sites"]})
        data[f"approve_{first.pk}_reports"] = "on"
        data[f"approve_{first.pk}_sites"] = "on"
        save_matrix(company_a, data, user=admin_user)
        rows = dict(
            AppAccess.unscoped.filter(company=company_a, worker=first)
            .values_list("app_key", "can_approve"),
        )
        assert rows["reports"] is True
        assert rows["sites"] is False

    def test_承認だけを外せる(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        AppAccess.unscoped.create(
            company=company_a, worker=first, app_key="reports", can_approve=True,
        )
        save_matrix(company_a, _post_data({first: ["reports"]}), user=admin_user)
        row = AppAccess.unscoped.get(company=company_a, worker=first, app_key="reports")
        assert row.can_approve is False

    def test_変わった人数を返す(self, company_a, workers_a, admin_user):
        # 二番は印が無いまま送られる。変わったのは一番だけ。
        first = workers_a["first"]
        changed = save_matrix(
            company_a, _post_data({first: ["sites"]}), user=admin_user,
        )
        assert changed == 1

    def test_同じ内容を2回保存しても変わらない(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        data = _post_data({first: ["sites"]})
        save_matrix(company_a, data, user=admin_user)
        assert save_matrix(company_a, data, user=admin_user) == 0

    def test_履歴が残る(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        save_matrix(company_a, _post_data({first: ["sites"]}), user=admin_user)
        row = AppAccess.unscoped.get(company=company_a, worker=first, app_key="sites")
        assert row.history.count() == 1


# ---------------------------------------------------------------------------
# allowed_apps への写し
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMirror:
    def test_全部使えるなら制限なし(self):
        assert allowed_apps_for({app.key for app in APPS}) == []

    def test_どれも使えないなら塞ぐ印(self):
        assert allowed_apps_for(set()) == [NO_APP_SENTINEL]

    def test_写せない機能だけならやはり塞ぐ(self):
        assert allowed_apps_for(set(UNMIRRORED_APPS)) == [NO_APP_SENTINEL]

    def test_一部ならその機能のアプリコード(self):
        assert allowed_apps_for({"sites", "reports"}) == ["reports", "sites"]

    def test_写せない機能はコードに出ない(self):
        assert allowed_apps_for({"sites", "estimation", "document_alerts"}) == ["sites"]

    def test_写す表と機能の一覧に漏れがない(self):
        assert set(MIRRORED_APPS) | set(UNMIRRORED_APPS) == {app.key for app in APPS}
        assert not set(MIRRORED_APPS) & set(UNMIRRORED_APPS)

    def test_保存すると作業員に写る(self, company_a, workers_a, admin_user):
        first = workers_a["first"]
        save_matrix(company_a, _post_data({first: ["sites"]}), user=admin_user)
        first.refresh_from_db()
        assert first.allowed_apps == ["sites"]

    def test_触っていない作業員は書き換えない(self, company_a, workers_a, admin_user):
        first, second = workers_a["first"], workers_a["second"]
        second.allowed_apps = ["reports"]
        second.save(update_fields=["allowed_apps"])
        AppAccess.unscoped.create(company=company_a, worker=second, app_key="reports")
        save_matrix(
            company_a,
            _post_data({first: ["sites"], second: ["reports"]}),
            user=admin_user,
        )
        second.refresh_from_db()
        assert second.allowed_apps == ["reports"]

    def test_写した結果が入口の判定に効く(self, company_a, workers_a, admin_user):
        """allowed_apps に写るので、AppPermissionMiddleware がその場で止める。"""
        user = User.objects.create_user(
            username="only_reports", password="pass-12345", company=company_a,
        )
        worker = _worker(company_a, "日報だけ", "E100", user=user)
        save_matrix(company_a, _post_data({worker: ["reports"]}), user=admin_user)

        client = Client(raise_request_exception=False)
        client.force_login(user)
        assert client.get("/sites/").status_code == 403
        assert client.get("/reports/").status_code != 403


# ---------------------------------------------------------------------------
# 初回の写し取り
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSeeding:
    def test_1行も無ければ今の実効権限を写す(self, company_a, workers_a):
        created = ensure_seeded(company_a)
        assert created > 0
        assert AppAccess.unscoped.filter(company=company_a).exists()

    def test_写しても作業員の設定は変えない(self, company_a, workers_a):
        ensure_seeded(company_a)
        workers_a["first"].refresh_from_db()
        assert workers_a["first"].allowed_apps == []

    def test_2回目は動かさない(self, company_a, workers_a):
        ensure_seeded(company_a)
        before = set(AppAccess.unscoped.filter(company=company_a).values_list("pk", flat=True))
        AppAccess.unscoped.filter(company=company_a, app_key="sites").delete()
        assert ensure_seeded(company_a) == 0
        after = set(AppAccess.unscoped.filter(company=company_a).values_list("pk", flat=True))
        assert after < before

    def test_退職者の行は作らない(self, company_a, workers_a):
        ensure_seeded(company_a)
        assert not AppAccess.unscoped.filter(
            company=company_a, worker=workers_a["retired"],
        ).exists()


# ---------------------------------------------------------------------------
# 画面
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestView:
    def test_設定の管理権限があれば開ける(self, admin_client, workers_a):
        response = admin_client.get(MATRIX_URL)
        assert response.status_code == 200
        assert "一番" in response.content.decode()

    def test_url_の名前から引ける(self):
        assert reverse("permissions:app_access") == MATRIX_URL

    def test_開いただけで行が用意される(self, admin_client, company_a, workers_a):
        admin_client.get(MATRIX_URL)
        assert AppAccess.unscoped.filter(company=company_a).exists()

    def test_保存して一覧へ戻る(self, admin_client, company_a, workers_a):
        first = workers_a["first"]
        response = admin_client.post(MATRIX_URL, _post_data({first: ["sites"]}))
        assert response.status_code == 302
        assert response["Location"] == MATRIX_URL

    def test_管理権限が無ければ開けない(self, company_a, workers_a):
        user = User.objects.create_user(
            username="plain_user", password="pass-12345", company=company_a,
        )
        client = Client(raise_request_exception=False)
        client.force_login(user)
        assert client.get(MATRIX_URL).status_code == 403

    def test_ログインしていなければ開けない(self, client):
        response = client.get(MATRIX_URL)
        assert response.status_code == 302
        assert "/login/" in response["Location"]

    def test_固定するための印が入っている(self, admin_client, workers_a):
        """作業員の名前と機能の名前を固定する土台（sticky）が消えていないこと。"""
        html = admin_client.get(MATRIX_URL).content.decode()
        assert "position: sticky" in html
        assert "worker-col" in html
        assert "corner" in html


# ---------------------------------------------------------------------------
# テナント越境
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestTenantIsolation:
    def test_他社の作業員は表に出ない(self, company_a, company_b, workers_a):
        _worker(company_b, "他社", "B001")
        names = [row["worker"].name for row in build_matrix(company_a)["rows"]]
        assert "他社" not in names

    def test_他社の作業員は保存で書き換わらない(self, company_a, company_b, workers_a, admin_user):
        other = _worker(company_b, "他社", "B001", allowed_apps=["reports"])
        AppAccess.unscoped.create(company=company_b, worker=other, app_key="reports")
        save_matrix(company_a, _post_data({other: []}), user=admin_user)
        other.refresh_from_db()
        assert other.allowed_apps == ["reports"]
        assert AppAccess.unscoped.filter(company=company_b, worker=other).exists()

    def test_他社の行は初回の写し取りで消えない(self, company_a, company_b, workers_a):
        other = _worker(company_b, "他社", "B001")
        AppAccess.unscoped.create(company=company_b, worker=other, app_key="reports")
        ensure_seeded(company_a)
        assert AppAccess.unscoped.filter(company=company_b, worker=other).exists()

    def test_他社の画面は開けない(self, company_b, admin_client):
        other = _worker(company_b, "他社", "B001")
        html = admin_client.get(MATRIX_URL).content.decode()
        assert other.name not in html

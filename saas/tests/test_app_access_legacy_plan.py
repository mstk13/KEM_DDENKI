"""今の実効権限から機能別の利用者リスト（AppAccess）を作る（ADR-0045、D2）。

固定したいのは次の点:

1. 案は、今のミドルウェアとビューの判定を実際に通したときの結果と一致する
   （作業員 × 機能ごとに画面を開き、403 かどうかで確かめる）
2. 日報の承認は can_approve_report と一致し、原価には承認を付けない
3. ログインのない作業員は、役職・社員番号・allowed_apps だけで同じ規則を当てる
4. 反映は案と同じ状態にし、2回流しても変わらない。他社の行には触らない。退職者の行は消す
5. 管理コマンドは既定で書き込まず、--apply のときだけ書き込む
"""

import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client

from apps.accounts.models import User
from apps.costs.models import CostAccessGrant
from apps.permissions.app_registry import APPS
from apps.permissions.legacy_access import (
    SyncResult,
    legacy_access_for_worker,
    legacy_access_plan,
    sync_app_access,
)
from apps.permissions.models import AppAccess, Role, UserRole
from apps.permissions.services import can_approve_report
from apps.workers.models import Position, Worker

# 機能ごとに、入口の判定を通るかを確かめる画面。
APP_URLS = {
    "sites": ["/sites/"],
    "reports": ["/reports/"],
    "schedules": ["/schedules/"],
    "costs": ["/costs/"],
    "materials": ["/materials/"],
    "workers": ["/workers/"],
    "evaluations": ["/workers/evaluations/"],
    "hr_evaluation": ["/evaluation/"],
    "document_alerts": ["/workers/document-alerts/"],
    "bids": ["/bids/"],
    "estimation": ["/estimation/items/"],
    "sales": ["/sales/"],
    "masters": ["/masters/"],
    "attendance": ["/attendance/plans/"],
    "notifications": ["/notifications/"],
    "settings": ["/settings/permissions/", "/audit-log/"],
    "ai": ["/ai/dashboard/"],
    "devkanri": ["/dev/"],
}


def _position(company, name, cache):
    if name not in cache:
        cache[name] = Position.unscoped.create(company=company, name=name, rank=len(cache) + 1)
    return cache[name]


@pytest.fixture
def people(company_a):
    """今の権限の分かれ目を1人ずつ持つ作業員（全員ログインあり）。"""
    positions = {}

    def person(key, code, position, *, allowed_apps=None, employee_no="", superuser=False):
        make = User.objects.create_superuser if superuser else User.objects.create_user
        user = make(
            username=key, password="pass-12345", company=company_a, employee_no=employee_no,
        )
        return Worker.unscoped.create(
            company=company_a, user=user, name=key, employee_code=code, hourly_cost=3000,
            position=_position(company_a, position, positions),
            allowed_apps=allowed_apps or [],
        )

    people = {
        "plain": person("plain", "E001", "正社員"),
        "president": person("president", "E010", "社長"),
        "executive": person("executive", "S001", "役員"),
        # IT 担当の作成時に allowed_apps へ devkanri だけが入る（workers.services）
        "developer": person(
            "developer", "G001", "Developer", allowed_apps=["devkanri"], employee_no="G001",
        ),
        "developer_open": person("developer_open", "G002", "Developer", employee_no="G002"),
        "y_admin": person("y_admin", "Y001", "正社員"),
        "cost_granted": person("cost_granted", "E020", "正社員"),
        "office_staff": person("office_staff", "E030", "正社員"),
        "superuser": person("superuser", "E040", "正社員", superuser=True),
    }
    CostAccessGrant.unscoped.create(company=company_a, user=people["cost_granted"].user)
    role = Role.unscoped.create(company=company_a, code="office_staff", name="事務員")
    UserRole.unscoped.create(company=company_a, user=people["office_staff"].user, role=role)
    return people


def test_確かめる画面は全機能ぶんある():
    assert set(APP_URLS) == {app.key for app in APPS}


# ---------------------------------------------------------------------------
# 案 = 今の判定
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPlanMatchesLegacyChecks:
    def test_案は今の判定で画面を開いた結果と一致する(self, people):
        mismatches = []
        for key, worker in people.items():
            client = Client(raise_request_exception=False)
            client.force_login(worker.user)
            access = legacy_access_for_worker(worker)
            for app_key, urls in APP_URLS.items():
                for url in urls:
                    status = client.get(url).status_code
                    if (status != 403) != (app_key in access):
                        planned = "可" if app_key in access else "不可"
                        mismatches.append(f"{key} {url}: 画面={status} 案={planned}")
        assert mismatches == []

    def test_今の権限の分かれ目(self, people):
        plan = {key: legacy_access_for_worker(worker) for key, worker in people.items()}

        # 人事評価は社長・役員・Developer と Y 始まり
        assert "hr_evaluation" not in plan["plain"]
        assert {"president", "executive", "developer_open", "y_admin"} <= {
            key for key, access in plan.items() if "hr_evaluation" in access
        }
        # 原価は G 始まりと個別許可。役職の社長・役員だけでは見られない（ロールが無いため）
        assert "costs" in plan["developer_open"]
        assert "costs" in plan["cost_granted"]
        assert not {"plain", "president", "executive"} & {
            key for key, access in plan.items() if "costs" in access
        }
        # 書類アラートは Y 始まりと事務員ロール
        assert "document_alerts" in plan["y_admin"]
        assert "document_alerts" in plan["office_staff"]
        assert "document_alerts" not in plan["plain"]
        # allowed_apps に devkanri だけがある人は、ミドルウェアの表に無い機能と devkanri だけ
        assert set(plan["developer"]) == {"devkanri", "attendance", "estimation", "ai"}
        # superuser は全機能
        assert set(plan["superuser"]) == {app.key for app in APPS}

    def test_日報の承認は今の承認者と一致し原価には付けない(self, people):
        for key, worker in people.items():
            access = legacy_access_for_worker(worker)
            if "reports" in access:
                assert access["reports"] == can_approve_report(worker.user), key
            assert access.get("costs", False) is False, key
        assert legacy_access_for_worker(people["president"])["reports"] is True
        assert legacy_access_for_worker(people["developer_open"])["reports"] is True
        assert legacy_access_for_worker(people["plain"])["reports"] is False

    def test_ログインのない作業員は作業員の項目だけで判定する(self, company_a):
        positions = {}
        executive = Worker.unscoped.create(
            company=company_a, name="役員（ログインなし）", employee_code="S010", hourly_cost=0,
            position=_position(company_a, "役員", positions),
        )
        president = Worker.unscoped.create(
            company=company_a, name="社長（ログインなし）", employee_code="E050", hourly_cost=0,
            position=_position(company_a, "社長", positions),
        )

        access = legacy_access_for_worker(executive)
        assert "hr_evaluation" in access
        # ユーザーに付く権限（ロール・原価の個別許可）は持たない扱い
        assert not {"costs", "settings", "document_alerts"} & set(access)
        assert access["reports"] is False
        assert legacy_access_for_worker(president)["reports"] is True


# ---------------------------------------------------------------------------
# 反映
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestSyncAppAccess:
    def test_案どおりに作り_2回目は何も変えない(self, company_a, people):
        plan = legacy_access_plan(company_a)
        expected = sum(len(access) for _worker, access in plan)

        first = sync_app_access(company_a, plan, apply=True)

        assert first.created == expected
        assert AppAccess.unscoped.filter(company=company_a).count() == expected
        approvers = set(
            AppAccess.unscoped.filter(app_key="reports", can_approve=True)
            .values_list("worker__name", flat=True),
        )
        assert {"president", "developer_open", "superuser"} <= approvers
        again = sync_app_access(company_a, legacy_access_plan(company_a), apply=True)
        assert again == SyncResult()

    def test_ずれた行を直し余った行を消す(self, company_a, people):
        sync_app_access(company_a, legacy_access_plan(company_a), apply=True)
        AppAccess.unscoped.create(
            company=company_a, worker=people["plain"], app_key="hr_evaluation",
        )
        row = AppAccess.unscoped.get(worker=people["president"], app_key="reports")
        row.can_approve = False
        row.save()

        result = sync_app_access(company_a, legacy_access_plan(company_a), apply=True)

        assert (result.created, result.updated, result.deleted) == (0, 1, 1)
        assert not AppAccess.unscoped.filter(
            worker=people["plain"], app_key="hr_evaluation",
        ).exists()
        assert AppAccess.unscoped.get(worker=people["president"], app_key="reports").can_approve
        assert AppAccess.history.filter(worker=people["president"]).exists()

    def test_applyしなければ書き込まない(self, company_a, people):
        result = sync_app_access(company_a, legacy_access_plan(company_a), apply=False)

        assert result.created > 0
        assert not AppAccess.unscoped.exists()

    def test_他社の行には触らない(self, company_a, company_b, people):
        other = Worker.unscoped.create(company=company_b, name="B社の人", hourly_cost=3000)
        AppAccess.unscoped.create(company=company_b, worker=other, app_key="sites")

        sync_app_access(company_a, legacy_access_plan(company_a), apply=True)

        assert AppAccess.unscoped.filter(company=company_b).count() == 1

    def test_退職者の行は消す(self, company_a, people):
        sync_app_access(company_a, legacy_access_plan(company_a), apply=True)
        retired = people["plain"]
        retired.is_active = False
        retired.save()

        sync_app_access(company_a, legacy_access_plan(company_a), apply=True)

        assert not AppAccess.unscoped.filter(worker=retired).exists()


# ---------------------------------------------------------------------------
# 管理コマンド
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestPlanAppAccessCommand:
    def test_既定では書き込まずに案と差分を出す(self, company_a, people):
        out = io.StringIO()

        call_command("plan_app_access", stdout=out)

        text = out.getvalue()
        assert "== A社電気工事（在籍 9 人）" in text
        assert "人事評価: " in text
        assert "承認できる: " in text and "E010 president" in text
        assert "--apply で反映します" in text
        assert not AppAccess.unscoped.exists()

    def test_applyで反映する(self, company_a, people):
        expected = sum(len(access) for _worker, access in legacy_access_plan(company_a))

        call_command("plan_app_access", "--apply", stdout=io.StringIO())

        assert AppAccess.unscoped.filter(company=company_a).count() == expected

    def test_作業員と機能の表をCSVで出す(self, company_a, people):
        out = io.StringIO()

        call_command("plan_app_access", "--matrix", "--company", str(company_a.pk), stdout=out)

        lines = out.getvalue().splitlines()
        assert lines[0].startswith("会社,社員番号,氏名,役職,ログイン,現場管理,日報管理")
        president = next(line for line in lines if ",president," in line)
        assert ",承認," in president
        assert not AppAccess.unscoped.exists()

    def test_存在しない会社や矛盾する指定はエラー(self, company_a):
        with pytest.raises(CommandError):
            call_command("plan_app_access", "--company", "999999", stdout=io.StringIO())
        with pytest.raises(CommandError):
            call_command("plan_app_access", "--apply", "--matrix", stdout=io.StringIO())

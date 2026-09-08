"""apps.core.navigation — サイドバーの active 判定。

判定を base.html の {% if %} から Python へ移した理由を固定するテスト。
テンプレート時代は次の2つが原因で誤判定していた。

  * `{% if 'masters:' in view_name and 'customer' in url_name or 'supplier' in url_name %}`
    Django テンプレートは `and` が `or` より強いため、url_name に "supplier" を
    含むだけで「取引先」グループが開いた。materials:material_supplier_list が
    実際に該当する。
  * 「マスタ管理」が `'masters:' in view_name` で active になっていたため、
    顧客一覧を開くと「顧客」と同時に2箇所が active になった。

どちらも「最も具体的に一致した項目だけが active」という規則で消える。
"""

import pytest

from apps.core.navigation import (
    NAVIGATION,
    NavGroup,
    NavItem,
    build_navigation,
    is_visible,
    resolve_active,
)
from apps.workers.models import Position, Worker


def _all_items():
    for entry in NAVIGATION:
        yield from (entry.items if isinstance(entry, NavGroup) else (entry,))


def test_名前空間の前方一致で選ばれる():
    assert resolve_active("sites:detail").label == "現場管理"
    assert resolve_active("reports:list").label == "日報管理"


def test_完全一致の項目は他の画面に反応しない():
    assert resolve_active("dashboard").label == "ダッシュボード"
    # 名前空間付きの dashboard は別物として扱う
    assert resolve_active("sales:dashboard").label == "営業ダッシュボード"
    assert resolve_active("ai:dashboard").label == "利用状況"


def test_材料の発注先一覧で取引先グループが開かない():
    """旧条件式が 'supplier' の部分一致で誤検知していたケース。"""
    assert resolve_active("materials:material_supplier_list").label == "材料・発注"


def test_顧客一覧でマスタ管理が同時にactiveにならない():
    assert resolve_active("masters:customer_list").label == "顧客"
    assert resolve_active("masters:worktypes").label == "マスタ管理"


def test_同居する名前空間が接頭辞で振り分けられる():
    """workers は作業員台帳と評価が同じ名前空間にある。"""
    assert resolve_active("workers:detail").label == "作業員"
    assert resolve_active("workers:qual_create").label == "作業員"
    assert resolve_active("workers:eval_create").label == "人材評価"
    assert resolve_active("workers:evaluations").label == "人材評価"
    assert resolve_active("workers:document_alerts").label == "書類アラート"


def test_より具体的なパターンが優先される():
    """estimation:project_* と estimation:item_* のように接頭辞が競合しない範囲でも、
    完全一致と前方一致が重なったときは完全一致を選ぶ。"""
    assert resolve_active("estimation:standard_edit").label == "積算基準・歩掛"
    assert resolve_active("estimation:workrate_create").label == "積算基準・歩掛"
    assert resolve_active("bids:qualification_import").label == "入札参加資格"


def test_解決できない画面ではどこもactiveにならない():
    assert resolve_active(None) is None
    assert resolve_active("") is None
    assert resolve_active("admin:index") is None


def test_activeになる項目は常に1つ以下():
    """resolve_active が返すのは1件なので、全 url_name を通しても重複しない。"""
    view_names = [
        "sites:list",
        "masters:customer_list",
        "masters:supplier_list",
        "masters:worktypes",
        "materials:material_supplier_list",
        "workers:eval_detail",
        "evaluation:eval_list",
        "notification_list",
        "alert_rule_create",
        "audit_log",
        "permissions:matrix",
    ]
    for view_name in view_names:
        matched = [item for item in _all_items() if item is resolve_active(view_name)]
        assert len(matched) <= 1, f"{view_name} が複数の項目に一致した"


def test_定義した項目のパターンが互いを食い合わない():
    """ある項目の url_name を開いたとき、必ずその項目自身が選ばれる。

    パターンを足したときに他の項目を奪っていないことの回帰チェック。
    """
    for item in _all_items():
        assert resolve_active(item.url_name) is item, (
            f"{item.url_name} を開くと {resolve_active(item.url_name).label} が選ばれる"
        )


# ---------------------------------------------------------------------------
# 役職による出し分け
#
# base.html に手書きされていた
#   {% if user|can_use:"hr_evaluation" %} 人事評価一覧 … {% endif %}
# を NavItem.permission へ移した。判定は permissions.services.can_use_app に
# 委ねているので、ここで確かめるのは「どの項目に印が付いているか」と
# 「印の付いた項目が絞られるか」の2点。
# ---------------------------------------------------------------------------

HR_LABELS = {"人事評価一覧", "評価基準", "評価対象設定"}


def _labels(nav):
    labels = set()
    for entry in nav:
        if entry.get("items"):
            labels.update(item["label"] for item in entry["items"])
        else:
            labels.add(entry["label"])
    return labels


def test_人事評価の3項目だけが権限を持つ():
    restricted = {
        item.label
        for entry in NAVIGATION
        for item in (entry.items if isinstance(entry, NavGroup) else (entry,))
        if item.permission
    }
    assert restricted == HR_LABELS

    for entry in NAVIGATION:
        for item in (entry.items if isinstance(entry, NavGroup) else (entry,)):
            if item.label in HR_LABELS:
                assert item.permission == "hr_evaluation"


def test_権限を持たない項目は誰にでも出す():
    assert is_visible(NavItem("作業員", "workers:list", "👥"), None) is True


def test_userを渡さなければ絞らない():
    """管理コマンドやテストからの呼び出しでは判定材料が無いので落とさない。"""
    assert _labels(build_navigation(None)) >= HR_LABELS


@pytest.mark.django_db
class TestNavigationPermission:
    def _user_with_position(self, company, username, position_name):
        from django.contrib.auth.models import Group

        from apps.accounts.models import User

        user = User.objects.create_user(
            username=username, password="testpass123", company=company,
        )
        Group.objects.get_or_create(name="worker")
        position = Position.unscoped.create(company=company, name=position_name)
        Worker.unscoped.create(
            company=company, name=username, employee_code=f"E-{username}",
            position=position, hourly_cost=3000, user=user,
        )
        return user

    def test_役職の無いユーザーには人事評価を出さない(self, company_a, user_a):
        labels = _labels(build_navigation("dashboard", user_a))

        assert not (HR_LABELS & labels)
        # 同じグループの他の項目は残る
        assert "作業員" in labels

    def test_役員には人事評価を出す(self, company_a):
        user = self._user_with_position(company_a, "yakuin", "役員")
        assert _labels(build_navigation("dashboard", user)) >= HR_LABELS

    def test_一般社員には人事評価を出さない(self, company_a):
        user = self._user_with_position(company_a, "seishain", "正社員")
        assert not (HR_LABELS & _labels(build_navigation("dashboard", user)))

    def test_superuserには出す(self, company_a):
        from apps.accounts.models import User

        user = User.objects.create_superuser(
            username="root", password="testpass123",
        )
        user.company = company_a
        user.save(update_fields=["company"])
        assert _labels(build_navigation("dashboard", user)) >= HR_LABELS

    def test_画面にも出ない(self, client, company_a, user_a):
        """context processor 経由でも同じであること。"""
        client.force_login(user_a)
        html = client.get("/").content.decode()

        assert "人事評価一覧" not in html
        assert "作業員" in html

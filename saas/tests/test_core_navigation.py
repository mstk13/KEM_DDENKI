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

from apps.core.navigation import NAVIGATION, NavGroup, resolve_active


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

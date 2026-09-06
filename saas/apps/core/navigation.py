"""サイドバーナビゲーションの定義と active 判定。

base.html に手書きされていた約50本のリンクと、その一つひとつに付いていた
{% if %} 条件をここへ集約する。テンプレート側で判定していたときは、

  * Django テンプレートの `and` は `or` より優先される
  * `in` は右辺が文字列だと部分一致になる

の2点が原因で、意図しないグループが開いたり、2箇所が同時に active になったり
していた。判定を Python に置き、「最も具体的に一致した項目だけが active」という
規則を1箇所で保証する。

パターンの書き方:
    "sites:list"    … view_name の完全一致
    "sites:*"       … 前方一致（末尾の * まで）

同じ view_name に複数の項目が一致した場合は、一致した前置き部分が長いものを
選ぶ。長さが同じなら完全一致を優先する。
"""

from dataclasses import dataclass

from django.urls import reverse


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    icon: str
    match: tuple[str, ...] = ()

    def patterns(self) -> tuple[str, ...]:
        """match 未指定なら url_name の完全一致だけを見る。"""
        return self.match or (self.url_name,)


@dataclass(frozen=True)
class NavGroup:
    label: str
    items: tuple[NavItem, ...]


# 表示順がそのままサイドバーの並び。NavItem を直に置くと単独リンクになる。
NAVIGATION: tuple[NavItem | NavGroup, ...] = (
    NavItem("ダッシュボード", "dashboard", "📊"),
    NavGroup(
        "現場・日報",
        (
            NavItem("現場管理", "sites:list", "🏗️", ("sites:*",)),
            NavItem("日報管理", "reports:list", "📝", ("reports:*",)),
            NavItem("工期管理", "schedules:list", "📅", ("schedules:*",)),
        ),
    ),
    NavGroup(
        "現場見積もり・材料",
        (
            NavItem("現場見積もり/実経費", "costs:list", "💰", ("costs:*",)),
            NavItem("材料・発注", "materials:list", "📦", ("materials:*",)),
        ),
    ),
    NavGroup(
        "人材",
        (
            # workers は作業員台帳と評価が同じ名前空間に同居しているため、
            # 名前空間ごとではなく url_name の接頭辞で振り分ける。
            NavItem(
                "作業員",
                "workers:list",
                "👥",
                (
                    "workers:list",
                    "workers:create",
                    "workers:detail",
                    "workers:edit",
                    "workers:excel",
                    "workers:qual_*",
                    "workers:health_*",
                ),
            ),
            NavItem(
                "人材評価",
                "workers:evaluations",
                "📋",
                ("workers:evaluations", "workers:eval_*"),
            ),
            NavItem("書類アラート", "workers:document_alerts", "⚠️"),
            NavItem(
                "人事評価一覧",
                "evaluation:eval_list",
                "📏",
                ("evaluation:eval_*", "evaluation:employee_summary"),
            ),
            NavItem(
                "評価基準",
                "evaluation:criteria_list",
                "📐",
                ("evaluation:criteria_*",),
            ),
            NavItem(
                "評価対象設定",
                "evaluation:assignment_list",
                "🔗",
                ("evaluation:assignment_*",),
            ),
        ),
    ),
    NavGroup(
        "取引先",
        (
            NavItem("顧客", "masters:customer_list", "👥", ("masters:customer_*",)),
            NavItem("発注先", "masters:supplier_list", "🏭", ("masters:supplier_*",)),
        ),
    ),
    NavGroup(
        "入札・営業",
        (
            NavItem(
                "入札案件",
                "bids:project_list",
                "📋",
                (
                    "bids:project_*",
                    "bids:dashboard",
                    "bids:mark_won",
                    "bids:start_estimation",
                ),
            ),
            NavItem(
                "入札参加資格",
                "bids:qualification_list",
                "🏅",
                ("bids:qualification_*",),
            ),
            NavItem("単価マスタ", "bids:unit_price_list", "💴", ("bids:unit_price_*",)),
            NavItem("案件取得", "bids:scrape_target_list", "🌐", ("bids:scrape_*",)),
        ),
    ),
    NavGroup(
        "積算",
        (
            NavItem(
                "積算案件",
                "estimation:project_list",
                "📁",
                (
                    "estimation:project_*",
                    "estimation:boq_export",
                    "estimation:boqline_*",
                    "estimation:generate_comparison",
                ),
            ),
            NavItem("積算品目", "estimation:item_list", "📐", ("estimation:item_*",)),
            NavItem("名寄せレビュー", "estimation:alias_list", "🔗", ("estimation:alias_*",)),
            NavItem("発注機関", "estimation:orderer_list", "🏛️", ("estimation:orderer_*",)),
            NavItem(
                "労務単価",
                "estimation:labor_rate_list",
                "💴",
                ("estimation:labor_rate_*",),
            ),
            NavItem(
                "積算基準・歩掛",
                "estimation:standard_list",
                "📖",
                ("estimation:standard_*", "estimation:workrate_*"),
            ),
            NavItem(
                "仕入実績",
                "estimation:purchase_list",
                "📦",
                ("estimation:purchase_*",),
            ),
            NavItem(
                "データソース一覧",
                "estimation:datasource_matrix",
                "📋",
                ("estimation:datasource_*",),
            ),
        ),
    ),
    NavGroup(
        "営業",
        (
            NavItem("営業ダッシュボード", "sales:dashboard", "📊"),
            NavItem("訪問記録", "sales:visit_list", "📋", ("sales:visit_*",)),
            NavItem("業種別一覧", "sales:industry_browse", "🏭"),
        ),
    ),
    NavGroup(
        "勤怠",
        (
            NavItem(
                "勤怠日報",
                "attendance:report_list",
                "📋",
                ("attendance:report_*",),
            ),
            NavItem(
                "個人別一覧",
                "attendance:entry_list",
                "👥",
                ("attendance:entry_list", "attendance:employee_record"),
            ),
            NavItem("月次サマリ", "attendance:summary", "📊"),
            NavItem("勤怠設定", "attendance:settings", "⚙️"),
        ),
    ),
    NavGroup(
        "開発",
        (
            NavItem(
                "開発管理",
                "devkanri:project_list",
                "💻",
                ("devkanri:project_*", "devkanri:task_*"),
            ),
            NavItem(
                "目安箱",
                "devkanri:meyasubako_list",
                "📮",
                ("devkanri:meyasubako_*",),
            ),
        ),
    ),
    NavGroup(
        "AI分析",
        (
            NavItem(
                "コスト分析・工程提案",
                "ai:site_select",
                "🤖",
                (
                    "ai:site_select",
                    "ai:cost_prediction",
                    "ai:cost_optimization",
                    "ai:cost_report",
                    "ai:schedule_suggestion",
                    "ai:schedule_risk",
                    "ai:batch_list",
                ),
            ),
            NavItem("利用状況", "ai:dashboard", "📊"),
            NavItem("実行ログ", "ai:log_list", "📄", ("ai:log_*", "ai:feedback_*")),
        ),
    ),
    NavGroup(
        "設定",
        (
            NavItem(
                "通知・アラート",
                "notification_list",
                "🔔",
                ("notification_*", "alert_rule_*"),
            ),
            NavItem(
                "マスタ管理",
                "masters:worktypes",
                "⚙️",
                ("masters:worktypes", "masters:extract_partner"),
            ),
            NavItem("権限管理", "permissions:matrix", "🔒", ("permissions:*",)),
            NavItem("変更ログ", "audit_log", "📜"),
        ),
    ),
)


def _specificity(pattern: str, view_name: str) -> tuple[int, int] | None:
    """pattern が view_name に一致するなら具体度を返す。しなければ None。

    具体度は (一致した前置きの長さ, 完全一致なら1) の組。大きいほど具体的。
    """
    if pattern.endswith("*"):
        prefix = pattern[:-1]
        return (len(prefix), 0) if view_name.startswith(prefix) else None
    return (len(pattern), 1) if pattern == view_name else None


def resolve_active(view_name: str | None) -> NavItem | None:
    """view_name に最も具体的に一致する項目を1つだけ返す。

    複数のグループにまたがって一致しても、返るのは常に1つ。これが
    「マスタ管理と顧客が同時に active になる」類の重複を防ぐ。
    """
    if not view_name:
        return None

    best: NavItem | None = None
    best_score: tuple[int, int] = (-1, -1)
    for entry in NAVIGATION:
        items = entry.items if isinstance(entry, NavGroup) else (entry,)
        for item in items:
            for pattern in item.patterns():
                score = _specificity(pattern, view_name)
                if score is not None and score > best_score:
                    best, best_score = item, score
    return best


def build_navigation(view_name: str | None) -> list[dict]:
    """テンプレートがそのまま回せる形に落とす。

    URL の逆引きはここで済ませ、テンプレートから {% url %} を無くす。
    """
    active = resolve_active(view_name)

    nav: list[dict] = []
    for entry in NAVIGATION:
        if isinstance(entry, NavGroup):
            items = [
                {
                    "label": item.label,
                    "icon": item.icon,
                    "url": reverse(item.url_name),
                    "active": item is active,
                }
                for item in entry.items
            ]
            nav.append(
                {
                    "label": entry.label,
                    "items": items,
                    "open": any(item["active"] for item in items),
                }
            )
        else:
            nav.append(
                {
                    "label": entry.label,
                    "icon": entry.icon,
                    "url": reverse(entry.url_name),
                    "active": entry is active,
                    "items": None,
                }
            )
    return nav

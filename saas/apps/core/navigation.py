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

役職で絞る項目は NavItem.permission にアプリコードを書く。判定は
permissions.services.can_use_app に委ね、ここでは持たない。

サイドバーの並びは再設計仕様書 v2.0 §2.1 の業務グループ（ADR-0029）。
関連する画面が多い入札・積算マスタ・業者名鑑は、サイドバーを1項目にし、
画面の上に出すタブ（SectionTabs）で行き来する。
"""

from dataclasses import dataclass

from django.urls import reverse


@dataclass(frozen=True)
class NavItem:
    label: str
    url_name: str
    icon: str
    match: tuple[str, ...] = ()
    # 役職で利用を絞るアプリのコード（permissions.services.POSITION_RESTRICTED_APPS）。
    # 空なら誰にでも出す。テンプレート時代の
    #   {% if user|can_use:"hr_evaluation" %} ... {% endif %}
    # をここへ移したもの。判定の実体は permissions 側にあり、
    # ここは「どの項目がどのアプリに属するか」だけを持つ。
    permission: str = ""

    def patterns(self) -> tuple[str, ...]:
        """match 未指定なら url_name の完全一致だけを見る。"""
        return self.match or (self.url_name,)


@dataclass(frozen=True)
class NavGroup:
    label: str
    items: tuple[NavItem, ...]


@dataclass(frozen=True)
class SectionTabs:
    """サイドバーでは1項目にまとめ、画面の上のタブで行き来する画面群。

    サイドバーの項目は patterns() をそのまま match に使うので、
    タブを足せばサイドバーの active 判定にも自動で反映される。
    """

    label: str
    tabs: tuple[NavItem, ...]

    def patterns(self) -> tuple[str, ...]:
        return tuple(pattern for tab in self.tabs for pattern in tab.patterns())


BID_TABS = SectionTabs(
    "入札",
    (
        NavItem(
            "入札案件",
            "bids:project_list",
            "",
            ("bids:project_*", "bids:mark_won", "bids:start_estimation"),
        ),
        NavItem("入札ダッシュボード", "bids:dashboard", ""),
        NavItem("入札参加資格", "bids:qualification_list", "", ("bids:qualification_*",)),
        NavItem("単価マスタ", "bids:unit_price_list", "", ("bids:unit_price_*",)),
        NavItem("案件取得", "bids:scrape_target_list", "", ("bids:scrape_*",)),
    ),
)

ESTIMATION_MASTER_TABS = SectionTabs(
    "積算マスタ",
    (
        NavItem("積算品目", "estimation:item_list", "", ("estimation:item_*",)),
        NavItem("名寄せレビュー", "estimation:alias_list", "", ("estimation:alias_*",)),
        NavItem("発注機関", "estimation:orderer_list", "", ("estimation:orderer_*",)),
        NavItem("労務単価", "estimation:labor_rate_list", "", ("estimation:labor_rate_*",)),
        NavItem(
            "積算基準・歩掛",
            "estimation:standard_list",
            "",
            ("estimation:standard_*", "estimation:workrate_*"),
        ),
        NavItem("仕入実績", "estimation:purchase_list", "", ("estimation:purchase_*",)),
        NavItem(
            "データソース一覧",
            "estimation:datasource_matrix",
            "",
            ("estimation:datasource_*",),
        ),
    ),
)

# v2.0 §3: 来訪営業の記録（sales）は「マスタ > 業者名鑑」へ移す。
VENDOR_DIRECTORY_TABS = SectionTabs(
    "業者名鑑",
    (
        NavItem("訪問記録", "sales:visit_list", "", ("sales:visit_*",)),
        NavItem("業種別一覧", "sales:industry_browse", ""),
        NavItem("営業ダッシュボード", "sales:dashboard", ""),
    ),
)

# 材料ごとの過去の取引の検索は、サイドバーに増やさず材料・発注の中に置く（ADR-0034）。
# 取引履歴は完全一致なので、materials:* より具体的に一致してそちらが active になる。
MATERIALS_TABS = SectionTabs(
    "材料・発注",
    (
        NavItem("材料・発注", "materials:list", "", ("materials:*",)),
        NavItem("取引履歴", "materials:purchase_history", ""),
    ),
)

SECTION_TABS: tuple[SectionTabs, ...] = (
    BID_TABS,
    ESTIMATION_MASTER_TABS,
    VENDOR_DIRECTORY_TABS,
    MATERIALS_TABS,
)


# 表示順がそのままサイドバーの並び。NavItem を直に置くと単独リンクになる。
NAVIGATION: tuple[NavItem | NavGroup, ...] = (
    # ダッシュボードの統合（5種 → 1つ）は KPI の選定待ち。今は既存のトップを指す。
    NavItem("ホーム", "dashboard", "🏠"),
    NavGroup(
        "現場",
        (
            NavItem("入札案件", "bids:project_list", "📋", BID_TABS.patterns()),
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
            NavItem("現場管理", "sites:list", "🏗️", ("sites:*",)),
            NavItem("工期管理", "schedules:list", "📅", ("schedules:*",)),
            NavItem("現場見積もり/実経費", "costs:list", "💰", ("costs:*",)),
            # 発注は現場に紐づくため現場グループに置く（ADR-0033）。
            # 材料ごとの過去の取引の検索は、材料・発注の画面の中に置く。
            NavItem("材料・発注", "materials:list", "📦", ("materials:*",)),
        ),
    ),
    NavGroup(
        "日々の記録",
        (
            NavItem("日報管理", "reports:list", "📝", ("reports:*",)),
            NavItem(
                "出社予定",
                "attendance:plan_board",
                "🗓️",
                ("attendance:plan_*",),
            ),
            # 実績は日報（reports）に一本化した。月次サマリは日報側の
            # 月別集計をそのまま指す。ADR-0024。
            NavItem("月次サマリ", "reports:monthly_summary", "📊"),
        ),
    ),
    NavGroup(
        "作業員",
        (
            # workers は作業員台帳と評価が同じ名前空間に同居しているため、
            # 名前空間ごとではなく url_name の接頭辞で振り分ける。
            # グループ名と同じ「作業員」が並ぶと区別しにくいので「作業員一覧」（ADR-0033）。
            NavItem(
                "作業員一覧",
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
                permission="hr_evaluation",
            ),
            NavItem(
                "評価基準",
                "evaluation:criteria_list",
                "📐",
                ("evaluation:criteria_*",),
                permission="hr_evaluation",
            ),
            NavItem(
                "評価対象設定",
                "evaluation:assignment_list",
                "🔗",
                ("evaluation:assignment_*",),
                permission="hr_evaluation",
            ),
        ),
    ),
    # 取引の相手だけを置く。積算マスタ・工種マスタは設定へ（ADR-0033）。
    NavGroup(
        "取引先",
        (
            NavItem("顧客", "masters:customer_list", "👥", ("masters:customer_*",)),
            NavItem("発注先", "masters:supplier_list", "🏭", ("masters:supplier_*",)),
            NavItem("業者名鑑", "sales:visit_list", "📇", VENDOR_DIRECTORY_TABS.patterns()),
        ),
    ),
    # 「AI分析」グループは置かない（ADR-0026）。AI の個別機能は現場・原価・工期の
    # 詳細画面から開き、利用状況と実行ログは管理者向けとして「設定」に置く。
    NavGroup(
        "設定",
        (
            NavItem(
                "通知・アラート",
                "notification_list",
                "🔔",
                ("notification_*", "alert_rule_*"),
            ),
            NavItem("権限管理", "permissions:matrix", "🔒", ("permissions:*",)),
            NavItem("勤怠設定", "attendance:settings", "⏱️"),
            NavItem(
                "積算マスタ",
                "estimation:item_list",
                "📐",
                ESTIMATION_MASTER_TABS.patterns(),
            ),
            NavItem(
                "工種マスタ",
                "masters:worktypes",
                "⚙️",
                ("masters:worktypes", "masters:extract_partner"),
            ),
            NavItem(
                "AI利用状況",
                "ai:dashboard",
                "🤖",
                ("ai:dashboard", "ai:cost_report", "ai:batch_list"),
            ),
            NavItem("AI実行ログ", "ai:log_list", "📄", ("ai:log_*", "ai:feedback_*")),
            NavItem("変更ログ", "audit_log", "📜"),
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
)


def _specificity(pattern: str, view_name: str) -> tuple[int, int] | None:
    """pattern が view_name に一致するなら具体度を返す。しなければ None。

    具体度は (一致した前置きの長さ, 完全一致なら1) の組。大きいほど具体的。
    """
    if pattern.endswith("*"):
        prefix = pattern[:-1]
        return (len(prefix), 0) if view_name.startswith(prefix) else None
    return (len(pattern), 1) if pattern == view_name else None


def _best_match(
    items: tuple[NavItem, ...], view_name: str
) -> tuple[NavItem | None, tuple[int, int]]:
    best: NavItem | None = None
    best_score: tuple[int, int] = (-1, -1)
    for item in items:
        for pattern in item.patterns():
            score = _specificity(pattern, view_name)
            if score is not None and score > best_score:
                best, best_score = item, score
    return best, best_score


def resolve_active(view_name: str | None) -> NavItem | None:
    """view_name に最も具体的に一致する項目を1つだけ返す。

    複数のグループにまたがって一致しても、返るのは常に1つ。これが
    「マスタ管理と顧客が同時に active になる」類の重複を防ぐ。
    """
    if not view_name:
        return None

    items = tuple(
        item
        for entry in NAVIGATION
        for item in (entry.items if isinstance(entry, NavGroup) else (entry,))
    )
    return _best_match(items, view_name)[0]


def is_visible(item: NavItem, user) -> bool:
    """その項目を user に出してよいか。

    permission を持たない項目は常に出す。持つ項目は permissions 側の
    判定に委ねる。user が渡らない呼び出し（テストや管理コマンド）では
    絞らない。絞る条件を2箇所に書くと必ず食い違うため、判定は
    can_use_app 1つに寄せる。
    """
    if not item.permission or user is None:
        return True

    from apps.permissions.services import can_use_app

    return can_use_app(user, item.permission)


def build_navigation(view_name: str | None, user=None) -> list[dict]:
    """テンプレートがそのまま回せる形に落とす。

    URL の逆引きはここで済ませ、テンプレートから {% url %} を無くす。
    user を渡すと、役職で使えない項目を落とす。項目が全部消えた
    グループは見出しだけ残っても意味がないので、グループごと落とす。
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
                if is_visible(item, user)
            ]
            if not items:
                continue
            nav.append(
                {
                    "label": entry.label,
                    "items": items,
                    "open": any(item["active"] for item in items),
                }
            )
        elif is_visible(entry, user):
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


def build_section_tabs(view_name: str | None) -> dict | None:
    """view_name が SECTION_TABS のどれかに属するなら、画面上部のタブを返す。

    属さない画面では None（base.html はタブを描かない）。
    active になるタブは、サイドバーと同じ「最も具体的に一致した1つ」。
    """
    if not view_name:
        return None

    best_section: SectionTabs | None = None
    best_tab: NavItem | None = None
    best_score: tuple[int, int] = (-1, -1)
    for section in SECTION_TABS:
        tab, score = _best_match(section.tabs, view_name)
        if tab is not None and score > best_score:
            best_section, best_tab, best_score = section, tab, score

    if best_section is None:
        return None
    return {
        "label": best_section.label,
        "tabs": [
            {
                "label": tab.label,
                "url": reverse(tab.url_name),
                "active": tab is best_tab,
            }
            for tab in best_section.tabs
        ],
    }

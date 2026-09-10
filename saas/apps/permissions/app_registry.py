"""
機能（アプリ）キーの一覧。アクセス管理で使う語彙はここだけで定義する（ADR-0030）。

今はキーの語彙が4か所に分かれていて、互いに食い違っている。

- permissions.models.ModulePermission.MODULE_CHOICES
- core.middleware._PATH_TO_APP
- workers.forms.APP_PERMISSION_CHOICES
- tenants.models.CompanyApp.APP_CODES（jinzai / nippou などローマ字の別語彙）

AppAccess と has_app_access はこの一覧だけを見る。expand の段階なので、
ミドルウェア・ナビ・管理画面はまだここを参照していない（切り替えは後続の PR）。
既にあるキー（hr_evaluation / evaluations / devkanri など）は名前を変えない。
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class AppDef:
    key: str
    label: str
    # この機能に属する URL の前置き。複数の機能に一致したら、長く一致したほうを採る。
    path_prefixes: tuple[str, ...] = ()
    # 「承認できる人」リストを持つか。v2.0 §4 で日報承認・原価承認だけと決めている。
    approvable: bool = False


# 並びは管理画面のチェック表の列順になる想定。
APPS: tuple[AppDef, ...] = (
    AppDef("sites", "現場管理", ("/sites/",)),
    AppDef("reports", "日報管理", ("/reports/",), approvable=True),
    AppDef("schedules", "工期管理", ("/schedules/",)),
    AppDef("costs", "原価・予実", ("/costs/",), approvable=True),
    AppDef("materials", "材料・発注", ("/materials/",)),
    AppDef("workers", "作業員管理", ("/workers/",)),
    # /workers/ 配下の人材評価。前置きのほか、/workers/ 配下で "/evaluations/" を
    # 含むパスもここに入る（app_key_for_path の分岐。ミドルウェアの既存の判定と同じ）。
    AppDef("evaluations", "人材評価", ("/workers/evaluations/",)),
    # /evaluation/ の人事評価。上の人材評価とは別機能。
    AppDef("hr_evaluation", "人事評価", ("/evaluation/",)),
    # ミドルウェアは今 workers として扱っている。独立した画面なのでここで分ける。
    AppDef("document_alerts", "書類アラート", ("/workers/document-alerts/",)),
    AppDef("bids", "入札管理", ("/bids/",)),
    AppDef("estimation", "積算", ("/estimation/",)),
    AppDef("sales", "業者名鑑", ("/sales/",)),
    AppDef("masters", "マスタ管理", ("/masters/",)),
    AppDef("attendance", "勤怠", ("/attendance/",)),
    AppDef("notifications", "通知", ("/notifications/",)),
    # 権限管理と変更ログ。
    AppDef("settings", "設定", ("/settings/", "/audit-log/")),
    # /ai/ 配下全体。利用状況・実行ログ（ADR-0026 で設定に置いた画面）のほか、
    # 現場・原価・工期の詳細から開く AI 予測・工程提案も同じ前置きにある。
    # 分けるかどうかは切り替えの PR で決める。
    AppDef("ai", "AI", ("/ai/",)),
    AppDef("devkanri", "開発管理", ("/dev/",)),
)

APP_CHOICES = [(app.key, app.label) for app in APPS]

_APPS_BY_KEY = {app.key: app for app in APPS}


def get_app(key: str) -> AppDef:
    """キーから機能の定義を引く。

    未登録のキーは ValueError にする。打ち間違いで黙って閉じたり開いたり
    しないよう、判定の入口で必ずここを通す。
    """
    try:
        return _APPS_BY_KEY[key]
    except KeyError:
        raise ValueError(f"未登録のアプリキーです: {key!r}") from None


def app_key_for_path(path: str) -> str | None:
    """URL パスが属する機能のキーを返す。どこにも属さなければ None。

    AppPermissionMiddleware の今の解決方法に合わせてある。違いは、
    ミドルウェアに無い前置き（/attendance/ /estimation/ /ai/ /audit-log/）も
    解決することと、書類アラートを workers から分けることの2点。
    ミドルウェアはまだこの関数を使っていない。
    """
    best_key, best_len = None, -1
    for app in APPS:
        for prefix in app.path_prefixes:
            if path.startswith(prefix) and len(prefix) > best_len:
                best_key, best_len = app.key, len(prefix)

    # 人材評価は /workers/<pk>/evaluations/ のような形でも workers 配下に来る。
    if best_key == "workers" and "/evaluations/" in path:
        return "evaluations"
    return best_key

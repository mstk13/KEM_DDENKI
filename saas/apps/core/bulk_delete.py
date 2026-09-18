"""一覧から選んだものをまとめて消す（ADR-0098）。

削除は画面ごとに1件ずつのボタンしか無く、まとめて消せなかった。
取り込み直しや、試しに入れた行の後始末で数が多くなると手間がかかる。

安全のために次を守る。

- 消せる対象は `DELETABLE` に書いたものだけ。画面から任意のモデルは消せない
- 引くのは会社で絞ったマネージャ（`objects`）。他社の行は選んでも消えない
- 画面ごとの「消してよいか」の決まり（承認済みの日報は消せない など）はそのまま効かせる
- ほかから参照されていて消せない行（`ProtectedError`）は飛ばし、名前を画面に出す
"""

from dataclasses import dataclass, field

from django.apps import apps


@dataclass(frozen=True)
class Deletable:
    """まとめて消してよい対象。"""

    model_label: str
    label: str
    # 戻り先。画面から next が来なければここへ戻る
    redirect: str
    # 1件ごとの可否。(user, obj) -> bool。省略なら全部消せる
    can_delete: object = None
    # 画面に出す名前を作る。省略なら str(obj)
    describe: object = field(default=None)

    def model(self):
        return apps.get_model(self.model_label)

    def name_of(self, obj):
        return self.describe(obj) if self.describe else str(obj)


def _report_can_delete(user, report):
    from apps.permissions.services import can_delete_report

    return can_delete_report(user, report)


# 画面から消せるもの。鍵は画面側の form に書く
DELETABLE = {
    "reports.daily": Deletable(
        "reports.DailyReport", "日報", "reports:list", can_delete=_report_can_delete,
    ),
    "sites.site": Deletable("sites.Site", "現場", "sites:list"),
    "workers.worker": Deletable("workers.Worker", "作業員", "workers:list"),
    "workers.qualification": Deletable(
        "workers.WorkerQualification", "保有資格", "workers:list",
    ),
    "masters.customer": Deletable("masters.Customer", "顧客", "masters:customer_list"),
    "masters.supplier": Deletable("masters.Supplier", "発注先", "masters:supplier_list"),
    "bids.project": Deletable("bids.BidProject", "入札案件", "bids:project_list"),
    "bids.qualification": Deletable(
        "bids.Qualification", "入札参加資格", "bids:qualification_list",
    ),
    "bids.unified_qualification": Deletable(
        "bids.UnifiedQualification", "全省庁統一資格", "bids:qualification_list",
    ),
    "bids.license": Deletable(
        "bids.ConstructionLicense", "建設業許可", "bids:qualification_list",
    ),
    "bids.unit_price": Deletable("bids.UnitPrice", "単価", "bids:unit_price_list"),
    "bids.scrape_target": Deletable(
        "bids.ScrapeTarget", "案件取得先", "bids:scrape_target_list",
    ),
    "bids.skipped": Deletable("bids.SkippedBid", "見送り案件", "bids:skipped_list"),
    "bids.competitor": Deletable(
        "bids.BidCompetitor", "競合", "bids:project_list",
    ),
    "notifications.alert_rule": Deletable(
        "notifications.AlertRule", "アラートルール", "alert_rule_list",
    ),
    # 現場まわり
    "sites.document": Deletable("sites.SiteDocument", "提出書類", "sites:list"),
    "sites.document_file": Deletable(
        "sites.SiteDocumentFile", "書類のファイル", "sites:list",
    ),
    "sites.photo": Deletable("sites.SitePhoto", "現場写真", "sites:list"),
    "sites.process": Deletable("sites.Process", "工程", "sites:list"),
    # 工期管理
    "schedules.phase": Deletable("schedules.Phase", "工程", "schedules:list"),
    "schedules.milestone": Deletable(
        "schedules.Milestone", "マイルストーン", "schedules:list",
    ),
    "schedules.assignment": Deletable("schedules.Assignment", "配置", "schedules:list"),
    # 材料・発注
    "materials.po_item": Deletable(
        "materials.PurchaseOrderItem", "発注明細", "materials:po_list",
    ),
    "materials.quotation_item": Deletable(
        "materials.QuotationItem", "見積明細", "materials:quotation_list",
    ),
    # 積算
    "estimation.document": Deletable(
        "estimation.EstimationDocument", "案件資料", "estimation:project_list",
    ),
    "estimation.competitor": Deletable(
        "estimation.EstimationCompetitor", "競合", "estimation:project_list",
    ),
    "estimation.phase": Deletable(
        "estimation.EstimationPhase", "工程", "estimation:project_list",
    ),
    # 安全書類・開発管理・人事評価・営業・自社書類・健診
    "safety.ky_participant": Deletable(
        "safety.KyParticipant", "参加者", "sites:list",
    ),
    "devkanri.project": Deletable(
        "devkanri.DevProject", "開発プロジェクト", "devkanri:project_list",
    ),
    "devkanri.task": Deletable("devkanri.DevTask", "タスク", "devkanri:project_list"),
    "evaluation.assignment": Deletable(
        "evaluation.EvaluatorTarget", "評価の割当", "evaluation:assignment_list",
    ),
    "sales.visit": Deletable("sales.SalesVisit", "訪問記録", "sales:visit_list"),
    "tenants.company_document": Deletable(
        "tenants.CompanyDocument", "自社書類", "tenants:company_document_list",
    ),
    "workers.health": Deletable("workers.HealthCheckup", "健診の記録", "workers:list"),
}

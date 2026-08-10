"""デモ用テストデータ投入コマンド。

開発環境で各画面の実動作を確認するためのデータを投入する。

方針:
- **作業員マスタには一切触れない。** 作業員・勤怠・人事評価のデータは作らず、
  日報と現場配置だけが既存の作業員を「参照」する。
- 労務費は Worker.hourly_cost を使わない。実データは全員 0 のままで正しく、
  書き換えると作業員データの改変になるため、役職ごとのデモ単価で計上する。
- 入札案件は GEPS 等からの収集が済んだ想定のデータとして投入する
  （実際の収集はスクレイピング設定が必要で、このコマンドの範囲外）。
  入札参加資格（Qualification）は実データが入っているため触れない。

冪等。コード等の自然キーで get_or_create するため、何度実行しても増えない。
投入したデータだけを消して作り直したい場合は --wipe を付ける。

    python manage.py seed_demo
    python manage.py seed_demo --wipe
"""

from datetime import date, timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.bids.models import BidCompetitor, BidCost, BidProject, ScrapeTarget, UnitPrice
from apps.costs.models import BudgetItem, CostTransaction
from apps.devkanri.models import Meyasubako
from apps.masters.models import (
    CostCategory,
    Customer,
    Supplier,
    SupplierEvaluation,
    WorkStandard,
    WorkType,
)
from apps.materials.models import (
    Delivery,
    DeliveryItem,
    Inventory,
    Material,
    PurchaseOrder,
    PurchaseOrderItem,
    Quotation,
    QuotationItem,
)
from apps.notifications.models import Notification
from apps.reports.models import DailyReport, DailyReportMaterial
from apps.schedules.models import (
    Assignment,
    Milestone,
    Phase,
    PhaseTemplate,
    PhaseTemplateItem,
)
from apps.sites.models import Process, Site
from apps.tenants.models import Company
from apps.workers.models import Worker

# ---- マスタ定義 -------------------------------------------------------------

WORK_TYPES = [
    # (コード, 工種名, 親コード, 表示順)
    ("EL", "電気設備工事", None, 1),
    ("EL-01", "幹線・動力設備", "EL", 2),
    ("EL-02", "電灯・コンセント設備", "EL", 3),
    ("EL-03", "弱電・通信設備", "EL", 4),
    ("EL-04", "受変電・キュービクル", "EL", 5),
    ("AC", "空調・換気設備", None, 6),
    ("AC-01", "ダクト工事", "AC", 7),
    ("IN", "内装仕上工事", None, 8),
    ("IN-01", "軽鉄・ボード", "IN", 9),
]

CUSTOMERS = [
    ("C001", "山陽建設株式会社", "山陽　太郎", "工事部　三浦", "045-000-1101"),
    ("C002", "みなと工務店株式会社", "港　健一", "積算課　安西", "045-000-2202"),
    ("C003", "横浜市 建築局", "", "設備課　石田", "045-000-3303"),
    ("C004", "白楽不動産管理株式会社", "白楽　誠", "管理部　大野", "045-000-4404"),
    ("C005", "学校法人 青葉学園", "", "総務部　小林", "045-000-5505"),
    ("C006", "ヤマト物流株式会社", "大和　実", "施設課　中原", "045-000-6606"),
]

SUPPLIERS = [
    ("SP001", "中央電材株式会社", "電材卸。ケーブル・配線器具の主力仕入先。"),
    ("SP002", "日進電気工業株式会社", "協力会社。応援・外注工事。"),
    ("SP003", "カワイ商会", "照明器具・盤類。"),
    ("SP004", "高崎ケーブル販売株式会社", "高圧ケーブル・特注品。"),
    ("SP005", "エアテック空調株式会社", "空調・ダクト材。"),
]

MATERIALS = [
    # (コード, 材料名, 単位, 分類, 標準単価, 工種コード)
    ("M001", "VVFケーブル 2.0-2C 100m巻", "巻", "ケーブル", 12800, "EL-02"),
    ("M002", "VVFケーブル 1.6-2C 100m巻", "巻", "ケーブル", 8600, "EL-02"),
    ("M003", "CVTケーブル 38sq", "m", "ケーブル", 1450, "EL-01"),
    ("M004", "PF管 CD16 50m巻", "巻", "配管材", 2400, "EL-02"),
    ("M005", "金属管 E19 3.66m", "本", "配管材", 980, "EL-01"),
    ("M006", "分電盤 12回路 主幹50A", "面", "盤", 38000, "EL-01"),
    ("M007", "LEDベースライト 40形 逆富士", "台", "照明器具", 9800, "EL-02"),
    ("M008", "LEDダウンライト φ150", "台", "照明器具", 5400, "EL-02"),
    ("M009", "埋込コンセント 2口", "個", "配線器具", 480, "EL-02"),
    ("M010", "LANケーブル Cat6 300m箱", "箱", "通信", 18500, "EL-03"),
    ("M011", "高圧キュービクル 300kVA", "基", "受変電", 1850000, "EL-04"),
    ("M012", "スパイラルダクト φ200 4m", "本", "空調", 3200, "AC-01"),
]

WORK_STANDARDS = [
    # (工種コード, 作業名, 単位, 標準単価, 標準工数)
    ("EL-01", "幹線敷設（CVT 38sq）", "m", 2400, "0.15"),
    ("EL-01", "分電盤取付", "面", 42000, "3.50"),
    ("EL-02", "電灯配線（VVF 2.0-2C）", "m", 620, "0.08"),
    ("EL-02", "LEDベースライト取付", "台", 3800, "0.45"),
    ("EL-03", "LAN配線・成端", "端", 3200, "0.40"),
    ("EL-04", "キュービクル据付", "基", 480000, "24.00"),
]

# 役職ごとのデモ用時間単価。Worker.hourly_cost（実データは全員0）は書き換えない。
DEMO_HOURLY_COST = {
    "役員": Decimal("4500"),
    "シニア": Decimal("3800"),
    "正社員": Decimal("3200"),
    "ジュニア": Decimal("2800"),
    "試用期間": Decimal("2400"),
}
DEFAULT_HOURLY_COST = Decimal("3000")

BID_PROJECTS = [
    # (案件名, 発注者, 地域, 工事種別, 期限オフセット, 予算, 自社入札額, 状態)
    (
        "令和8年度 市営住宅電気設備改修工事（第1期）",
        "横浜市", "横浜市中区", "電気", 12, 18000000, None, "new",
    ),
    (
        "県立青葉高等学校 受変電設備更新工事",
        "神奈川県", "横浜市青葉区", "電気", 5, 24500000, None, "considering",
    ),
    (
        "市庁舎 非常用照明設備改修工事",
        "横浜市", "横浜市中区", "電気", 3, 7800000, None, "skipped",
    ),
    (
        "市立第五中学校 屋内運動場LED化工事",
        "横浜市 教育委員会", "横浜市港北区", "電気", -2, 9200000, 8740000, "bid",
    ),
    (
        "水道局 鶴見ポンプ場 動力設備更新工事",
        "横浜市 水道局", "横浜市鶴見区", "電気", -20, 31000000, 29800000, "won",
    ),
    (
        "こども自然公園 園路照明更新工事",
        "横浜市 環境創造局", "横浜市旭区", "電気", -35, 6400000, 6180000, "lost",
    ),
    (
        "市民ホール 舞台照明設備改修工事",
        "横浜市 文化観光局", "横浜市西区", "電気", 21, 15600000, None, "new",
    ),
    (
        "消防局 自家発電設備点検整備業務",
        "横浜市 消防局", "横浜市全域", "電気", 9, 4300000, None, "considering",
    ),
]

UNIT_PRICES = [
    ("電線・ケーブル", "VVFケーブル 2.0-2C", "m", 148),
    ("電線・ケーブル", "CVTケーブル 38sq", "m", 1450),
    ("配管", "PF管 CD16", "m", 62),
    ("配管", "金属管 E19", "m", 280),
    ("照明器具", "LEDベースライト 40形", "台", 9800),
    ("照明器具", "LEDダウンライト φ150", "台", 5400),
    ("盤", "分電盤 12回路", "面", 38000),
    ("労務", "電工（一般）", "人日", 26000),
]

SCRAPE_TARGETS = [
    ("政府電子調達（GEPS）", "https://www.geps.go.jp/", "全国"),
    ("横浜市 入札情報サービス", "https://www.city.yokohama.lg.jp/", "横浜市"),
    ("神奈川県 electronic bidding", "https://www.pref.kanagawa.jp/", "神奈川県"),
]

# --wipe の対象。このコマンドが作るレコードだけを消すための目印。
DEMO_SITE_CODES = ["S26-001", "S26-002", "S26-003", "S26-004", "S26-005", "S25-018"]


class Command(BaseCommand):
    help = "開発環境用のデモデータを投入（作業員マスタは対象外）"

    def add_arguments(self, parser):
        parser.add_argument(
            "--company", default="ケンモチ電機", help="投入先のテナント名",
        )
        parser.add_argument(
            "--wipe",
            action="store_true",
            help="このコマンドが投入したデータを削除してから作り直す",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        # unscoped: 管理コマンドはリクエスト外で動くためテナントを明示的に指定する。
        # 以降すべて company を明示して絞る。
        company = Company.objects.filter(name=options["company"]).first()
        if not company:
            self.stderr.write(f"会社「{options['company']}」が見つかりません。")
            return

        self.company = company
        self.today = timezone.localdate()
        self.admin = company.users.filter(is_superuser=True).first()

        if options["wipe"]:
            self._wipe()

        work_types = self._seed_work_types()
        customers = self._seed_customers()
        suppliers = self._seed_suppliers()
        self._seed_work_standards(work_types)
        self._seed_supplier_evaluations(suppliers)
        materials = self._seed_materials(work_types)
        sites = self._seed_sites(customers, work_types)
        self._seed_processes(sites, work_types)
        self._seed_schedules(sites)
        self._seed_assignments(sites)
        self._seed_purchasing(sites, suppliers, materials, work_types)
        self._seed_budget(sites, work_types)
        self._seed_daily_reports(sites, work_types, materials)
        self._seed_other_costs(sites, suppliers, work_types)
        self._seed_bids(customers)
        self._seed_notifications()

        self.stdout.write(self.style.SUCCESS("デモデータを投入しました。"))
        self._print_summary()

    # ---- 削除 -------------------------------------------------------------

    def _wipe(self):
        """このコマンドが投入したデータだけを消す。

        現場を消せば工程・工期・配置・日報・発注・予算・原価は
        カスケードで一緒に消える。
        """
        c = self.company
        Site.unscoped.filter(company=c, code__in=DEMO_SITE_CODES).delete()
        BidProject.unscoped.filter(
            company=c, title__in=[b[0] for b in BID_PROJECTS],
        ).delete()
        UnitPrice.unscoped.filter(
            company=c, item_name__in=[u[1] for u in UNIT_PRICES],
        ).delete()
        ScrapeTarget.unscoped.filter(
            company=c, name__in=[s[0] for s in SCRAPE_TARGETS],
        ).delete()
        Material.unscoped.filter(company=c, code__in=[m[0] for m in MATERIALS]).delete()
        Supplier.unscoped.filter(company=c, code__in=[s[0] for s in SUPPLIERS]).delete()
        Customer.unscoped.filter(company=c, code__in=[x[0] for x in CUSTOMERS]).delete()
        WorkType.unscoped.filter(company=c, code__in=[w[0] for w in WORK_TYPES]).delete()
        Notification.unscoped.filter(company=c, title__startswith="[デモ]").delete()
        Meyasubako.unscoped.filter(company=c, title__startswith="[デモ]").delete()
        PhaseTemplate.unscoped.filter(company=c, name="電気設備工事（標準）").delete()
        self.stdout.write("既存のデモデータを削除しました。")

    # ---- マスタ -----------------------------------------------------------

    def _seed_work_types(self):
        result = {}
        for code, name, parent_code, order in WORK_TYPES:
            obj, _ = WorkType.unscoped.get_or_create(
                company=self.company,
                code=code,
                defaults={
                    "name": name,
                    "parent": result.get(parent_code),
                    "display_order": order,
                    "created_by": self.admin,
                },
            )
            result[code] = obj
        return result

    def _seed_customers(self):
        result = {}
        for code, name, rep, contact, phone in CUSTOMERS:
            obj, _ = Customer.unscoped.get_or_create(
                company=self.company,
                code=code,
                defaults={
                    "name": name,
                    "representative": rep,
                    "contact_person": contact,
                    "phone": phone,
                    "address": "神奈川県横浜市",
                    "created_by": self.admin,
                },
            )
            result[code] = obj
        return result

    def _seed_suppliers(self):
        result = {}
        for code, name, note in SUPPLIERS:
            obj, _ = Supplier.unscoped.get_or_create(
                company=self.company,
                code=code,
                defaults={
                    "name": name,
                    "note": note,
                    "phone": "045-000-0000",
                    "address": "神奈川県横浜市",
                    "created_by": self.admin,
                },
            )
            result[code] = obj
        return result

    def _seed_work_standards(self, work_types):
        for wt_code, name, unit, unit_cost, manhours in WORK_STANDARDS:
            WorkStandard.unscoped.get_or_create(
                company=self.company,
                work_type=work_types[wt_code],
                name=name,
                defaults={
                    "unit": unit,
                    "standard_unit_cost": Decimal(unit_cost),
                    "standard_manhours": Decimal(manhours),
                    "valid_from": date(self.today.year, 4, 1),
                    "created_by": self.admin,
                },
            )

    def _seed_supplier_evaluations(self, suppliers):
        ratings = [
            ("SP001", 4, 5, 4, "ケーブル・配線器具全般。当日出荷対応あり。"),
            ("SP002", 3, 4, 5, "応援工事。仕上がりは安定している。"),
            ("SP003", 4, 3, 4, "照明器具。特注品は納期に余裕が必要。"),
            ("SP005", 3, 3, 3, "ダクト材。価格は標準的。"),
        ]
        for code, price, delivery, quality, desc in ratings:
            SupplierEvaluation.unscoped.get_or_create(
                company=self.company,
                supplier=suppliers[code],
                evaluation_date=self.today - timedelta(days=30),
                defaults={
                    "evaluator": self.admin,
                    "price_rating": price,
                    "delivery_rating": delivery,
                    "quality_rating": quality,
                    "service_description": desc,
                    "created_by": self.admin,
                },
            )

    def _seed_materials(self, work_types):
        result = {}
        for code, name, unit, category, price, wt_code in MATERIALS:
            obj, _ = Material.unscoped.get_or_create(
                company=self.company,
                code=code,
                defaults={
                    "name": name,
                    "unit": unit,
                    "category": category,
                    "standard_price": Decimal(price),
                    "work_type": work_types[wt_code],
                    "created_by": self.admin,
                },
            )
            result[code] = obj
        return result

    # ---- 現場 -------------------------------------------------------------

    def _site_defs(self):
        t = self.today
        return [
            # (コード, 現場名, 得意先, 状態, 受注金額, 開始, 終了, 工種)
            (
                "S26-001", "市立第三中学校 電気設備改修工事", "C003", "in_progress",
                12800000, t - timedelta(days=45), t + timedelta(days=30),
                ["EL-01", "EL-02"],
            ),
            (
                "S26-002", "サンライズ横浜 新築電気工事", "C001", "in_progress",
                28500000, t - timedelta(days=20), t + timedelta(days=75),
                ["EL-01", "EL-02", "EL-03"],
            ),
            (
                "S26-003", "ヤマト物流センター 受変電設備更新", "C006", "in_progress",
                9600000, t - timedelta(days=10), t + timedelta(days=25),
                ["EL-04", "EL-01"],
            ),
            (
                "S26-004", "メゾン白楽 共用部改修電気工事", "C004", "ordered",
                4200000, t + timedelta(days=14), t + timedelta(days=60),
                ["EL-02"],
            ),
            (
                "S25-018", "みなと工務店 事務所照明LED化工事", "C002", "completed",
                2350000, t - timedelta(days=180), t - timedelta(days=120),
                ["EL-02"],
            ),
            # 工期未設定。工期比較ガントで「工程から工期を補う」動きを確認できる。
            (
                "S26-005", "青葉学園 体育館照明改修工事", "C005", "estimating",
                6800000, None, None, ["EL-02"],
            ),
        ]

    def _seed_sites(self, customers, work_types):
        result = {}
        for code, name, cust, status, amount, start, end, wt_codes in self._site_defs():
            site, created = Site.unscoped.get_or_create(
                company=self.company,
                code=code,
                defaults={
                    "name": name,
                    "customer": customers[cust],
                    "status": status,
                    "contract_amount": Decimal(amount),
                    "start_date": start,
                    "end_date": end,
                    "address": "神奈川県横浜市",
                    "manager": self.admin,
                    "created_by": self.admin,
                },
            )
            if created:
                site.work_types.set([work_types[c] for c in wt_codes])
            result[code] = site
        return result

    def _seed_processes(self, sites, work_types):
        defs = [
            ("S26-001", "EL-01", "幹線・分電盤更新", -45, -10, "completed"),
            ("S26-001", "EL-02", "教室系 電灯配線・器具取付", -12, 20, "in_progress"),
            ("S26-002", "EL-01", "受電・幹線工事", -20, 15, "in_progress"),
            ("S26-002", "EL-02", "住戸内 電気配線", 10, 55, "planned"),
            ("S26-002", "EL-03", "共用部 弱電・防犯設備", 40, 72, "planned"),
            ("S26-003", "EL-04", "キュービクル据付・切替", -10, 12, "in_progress"),
            ("S26-003", "EL-01", "動力盤更新", 8, 22, "planned"),
            ("S26-004", "EL-02", "共用部 照明器具更新", 14, 55, "planned"),
        ]
        for i, (site_code, wt_code, name, s_off, e_off, status) in enumerate(defs):
            Process.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                name=name,
                defaults={
                    "work_type": work_types[wt_code],
                    "planned_start": self.today + timedelta(days=s_off),
                    "planned_end": self.today + timedelta(days=e_off),
                    "status": status,
                    "display_order": i,
                    "created_by": self.admin,
                },
            )

    # ---- 工期 -------------------------------------------------------------

    def _seed_schedules(self, sites):
        phase_defs = [
            # (現場コード, 工程名, 開始オフセット, 終了オフセット, 進捗, 色)
            ("S26-001", "仮設・準備", -45, -38, 100, "#94a3b8"),
            ("S26-001", "幹線・分電盤更新", -38, -10, 100, "#3b82f6"),
            ("S26-001", "電灯配線", -12, 12, 65, "#10b981"),
            ("S26-001", "器具取付・試験調整", 10, 28, 10, "#f59e0b"),
            ("S26-002", "着工準備・墨出し", -20, -12, 100, "#94a3b8"),
            ("S26-002", "受電・幹線工事", -12, 18, 45, "#3b82f6"),
            ("S26-002", "住戸内配線", 10, 55, 0, "#10b981"),
            ("S26-002", "弱電・防犯設備", 40, 70, 0, "#8b5cf6"),
            ("S26-003", "既設調査・切替計画", -10, -4, 100, "#94a3b8"),
            ("S26-003", "キュービクル据付", -4, 12, 55, "#3b82f6"),
            ("S26-003", "受電切替・試験", 12, 24, 0, "#ef4444"),
            ("S26-004", "共用部 照明器具更新", 14, 55, 0, "#10b981"),
            # 現場に工期が無い分、工程の日付から工期比較ガントが補完する。
            ("S26-005", "現地調査・見積", 3, 10, 0, "#94a3b8"),
        ]
        for i, (site_code, name, s_off, e_off, progress, color) in enumerate(phase_defs):
            Phase.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                name=name,
                defaults={
                    "start_date": self.today + timedelta(days=s_off),
                    "end_date": self.today + timedelta(days=e_off),
                    "progress": progress,
                    "sort_order": i,
                    "color": color,
                    "created_by": self.admin,
                },
            )

        milestones = [
            ("S26-001", "電気設備 中間検査", 14, False),
            ("S26-001", "引渡し", 30, False),
            ("S26-002", "受電完了", 18, False),
            ("S26-003", "停電作業（受電切替）", 12, False),
            ("S26-003", "官庁検査", 22, False),
        ]
        for site_code, name, off, completed in milestones:
            Milestone.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                name=name,
                defaults={
                    "target_date": self.today + timedelta(days=off),
                    "completed": completed,
                    "created_by": self.admin,
                },
            )

        template, created = PhaseTemplate.unscoped.get_or_create(
            company=self.company,
            name="電気設備工事（標準）",
            defaults={
                "description": "着工から引渡しまでの標準工程。現場作成時の雛形。",
                "created_by": self.admin,
            },
        )
        if created:
            items = [
                ("仮設・準備", 0, 7, "#94a3b8"),
                ("幹線・配管工事", 5, 40, "#3b82f6"),
                ("配線・器具取付", 35, 75, "#10b981"),
                ("試験調整・検査", 70, 90, "#f59e0b"),
            ]
            for i, (name, s_off, e_off, color) in enumerate(items):
                PhaseTemplateItem.unscoped.create(
                    company=self.company,
                    template=template,
                    name=name,
                    offset_days_start=s_off,
                    offset_days_end=e_off,
                    sort_order=i,
                    color=color,
                    created_by=self.admin,
                )

    def _field_workers(self):
        """現場に出る作業員（既存データ）。作成はしない。"""
        # unscoped: 管理コマンドはリクエスト外で動くため company を明示して絞る。
        qs = Worker.unscoped.filter(company=self.company, is_active=True)
        electricians = list(qs.filter(job_title__name="電工").order_by("employee_code"))
        return electricians or list(qs.order_by("employee_code")[:6])

    def _seed_assignments(self, sites):
        workers = self._field_workers()
        if not workers:
            self.stdout.write("作業員が0件のため、現場配置はスキップしました。")
            return

        plan = [
            ("S26-001", 0, 3, -45, 30),
            ("S26-002", 3, 6, -20, 75),
            ("S26-003", 1, 4, -10, 25),
        ]
        for site_code, start_idx, end_idx, s_off, e_off in plan:
            for worker in workers[start_idx:end_idx]:
                Assignment.unscoped.get_or_create(
                    company=self.company,
                    site=sites[site_code],
                    worker=worker,
                    start_date=self.today + timedelta(days=s_off),
                    defaults={
                        "end_date": self.today + timedelta(days=e_off),
                        "created_by": self.admin,
                    },
                )

    # ---- 材料・発注 -------------------------------------------------------

    def _seed_purchasing(self, sites, suppliers, materials, work_types):
        order_defs = [
            # (現場, 仕入先, 発注日オフセット, 状態, [(材料, 数量, 単価, 工種)])
            (
                "S26-001", "SP001", -40, "received",
                [("M001", 20, 12400, "EL-02"), ("M004", 30, 2300, "EL-02"),
                 ("M009", 120, 460, "EL-02")],
            ),
            (
                "S26-001", "SP003", -25, "received",
                [("M007", 96, 9400, "EL-02"), ("M008", 40, 5200, "EL-02")],
            ),
            (
                "S26-002", "SP001", -18, "received",
                [("M003", 420, 1420, "EL-01"), ("M005", 200, 950, "EL-01")],
            ),
            (
                "S26-002", "SP004", -6, "ordered",
                [("M003", 180, 1480, "EL-01")],
            ),
            # 予算（材料費 150万）を超える検収。原価管理で予算超過の表示を確認できる。
            (
                "S26-003", "SP003", -8, "received",
                [("M011", 1, 1780000, "EL-04")],
            ),
        ]

        for site_code, sup_code, off, status, items in order_defs:
            order_date = self.today + timedelta(days=off)
            po, created = PurchaseOrder.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                supplier=suppliers[sup_code],
                order_date=order_date,
                defaults={"status": status, "created_by": self.admin},
            )
            if not created:
                continue

            for mat_code, qty, price, wt_code in items:
                PurchaseOrderItem.unscoped.create(
                    company=self.company,
                    purchase_order=po,
                    material=materials[mat_code],
                    quantity=Decimal(qty),
                    unit_price=Decimal(price),
                    work_type=work_types[wt_code],
                    created_by=self.admin,
                )
            po.recalculate_total()

            if status != "received":
                continue

            delivery = Delivery.unscoped.create(
                company=self.company,
                purchase_order=po,
                delivery_date=order_date + timedelta(days=4),
                inspected=True,
                inspected_by=self.admin,
                inspected_at=timezone.now(),
                created_by=self.admin,
            )
            for mat_code, qty, _price, _wt in items:
                DeliveryItem.unscoped.create(
                    company=self.company,
                    delivery=delivery,
                    material=materials[mat_code],
                    ordered_qty=Decimal(qty),
                    delivered_qty=Decimal(qty),
                    created_by=self.admin,
                )

        # 検収済みの発注明細を材料費として計上する。
        # サービス層（create_material_cost_from_po_item）と同じ内容だが、
        # 再実行で二重計上しないよう get_or_create で入れる。
        material_cat = CostCategory.objects.get(code="material")
        received = PurchaseOrderItem.unscoped.filter(
            company=self.company,
            purchase_order__status="received",
        ).select_related("purchase_order")
        for item in received:
            CostTransaction.unscoped.get_or_create(
                company=self.company,
                source_type=CostTransaction.SourceType.PO_ITEM,
                source_id=item.pk,
                defaults={
                    "site": item.purchase_order.site,
                    "work_type": item.work_type,
                    "cost_category": material_cat,
                    "amount": item.quantity * item.unit_price,
                    "transaction_date": item.purchase_order.order_date,
                    "supplier": item.purchase_order.supplier,
                    "created_by": self.admin,
                },
            )

        inventory = [
            ("S26-001", "M001", 4),
            ("S26-001", "M009", 25),
            ("S26-002", "M003", 60),
            ("S26-002", "M005", 35),
        ]
        for site_code, mat_code, qty in inventory:
            Inventory.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                material=materials[mat_code],
                defaults={"quantity": Decimal(qty), "created_by": self.admin},
            )

        quotations = [
            ("S26-003", "SP003", -20, "accepted", [("M011", 1, 1780000)]),
            ("S26-003", "SP004", -20, "rejected", [("M011", 1, 1920000)]),
            ("S26-004", "SP001", -3, "received", [("M007", 48, 9600), ("M002", 12, 8500)]),
        ]
        for site_code, sup_code, off, status, items in quotations:
            quotation, created = Quotation.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                supplier=suppliers[sup_code],
                quotation_date=self.today + timedelta(days=off),
                defaults={
                    "valid_until": self.today + timedelta(days=off + 30),
                    "status": status,
                    "created_by": self.admin,
                },
            )
            if not created:
                continue
            total = Decimal(0)
            for mat_code, qty, price in items:
                amount = Decimal(qty) * Decimal(price)
                total += amount
                QuotationItem.unscoped.create(
                    company=self.company,
                    quotation=quotation,
                    material=materials[mat_code],
                    material_name=materials[mat_code].name,
                    quantity=Decimal(qty),
                    unit_price=Decimal(price),
                    amount=amount,
                    created_by=self.admin,
                )
            quotation.total_amount = total
            quotation.save(update_fields=["total_amount"])

    # ---- 予算・原価 -------------------------------------------------------

    def _seed_budget(self, sites, work_types):
        defs = [
            # (現場, 工種, 原価区分, 項目名, 単位, 数量, 単価)
            ("S26-001", "EL-01", "material", "幹線ケーブル・分電盤", "式", 1, 1850000),
            ("S26-001", "EL-01", "labor", "幹線工事 労務", "人日", 45, 26000),
            ("S26-001", "EL-02", "material", "電灯配線材・照明器具", "式", 1, 2400000),
            ("S26-001", "EL-02", "labor", "配線・器具取付 労務", "人日", 120, 26000),
            ("S26-001", "EL-02", "outsourcing", "応援（協力会社）", "人日", 20, 32000),
            ("S26-001", "EL-01", "expense", "仮設・運搬・諸経費", "式", 1, 380000),
            ("S26-002", "EL-01", "material", "受電・幹線材料", "式", 1, 4200000),
            ("S26-002", "EL-01", "labor", "受電・幹線 労務", "人日", 130, 26000),
            ("S26-002", "EL-02", "material", "住戸内配線材", "式", 1, 5600000),
            ("S26-002", "EL-02", "labor", "住戸内配線 労務", "人日", 210, 26000),
            ("S26-002", "EL-03", "material", "弱電・防犯設備", "式", 1, 1900000),
            ("S26-002", "EL-01", "expense", "現場諸経費", "式", 1, 850000),
            # 材料費を意図的に低めに置き、原価管理で予算超過の表示を確認できるようにする。
            ("S26-003", "EL-04", "material", "キュービクル一式", "式", 1, 1500000),
            ("S26-003", "EL-04", "labor", "据付・切替 労務", "人日", 38, 26000),
            ("S26-003", "EL-01", "material", "動力盤・配線材", "式", 1, 760000),
            ("S26-003", "EL-01", "expense", "停電作業 諸経費", "式", 1, 240000),
            # 実績（35万）が予算を上回る。外注費の超過を確認できる。
            ("S26-003", "EL-04", "outsourcing", "受電切替 応援", "式", 1, 200000),
            ("S26-004", "EL-02", "material", "照明器具", "式", 1, 1250000),
            ("S26-004", "EL-02", "labor", "取付 労務", "人日", 42, 26000),
        ]
        categories = {c.code: c for c in CostCategory.objects.all()}
        for site_code, wt_code, cat_code, name, unit, qty, price in defs:
            BudgetItem.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                work_type=work_types[wt_code],
                cost_category=categories[cat_code],
                name=name,
                defaults={
                    "unit": unit,
                    "quantity": Decimal(qty),
                    "unit_price": Decimal(price),
                    "amount": Decimal(qty) * Decimal(price),
                    "created_by": self.admin,
                },
            )

    def _seed_other_costs(self, sites, suppliers, work_types):
        """発注・日報から自動生成されない外注費・経費を入れる。"""
        categories = {c.code: c for c in CostCategory.objects.all()}
        defs = [
            ("S26-001", "EL-02", "outsourcing", 480000, -22, "SP002"),
            ("S26-001", "EL-01", "expense", 165000, -35, None),
            ("S26-002", "EL-01", "outsourcing", 920000, -14, "SP002"),
            ("S26-002", "EL-01", "expense", 210000, -16, None),
            ("S26-003", "EL-04", "outsourcing", 350000, -6, "SP002"),
        ]
        for site_code, wt_code, cat_code, amount, off, sup_code in defs:
            tx_date = self.today + timedelta(days=off)
            source_type = (
                CostTransaction.SourceType.OUTSOURCING
                if cat_code == "outsourcing"
                else CostTransaction.SourceType.EXPENSE
            )
            CostTransaction.unscoped.get_or_create(
                company=self.company,
                site=sites[site_code],
                work_type=work_types[wt_code],
                cost_category=categories[cat_code],
                transaction_date=tx_date,
                source_type=source_type,
                defaults={
                    "amount": Decimal(amount),
                    "supplier": suppliers[sup_code] if sup_code else None,
                    "created_by": self.admin,
                },
            )

    # ---- 日報 -------------------------------------------------------------

    def _seed_daily_reports(self, sites, work_types, materials):
        workers = self._field_workers()
        if not workers:
            self.stdout.write("作業員が0件のため、日報はスキップしました。")
            return

        labor_cat = CostCategory.objects.get(code="labor")
        plan = [
            ("S26-001", "EL-02", workers[0:3], "教室系の電灯配線および照明器具取付。"),
            ("S26-002", "EL-01", workers[3:6], "受電設備まわりの幹線敷設。"),
            ("S26-003", "EL-04", workers[1:4], "キュービクル据付および二次側結線。"),
        ]
        weather_cycle = ["sunny", "sunny", "cloudy", "rainy", "cloudy"]
        created = 0

        for day_offset in range(-20, 1):
            report_date = self.today + timedelta(days=day_offset)
            if report_date.weekday() >= 5:
                continue

            for site_code, wt_code, members, description in plan:
                site = sites[site_code]
                if site.start_date and report_date < site.start_date:
                    continue

                for i, worker in enumerate(members):
                    # 直近2日は未承認にして、承認待ちの動きを確認できるようにする。
                    if day_offset >= -1:
                        status = DailyReport.Status.DRAFT
                    elif day_offset >= -3:
                        status = DailyReport.Status.SUBMITTED
                    else:
                        status = DailyReport.Status.APPROVED

                    overtime = Decimal("1.50") if (day_offset + i) % 5 == 0 else Decimal(0)
                    work_hours = Decimal("8.00") + overtime

                    report, is_new = DailyReport.unscoped.get_or_create(
                        company=self.company,
                        site=site,
                        worker=worker,
                        report_date=report_date,
                        work_type=work_types[wt_code],
                        defaults={
                            "weather": weather_cycle[report_date.day % len(weather_cycle)],
                            "work_description": description,
                            "work_hours": work_hours,
                            "regular_hours": Decimal("8.00"),
                            "overtime_hours": overtime,
                            "status": status,
                            "approved_by": (
                                self.admin
                                if status == DailyReport.Status.APPROVED
                                else None
                            ),
                            "approved_at": (
                                timezone.now()
                                if status == DailyReport.Status.APPROVED
                                else None
                            ),
                            "created_by": self.admin,
                        },
                    )
                    if not is_new:
                        continue
                    created += 1

                    if i == 0:
                        mat = materials["M001"] if wt_code == "EL-02" else materials["M003"]
                        DailyReportMaterial.unscoped.create(
                            company=self.company,
                            daily_report=report,
                            material=mat,
                            material_name=mat.name,
                            quantity_used=Decimal("2.00"),
                            unit=mat.unit,
                            created_by=self.admin,
                        )

                    if report.status != DailyReport.Status.APPROVED:
                        continue

                    # 労務費。Worker.hourly_cost は実データが全員0のため、
                    # 作業員マスタを書き換えずに役職ごとのデモ単価で計上する。
                    position = worker.position.name if worker.position else ""
                    rate = DEMO_HOURLY_COST.get(position, DEFAULT_HOURLY_COST)
                    CostTransaction.unscoped.get_or_create(
                        company=self.company,
                        source_type=CostTransaction.SourceType.DAILY_REPORT,
                        source_id=report.pk,
                        defaults={
                            "site": site,
                            "work_type": work_types[wt_code],
                            "cost_category": labor_cat,
                            "amount": work_hours * rate,
                            "transaction_date": report_date,
                            "manhours": work_hours,
                            "created_by": self.admin,
                        },
                    )

        self.stdout.write(f"日報を {created} 件作成しました（既存の作業員を参照）。")

    # ---- 入札 -------------------------------------------------------------

    def _seed_bids(self, customers):
        """入札案件。収集（スクレイピング）が済んだ想定のデータを入れる。

        入札参加資格（Qualification）は実データが投入済みのため触れない。
        """
        projects = {}
        for title, client, region, category, off, budget, our_bid, status in BID_PROJECTS:
            project, _ = BidProject.unscoped.get_or_create(
                company=self.company,
                title=title,
                defaults={
                    "client": client,
                    "client_ref": customers["C003"] if client == "横浜市" else None,
                    "region": region,
                    "category": category,
                    "deadline": self.today + timedelta(days=off),
                    "budget": Decimal(budget),
                    "our_bid_amount": Decimal(our_bid) if our_bid else None,
                    "source_type": BidProject.SourceType.SCRAPING,
                    "source_url": "https://www.geps.go.jp/",
                    "status": status,
                    "notes": "デモデータ（収集済みとして投入）。",
                    "created_by": self.admin,
                },
            )
            projects[title] = project

        costs = [
            (3, 8100000, 0, "積算済み。応札額は歩掛から算出。"),
            (4, 27600000, 28900000, "落札。実績原価は精算ベース。"),
            (5, 5900000, 0, "失注。単価を上げすぎた。"),
        ]
        for idx, estimate, actual, memo in costs:
            BidCost.unscoped.get_or_create(
                company=self.company,
                project=projects[BID_PROJECTS[idx][0]],
                defaults={
                    "estimate_amount": Decimal(estimate),
                    "actual_cost": Decimal(actual),
                    "memo": memo,
                    "created_by": self.admin,
                },
            )

        competitors = [
            (4, "北関東電設株式会社", 30250000, "開札結果"),
            (4, "つるみ電機工業", 31400000, "開札結果"),
            (5, "旭電気工事株式会社", 5980000, "開札結果（落札）"),
        ]
        for idx, name, amount, source in competitors:
            BidCompetitor.unscoped.get_or_create(
                company=self.company,
                project=projects[BID_PROJECTS[idx][0]],
                competitor_name=name,
                defaults={
                    "competitor_amount": Decimal(amount),
                    "source": source,
                    "created_by": self.admin,
                },
            )

        for category, item_name, unit, price in UNIT_PRICES:
            UnitPrice.unscoped.get_or_create(
                company=self.company,
                item_name=item_name,
                defaults={
                    "category": category,
                    "unit": unit,
                    "unit_price": Decimal(price),
                    "created_by": self.admin,
                },
            )

        for name, url, region in SCRAPE_TARGETS:
            ScrapeTarget.unscoped.get_or_create(
                company=self.company,
                name=name,
                defaults={
                    "url": url,
                    "region": region,
                    "last_scraped_at": timezone.now() - timedelta(hours=6),
                    "created_by": self.admin,
                },
            )

    # ---- 通知・目安箱 -----------------------------------------------------

    def _seed_notifications(self):
        if not self.admin:
            return

        notifications = [
            (
                "[デモ] 入札期限が近づいています",
                "「県立青葉高等学校 受変電設備更新工事」の入札期限まで5日です。",
                "warning", "bids", "/bids/",
            ),
            (
                "[デモ] 実行予算を超過しました",
                "ヤマト物流センター 受変電設備更新：受変電・キュービクルの"
                "材料費と外注費が実行予算を超過しています。",
                "error", "costs", "/costs/",
            ),
            (
                "[デモ] 未承認の日報があります",
                "承認待ちの日報が溜まっています。内容を確認してください。",
                "info", "reports", "/reports/",
            ),
            (
                "[デモ] 工期のマイルストーンが近づいています",
                "ヤマト物流センター：停電作業（受電切替）まで12日です。",
                "info", "schedules", "/schedules/",
            ),
        ]
        for title, body, level, module, url in notifications:
            Notification.unscoped.get_or_create(
                company=self.company,
                recipient=self.admin,
                title=title,
                defaults={
                    "body": body,
                    "level": level,
                    "module": module,
                    "reference_url": url,
                    "created_by": self.admin,
                },
            )

        meyasubako = [
            (
                "[デモ] 日報の入力に時間がかかる",
                "usability", "reports",
                "現場から戻ってから毎日入力しているが、項目が多くて時間がかかる。",
                "よく使う作業内容を選ぶだけで入力できるようにしてほしい。",
                "not_urgent",
            ),
            (
                "[デモ] 発注書のPDFが開けないことがある",
                "bug", "materials",
                "発注書のPDFを開こうとするとエラーになることがある。",
                "スマホからでも開けるようにしてほしい。",
                "urgent",
            ),
        ]
        for title, kind, module, problem, wish, urgency in meyasubako:
            Meyasubako.unscoped.get_or_create(
                company=self.company,
                title=title,
                defaults={
                    "reporter": self.admin,
                    "reporter_name": "デモユーザー",
                    "kind": kind,
                    "module": module,
                    "problem": problem,
                    "wish": wish,
                    "urgency": urgency,
                    "created_by": self.admin,
                },
            )

    # ---- 出力 -------------------------------------------------------------

    def _print_summary(self):
        c = self.company
        rows = [
            ("工種", WorkType.unscoped.filter(company=c).count()),
            ("得意先", Customer.unscoped.filter(company=c).count()),
            ("仕入先", Supplier.unscoped.filter(company=c).count()),
            ("材料", Material.unscoped.filter(company=c).count()),
            ("現場", Site.unscoped.filter(company=c).count()),
            ("工程", Process.unscoped.filter(company=c).count()),
            ("工期フェーズ", Phase.unscoped.filter(company=c).count()),
            ("現場配置", Assignment.unscoped.filter(company=c).count()),
            ("日報", DailyReport.unscoped.filter(company=c).count()),
            ("発注書", PurchaseOrder.unscoped.filter(company=c).count()),
            ("実行予算", BudgetItem.unscoped.filter(company=c).count()),
            ("原価データ", CostTransaction.unscoped.filter(company=c).count()),
            ("入札案件", BidProject.unscoped.filter(company=c).count()),
            ("通知", Notification.unscoped.filter(company=c).count()),
        ]
        for label, count in rows:
            self.stdout.write(f"  {label:12s} {count:5d} 件")

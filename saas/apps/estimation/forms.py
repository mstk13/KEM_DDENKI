"""積算アプリのフォーム。"""

from django import forms

# 候補から選び、無ければその場でマスタに登録する（ADR-0099）
from apps.core.master_input import (
    name_choices,
    resolve_customer,
    resolve_estimation_item,
    resolve_material,
    resolve_site,
    resolve_supplier,
    resolve_work_type,
)
from apps.estimation.models import (
    BoqLine,
    EstimationCompetitor,
    EstimationDocument,
    EstimationItem,
    EstimationPhase,
    EstimationProject,
    EstimationStandard,
    ItemAlias,
    Orderer,
    OrdererDataSource,
    PurchaseRecord,
    WorkRate,
)


class EstimationItemForm(forms.ModelForm):
    """積算品目の登録・編集。

    材料と工種は**自由入力**にしている（ADR-0099）。候補に無いものを選ぼうとした
    時点で「先に材料マスタへ登録してから戻る」という往復が要り、品目の登録が止まる。
    """

    material_name = forms.CharField(
        label="材料", required=False,
        help_text="登録済みの材料は候補から選べます。候補に無い名前を入力すると材料マスタにも登録されます。",
    )
    work_type_name = forms.CharField(
        label="工種", required=False,
        help_text="登録済みの工種は候補から選べます。候補に無い名前を入力すると工種マスタにも登録されます。",
    )

    class Meta:
        model = EstimationItem
        fields = [
            "code",
            "canonical_name",
            "category",
            "unit",
            "spec",
            "standard_price",
            "status",
            "notes",
        ]
        widgets = {
            "spec": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._company = company
        self._user = user
        if company:
            from apps.masters.models import WorkType
            from apps.materials.models import Material

            # 入力補助の候補。datalist なのでこの一覧に無い値も送信できる
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.material_choices = name_choices(
                Material.unscoped.filter(company=company, is_active=True),
            )
            self.work_type_choices = name_choices(
                WorkType.unscoped.filter(company=company, is_active=True),
            )
        else:
            self.material_choices = []
            self.work_type_choices = []

        self.fields["material_name"].widget.attrs["list"] = "material-name-options"
        self.fields["work_type_name"].widget.attrs["list"] = "work-type-name-options"
        if self.instance.pk:
            if self.instance.material_id:
                self.fields["material_name"].initial = self.instance.material.name
            if self.instance.work_type_id:
                self.fields["work_type_name"].initial = self.instance.work_type.name

        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

    def save(self, commit=True):
        item = super().save(commit=False)
        company = self._company or (item.company if item.company_id else None)
        if company is not None:
            unit = self.cleaned_data.get("unit", "")
            item.material = resolve_material(
                company, self.cleaned_data.get("material_name", ""),
                unit=unit, created_by=self._user,
            )
            item.work_type = resolve_work_type(
                company, self.cleaned_data.get("work_type_name", ""),
                created_by=self._user,
            )
        if commit:
            item.save()
            self.save_m2m()
        return item


class ItemAliasReviewForm(forms.ModelForm):
    """名寄せレビュー用。紐付先品目の選択と状態変更。"""

    class Meta:
        model = ItemAlias
        fields = ["estimation_item", "status", "notes"]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["estimation_item"].queryset = (
                EstimationItem.unscoped.filter(company=company, is_active=True)
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class OrdererForm(forms.ModelForm):
    """発注機関の登録・編集。紐づく顧客は自由入力（ADR-0099）。"""

    # ラベルは画面に出ている文言に合わせる。テンプレートに "顧客マスタ" と
    # 手書きされ、ここの label="顧客" と食い違っていた。検証エラーの文面だけ
    # 「顧客」になる状態だったので、見えている側に寄せた。
    customer_name = forms.CharField(
        label="顧客マスタ", required=False,
        help_text="登録済みの顧客は候補から選べます。候補に無い名前を入力すると顧客マスタにも登録されます。",
    )

    class Meta:
        model = Orderer
        fields = [
            "code",
            "name",
            "kind",
            "system_type",
            "prefecture",
            "standard_url",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._company = company
        self._user = user
        if company:
            from apps.masters.models import Customer

            # 入力補助の候補。datalist なのでこの一覧に無い値も送信できる
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.customer_choices = name_choices(
                Customer.unscoped.filter(company=company, is_active=True),
            )
        else:
            self.customer_choices = []

        self.fields["customer_name"].widget.attrs["list"] = "customer-name-options"
        if self.instance.pk and self.instance.customer_id:
            self.fields["customer_name"].initial = self.instance.customer.name

        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

    def save(self, commit=True):
        orderer = super().save(commit=False)
        company = self._company or (orderer.company if orderer.company_id else None)
        if company is not None:
            orderer.customer = resolve_customer(
                company, self.cleaned_data.get("customer_name", ""), created_by=self._user,
            )
        if commit:
            orderer.save()
            self.save_m2m()
        return orderer


class OrdererDataSourceForm(forms.ModelForm):
    class Meta:
        model = OrdererDataSource
        fields = [
            "category",
            "scope",
            "name",
            "source_url",
            "update_cycle",
            "data_format",
            "is_free",
            "fiscal_year",
            "last_checked_at",
            "diff_summary",
            "notes",
        ]
        widgets = {
            "diff_summary": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "last_checked_at": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.CheckboxInput)):
                field.widget.attrs.setdefault("class", "form-control")


class LaborRateImportForm(forms.Form):
    """労務単価インポートフォーム。Excel/PDF対応。"""

    IMPORT_TYPE_CHOICES = [
        ("excel", "社内整形済みExcel"),
        ("pdf", "国交省PDF（AI構造化）"),
    ]

    import_type = forms.ChoiceField(
        label="インポート種別",
        choices=IMPORT_TYPE_CHOICES,
        initial="excel",
        widget=forms.RadioSelect,
    )
    file = forms.FileField(
        label="ファイル",
        help_text="Excel(.xlsx) または PDF(.pdf)",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".xlsx,.xls,.pdf"}),
    )
    valid_from = forms.DateField(
        label="適用開始日",
        help_text="例: 2026-03-01",
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
    )
    fiscal_year_label = forms.CharField(
        label="年度表記",
        required=False,
        help_text="例: 令和8年3月適用",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )


class EstimationStandardForm(forms.ModelForm):
    class Meta:
        model = EstimationStandard
        fields = [
            "orderer",
            "name",
            "valid_from",
            "valid_to",
            "applies_by",
            "fiscal_year_label",
            "source_url",
            "source_file",
            "status",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "valid_from": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "valid_to": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["orderer"].queryset = Orderer.unscoped.filter(
                company=company, is_active=True,
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.FileInput)):
                field.widget.attrs.setdefault("class", "form-control")


class WorkRateForm(forms.ModelForm):
    class Meta:
        model = WorkRate
        fields = [
            "work_code",
            "work_name",
            "unit",
            "labor",
            "material",
            "remarks",
            "status",
            "extracted_by",
            "source_page",
            "notes",
        ]
        widgets = {
            "labor": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "material": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


# ===================================================================
# M3: 積算案件・内訳書
# ===================================================================


class EstimationProjectForm(forms.ModelForm):
    """積算案件の登録・編集フォーム。

    発注機関と積算担当者は**自由入力**にしている（ADR-0080）。
    公告を見ながら積算を始める時点で、マスタに無い発注機関は珍しくない。
    プルダウンだけだと「先に発注機関マスタへ登録してから案件を作る」という
    2画面の往復が要り、積算そのものが止まる。
    入力値は resolve_or_create_orderer が引き当て、未登録なら発注機関マスタに登録する。
    """

    orderer_name = forms.CharField(
        label="発注機関",
        help_text="登録済みの機関は候補から選べます。候補に無い機関名を直接入力すると発注機関マスタにも登録されます。",
    )
    estimator_name = forms.CharField(
        label="積算担当者",
        required=False,
        help_text="過去に入力した担当者は候補から選べます。",
    )
    site_name = forms.CharField(
        label="現場",
        required=False,
        help_text="登録済みの現場は候補から選べます。候補に無い名前を入力すると現場も登録されます。",
    )

    class Meta:
        model = EstimationProject
        fields = [
            "name", "standard", "bid_project",
            "primary_work_category", "status",
            "bid_announcement_date", "bid_opening_date",
            "construction_period_days", "construction_end_date",
            "estimator_name",
            "bid_amount", "award_amount", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "bid_announcement_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "bid_opening_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "construction_end_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, company=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._company = company
        self._user = user
        if company:
            from apps.bids.models import BidProject
            from apps.sites.models import Site

            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["standard"].queryset = EstimationStandard.unscoped.filter(company=company)
            self.fields["bid_project"].queryset = BidProject.unscoped.filter(company=company)
            # 現場名の候補（ADR-0099）。既にある現場が打ちかけで出るので、
            # 同じ現場を別名で二重に作ってしまう手前で気づける（ADR-0077 と同じ考え方）
            self.site_choices = name_choices(Site.unscoped.filter(company=company))
            # 入力補助の候補。datalist なのでこの一覧に無い値も送信できる。
            self.orderer_choices = list(
                Orderer.unscoped.filter(company=company, is_active=True)
                .order_by("name")
                .values_list("name", flat=True)
            )
            # 担当者はマスタを持たない。**過去に入れた値そのもの**を候補にする。
            # 誰が積算したかは人の入れ替わりで変わるので、マスタにすると
            # 使わなくなった名前を消す手間が残る（ADR-0080）。
            self.estimator_choices = sorted(
                name for name in set(
                    EstimationProject.unscoped
                    .filter(company=company)
                    .exclude(estimator_name="")
                    .values_list("estimator_name", flat=True)
                ) if name
            )
        else:
            self.orderer_choices = []
            self.estimator_choices = []
            self.site_choices = []

        self.fields["orderer_name"].widget.attrs["list"] = "orderer-name-options"
        self.fields["site_name"].widget.attrs["list"] = "site-name-options"
        if self.instance.pk and self.instance.site_id:
            self.fields["site_name"].initial = self.instance.site.name
        self.fields["estimator_name"].widget.attrs["list"] = "estimator-name-options"
        if self.instance.pk and self.instance.orderer_id:
            self.fields["orderer_name"].initial = self.instance.orderer.name

        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

    def clean_construction_end_date(self):
        """工期末日は開札予定日より前にならない。打ち間違いをここで止める。"""
        end = self.cleaned_data.get("construction_end_date")
        opening = self.cleaned_data.get("bid_opening_date")
        if end and opening and end < opening:
            raise forms.ValidationError(
                "工期末日が開札予定日より前になっています。日付を確認してください。",
            )
        return end

    def save(self, commit=True):
        from apps.estimation.services.from_bid import resolve_or_create_orderer

        project = super().save(commit=False)
        # 新規登録では project.company をビューが後から入れるので、
        # フォームに渡された company を優先する（現場の顧客欄と同じ方針）。
        company = self._company or (project.company if project.company_id else None)
        if company is not None:
            orderer = resolve_or_create_orderer(
                company, self.cleaned_data.get("orderer_name"), created_by=self._user,
            )
            if orderer is not None:
                project.orderer = orderer
            project.site = resolve_site(
                company, self.cleaned_data.get("site_name", ""), created_by=self._user,
            )
        if commit:
            project.save()
            self.save_m2m()
        return project


class BoqLineForm(forms.ModelForm):
    """内訳書の明細。紐づく積算品目は自由入力（ADR-0099）。

    親明細・歩掛は自由入力に**しない**。どちらもマスタではなく、
    同じ内訳書の行と積算基準に属する計算データで、名前から作れるものではない。
    """

    estimation_item_name = forms.CharField(
        label="積算品目", required=False,
        help_text="登録済みの品目は候補から選べます。候補に無い名前を入力すると品目マスタにも登録されます。",
    )

    class Meta:
        model = BoqLine
        fields = [
            "level", "parent", "sort_order", "name", "spec", "unit",
            "quantity", "unit_price", "amount",
            "work_rate", "remarks",
        ]
        widgets = {
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, project=None, site=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._company = company
        self._user = user
        if company:
            # 入力補助の候補。datalist なのでこの一覧に無い値も送信できる
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.estimation_item_choices = name_choices(
                EstimationItem.unscoped.filter(company=company, is_active=True),
                field="canonical_name",
            )
        else:
            self.estimation_item_choices = []

        self.fields["estimation_item_name"].widget.attrs["list"] = "estimation-item-options"
        if self.instance.pk and self.instance.estimation_item_id:
            self.fields["estimation_item_name"].initial = (
                self.instance.estimation_item.canonical_name
            )
        if project:
            self.fields["work_rate"].queryset = WorkRate.unscoped.filter(
                company=project.company, standard=project.standard,
            ) if project.standard else WorkRate.objects.none()
        else:
            # 現場から作る内訳書は積算基準に紐づかないので歩掛は選ばせない。
            self.fields["work_rate"].queryset = WorkRate.objects.none()

        # 親明細は同じ内訳書の中からしか選べない。
        # ここを絞らないと他現場の明細にぶら下げられてしまう。
        owner = {"project": project} if project is not None else {"site": site}
        if any(v is not None for v in owner.values()):
            queryset = BoqLine.objects.filter(**owner).order_by("sort_order")
            if self.instance.pk:
                queryset = queryset.exclude(pk=self.instance.pk)
            self.fields["parent"].queryset = queryset
        else:
            self.fields["parent"].queryset = BoqLine.objects.none()

        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

    def save(self, commit=True):
        line = super().save(commit=False)
        company = self._company or (line.company if line.company_id else None)
        if company is not None:
            # 単位は明細の欄から渡す。品目マスタの必須項目で、聞き直すと入力が止まる
            line.estimation_item = resolve_estimation_item(
                company, self.cleaned_data.get("estimation_item_name", ""),
                unit=self.cleaned_data.get("unit", ""), created_by=self._user,
            )
        if commit:
            line.save()
            self.save_m2m()
        return line


# ===================================================================
# M4: 仕入実績
# ===================================================================


class PurchaseRecordForm(forms.ModelForm):
    """仕入実績の登録・編集。発注先は自由入力（ADR-0099）。"""

    supplier_name = forms.CharField(
        label="発注先", required=False,
        help_text="登録済みの発注先は候補から選べます。候補に無い名前を入力すると発注先マスタにも登録されます。",
    )

    class Meta:
        model = PurchaseRecord
        fields = [
            "raw_name", "raw_code", "purchase_date", "quantity",
            "unit", "unit_price", "amount", "notes",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._company = company
        self._user = user
        if company:
            from apps.masters.models import Supplier

            # 入力補助の候補。datalist なのでこの一覧に無い値も送信できる
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.supplier_choices = name_choices(
                Supplier.unscoped.filter(company=company, is_active=True),
            )
        else:
            self.supplier_choices = []

        self.fields["supplier_name"].widget.attrs["list"] = "supplier-name-options"
        if self.instance.pk and self.instance.supplier_id:
            self.fields["supplier_name"].initial = self.instance.supplier.name

        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

    def save(self, commit=True):
        record = super().save(commit=False)
        company = self._company or (record.company if record.company_id else None)
        if company is not None:
            record.supplier = resolve_supplier(
                company, self.cleaned_data.get("supplier_name", ""), created_by=self._user,
            )
        if commit:
            record.save()
            self.save_m2m()
        return record


class PurchaseCSVImportForm(forms.Form):
    """仕入実績 CSV インポートフォーム。"""

    file = forms.FileField(
        label="CSVファイル",
        help_text="ヘッダー: 仕入日,品名,品番,数量,単位,単価,金額,仕入先名,備考",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".csv"}),
    )
    auto_match = forms.BooleanField(
        label="名寄せを同時実行",
        required=False,
        initial=True,
    )


# ===================================================================
# 内訳書の表形式入力（現場詳細から使う）
# ===================================================================


class BoqLineRowForm(forms.ModelForm):
    """内訳書を表形式で編集するための1行分。

    親子は選ばせない。行の並びと階層から組み立て直す（`rebuild_tree`）。
    表の中に「親明細」のセレクトを置くと、行を並べ替えるたびに
    人が親を選び直すことになり、まず維持できない。
    """

    class Meta:
        model = BoqLine
        fields = [
            "level", "name", "spec", "unit",
            "quantity", "unit_price", "amount", "remarks",
        ]
        widgets = {
            "remarks": forms.TextInput(attrs={"class": "form-control"}),
            "name": forms.TextInput(attrs={"class": "form-control", "placeholder": "名称"}),
            "spec": forms.TextInput(attrs={"class": "form-control", "placeholder": "仕様"}),
            "unit": forms.TextInput(attrs={"class": "form-control", "placeholder": "単位"}),
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.001"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
            "amount": forms.NumberInput(attrs={"class": "form-control", "step": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["level"].widget.attrs.setdefault("class", "form-control")
        # 空行を送っても検証で弾かれないようにする。
        # 「5行ぶんの入力欄を出しておいて2行だけ埋める」が普通の使い方。
        for name in self.fields:
            self.fields[name].required = False

    def clean(self):
        cleaned = super().clean()
        name = (cleaned.get("name") or "").strip()
        if not name:
            # 名称が空の行は入力されなかった行として捨てる。
            return cleaned
        if not cleaned.get("level"):
            # 階層の指定が無ければ、数量か単価があるものを内訳明細書とみなす。
            has_numbers = any(
                cleaned.get(key) is not None
                for key in ("quantity", "unit_price", "amount")
            )
            cleaned["level"] = (
                BoqLine.MEISAI_LEVEL if has_numbers else BoqLine.Level.KAMOKU
            )
        return cleaned


BoqLineRowFormSet = forms.modelformset_factory(
    BoqLine, form=BoqLineRowForm, extra=5, can_delete=True,
)


class BoqImportForm(forms.Form):
    """内訳書ファイル（Excel / PDF）の取込。"""

    upload = forms.FileField(
        label="内訳書ファイル",
        help_text="Excel(.xlsx) または PDF(.pdf)。名称・数量・単価・金額の列がある表を読みます。",
        widget=forms.ClearableFileInput(attrs={
            "class": "form-control", "accept": ".xlsx,.xlsm,.pdf",
        }),
    )
    replace = forms.BooleanField(
        label="既存の内訳書を置き換える",
        required=False,
        initial=True,
        help_text="外すと今ある明細の後ろに追加します。同じファイルを2回読むと行が重複します。",
    )


class EstimationWonForm(forms.Form):
    """受注の確定。落札額と結果確定日を入れて現場管理へ渡す（ADR-0076）。"""

    award_amount = forms.DecimalField(
        label="落札額（円）", max_digits=14, decimal_places=0, required=False,
        widget=forms.NumberInput(attrs={"class": "form-control"}),
        help_text="空のままなら積算案件の落札額と現場の受注金額は変えません",
    )
    decided_on = forms.DateField(
        label="結果確定日", required=False,
        widget=forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        help_text="空のままなら今日の日付が入ります",
    )


class EstimationLostForm(forms.ModelForm):
    """失注の確定。原因の区分とメモを入れる（ADR-0076）。

    競合の社名と金額は EstimationCompetitorForm で別に足す。
    1社とは限らず、後から分かることもあるため同じ画面で完結させない。
    """

    class Meta:
        model = EstimationProject
        fields = ["lost_reason", "lost_note", "decided_on"]
        widgets = {
            "lost_reason": forms.Select(attrs={"class": "form-control"}),
            "lost_note": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "decided_on": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lost_reason"].required = True
        self.fields["decided_on"].help_text = "空のままなら今日の日付が入ります"


class EstimationCompetitorForm(forms.ModelForm):
    """競合1社分。差額は自社応札額から計算して表示するので入力欄は持たない。"""

    class Meta:
        model = EstimationCompetitor
        fields = ["name", "amount", "is_winner", "memo"]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }


class EstimationPhaseForm(forms.ModelForm):
    """積算工程。現場管理の工程フェーズと同じ項目立てにする（ADR-0076）。"""

    class Meta:
        model = EstimationPhase
        fields = [
            "name", "start_date", "end_date", "progress",
            "sort_order", "color", "memo",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": "form-control"}),
            "start_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "end_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "progress": forms.NumberInput(
                attrs={"class": "form-control", "min": 0, "max": 100},
            ),
            "sort_order": forms.NumberInput(attrs={"class": "form-control"}),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and start > end:
            raise forms.ValidationError("終了日は開始日より後にしてください。")
        return cleaned


def registrant_name(user) -> str:
    """ログインしている人を、画面に出す名前にする。

    作業員が紐づいていれば氏名。無ければ利用者の表示名。
    どちらも空になることはあるので、その場合は空文字のまま返す。
    """
    if user is None or not getattr(user, "is_authenticated", False):
        return ""
    worker = getattr(user, "worker_profile", None)
    if worker is not None and worker.name:
        return worker.name[:100]
    return (user.get_full_name() or user.get_username() or "")[:100]


def _past_values(company, field: str) -> list[str]:
    """会社の案件資料に過去に入った値を、重複なく並べる。"""
    if company is None:
        return []
    # unscoped: フォーム初期化時に会社を明示フィルタするため
    return sorted(
        value for value in set(
            EstimationDocument.unscoped
            .filter(company=company)
            .exclude(**{field: ""})
            .values_list(field, flat=True)
        ) if value
    )


class EstimationDocumentForm(forms.Form):
    """積算案件に資料を1件足す（ADR-0080）。

    受け取れる形式と大きさの決まりは apps.core.documents に揃える
    （現場の提出書類・自社書類と同じ規則）。
    """

    from apps.core.documents import ACCEPT_ATTR as _ACCEPT_ATTR
    from apps.core.documents import MAX_DOCUMENT_FILE_MB as _MAX_MB

    name = forms.CharField(
        label="資料名", max_length=200, required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
        help_text="空のままならファイル名をそのまま使います。",
    )
    doc_type = forms.ChoiceField(
        label="種別",
        choices=[],  # __init__ でモデルの選択肢を入れる
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    file = forms.FileField(
        label="ファイル",
        widget=forms.ClearableFileInput(
            attrs={"class": "form-control", "accept": _ACCEPT_ATTR},
        ),
        help_text=f"PDF（.pdf）と Excel（.xlsx・.xls）。1件 {_MAX_MB}MB まで。",
    )
    provided_by = forms.CharField(
        label="提供元", max_length=100, required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "list": "doc-provided-by-options"},
        ),
        help_text="誰からもらった資料か。過去に入力した提供元は候補から選べます。",
    )
    registered_by_name = forms.CharField(
        label="登録者", max_length=100, required=False,
        widget=forms.TextInput(
            attrs={"class": "form-control", "list": "doc-registered-by-options"},
        ),
        help_text="空のままならログインしている人の名前が入ります。",
    )
    memo = forms.CharField(
        label="メモ", required=False,
        widget=forms.Textarea(attrs={"rows": 2, "class": "form-control"}),
    )

    def __init__(self, *args, company=None, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["doc_type"].choices = EstimationDocument.DocType.choices
        self.fields["doc_type"].initial = EstimationDocument.DocType.ANNOUNCEMENT

        # 提供元・登録者はマスタを持たない。**過去に入れた値そのもの**を候補にする。
        # 積算担当者（ADR-0080）と同じ理由で、マスタにすると使わなくなった名前を
        # 消す手間が残る。窓口の担当者は人の入れ替わりで変わる。
        self.provided_by_choices = _past_values(company, "provided_by")
        self.registered_by_choices = _past_values(company, "registered_by_name")

        # 既定は今ログインしている人。代理で登録するときだけ書き換える。
        if user is not None:
            self.fields["registered_by_name"].initial = registrant_name(user)

    def clean_file(self):
        """PDF・Excel であることと、大きさを確かめる。"""
        from apps.core.documents import (
            MAX_DOCUMENT_FILE_MB,
            UnsupportedDocumentFile,
            detect_file_kind,
        )

        uploaded = self.cleaned_data["file"]
        limit = MAX_DOCUMENT_FILE_MB * 1024 * 1024
        if uploaded.size > limit:
            raise forms.ValidationError(
                f"ファイルが大きすぎます（1件 {MAX_DOCUMENT_FILE_MB}MB まで）。",
            )
        try:
            self._kind = detect_file_kind(uploaded)
        except UnsupportedDocumentFile as exc:
            raise forms.ValidationError(str(exc)) from exc
        return uploaded

    @property
    def kind(self):
        """clean_file が見分けた形式。保存するビューが使う。"""
        return getattr(self, "_kind", EstimationDocument.Kind.PDF)

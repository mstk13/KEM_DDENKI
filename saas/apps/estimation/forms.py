"""積算アプリのフォーム。"""

from django import forms

from apps.estimation.models import (
    BoqLine,
    EstimationItem,
    EstimationProject,
    EstimationStandard,
    ItemAlias,
    Orderer,
    OrdererDataSource,
    PurchaseRecord,
    WorkRate,
)


class EstimationItemForm(forms.ModelForm):
    class Meta:
        model = EstimationItem
        fields = [
            "code",
            "canonical_name",
            "category",
            "unit",
            "spec",
            "standard_price",
            "material",
            "work_type",
            "status",
            "notes",
        ]
        widgets = {
            "spec": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            from apps.masters.models import WorkType
            from apps.materials.models import Material

            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["material"].queryset = Material.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


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
    class Meta:
        model = Orderer
        fields = [
            "code",
            "name",
            "kind",
            "system_type",
            "prefecture",
            "standard_url",
            "customer",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            from apps.masters.models import Customer

            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["customer"].queryset = Customer.unscoped.filter(
                company=company, is_active=True,
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


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
    class Meta:
        model = EstimationProject
        fields = [
            "name", "orderer", "standard", "site", "bid_project",
            "primary_work_category", "status",
            "bid_announcement_date", "bid_opening_date",
            "construction_period_days", "bid_amount", "award_amount", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "bid_announcement_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
            "bid_opening_date": forms.DateInput(
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            from apps.bids.models import BidProject
            from apps.sites.models import Site

            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["orderer"].queryset = Orderer.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["standard"].queryset = EstimationStandard.unscoped.filter(company=company)
            self.fields["site"].queryset = Site.unscoped.filter(company=company)
            self.fields["bid_project"].queryset = BidProject.unscoped.filter(company=company)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


class BoqLineForm(forms.ModelForm):
    class Meta:
        model = BoqLine
        fields = [
            "level", "sort_order", "name", "spec", "unit",
            "quantity", "unit_price", "amount",
            "estimation_item", "work_rate", "remarks",
        ]
        widgets = {
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, project=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["estimation_item"].queryset = EstimationItem.unscoped.filter(
                company=company, is_active=True,
            )
        if project:
            self.fields["work_rate"].queryset = WorkRate.unscoped.filter(
                company=project.company, standard=project.standard,
            ) if project.standard else WorkRate.objects.none()
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


# ===================================================================
# M4: 仕入実績
# ===================================================================


class PurchaseRecordForm(forms.ModelForm):
    class Meta:
        model = PurchaseRecord
        fields = [
            "raw_name", "raw_code", "purchase_date", "quantity",
            "unit", "unit_price", "amount", "supplier", "notes",
        ]
        widgets = {
            "purchase_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            from apps.masters.models import Supplier

            # unscoped: フォーム初期化時に会社を明示フィルタするため
            self.fields["supplier"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")


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

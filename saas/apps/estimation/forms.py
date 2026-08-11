"""積算アプリのフォーム。"""

from django import forms

from apps.estimation.models import (
    EstimationItem,
    EstimationStandard,
    ItemAlias,
    Orderer,
    OrdererDataSource,
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
        for name, field in self.fields.items():
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
        for name, field in self.fields.items():
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
        for name, field in self.fields.items():
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
        for name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.CheckboxInput)):
                field.widget.attrs.setdefault("class", "form-control")


class LaborRateImportForm(forms.Form):
    """労務単価 Excel インポートフォーム。

    注意: 国交省はPDFのみ配布。このフォームは社内整形済みExcel用。
    """

    file = forms.FileField(
        label="Excelファイル",
        help_text="社内整形済みの労務単価 Excel（公式PDFからの取込は別機能）",
        widget=forms.FileInput(attrs={"class": "form-control", "accept": ".xlsx,.xls"}),
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
        for name, field in self.fields.items():
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
        for name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

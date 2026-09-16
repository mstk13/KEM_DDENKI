"""積算アプリのフォーム。"""

from django import forms

from apps.estimation.models import (
    BoqLine,
    EstimationCompetitor,
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
            "level", "parent", "sort_order", "name", "spec", "unit",
            "quantity", "unit_price", "amount",
            "estimation_item", "work_rate", "remarks",
        ]
        widgets = {
            "remarks": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, project=None, site=None, **kwargs):
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
    """受注の確定。落札額と結果確定日を入れて現場管理へ渡す（ADR-0070）。"""

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
    """失注の確定。原因の区分とメモを入れる（ADR-0070）。

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
    """積算工程。現場管理の工程フェーズと同じ項目立てにする（ADR-0070）。"""

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

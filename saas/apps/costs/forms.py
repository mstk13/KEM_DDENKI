from django import forms

from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import CostCategory, WorkType
from apps.sites.forms import EstimateUploadForm
from apps.sites.models import Site


class BudgetImportForm(EstimateUploadForm):
    """見積書を読み込んで実行予算を起こすための受け口。

    ファイルの検証（対応拡張子・旧 .xls の案内）は見積取り込みと同じものを
    使う。読み方を2箇所で持つと、片方だけ直したときに挙動がずれる。

    工種と原価区分は見積書に書かれていないので、ここで既定値を選んでもらう。
    確認画面で行ごとに変えられるが、既定が無いと全行を選び直すことになる。
    """

    site = forms.ModelChoiceField(
        label="現場", queryset=Site.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    default_work_type = forms.ModelChoiceField(
        label="工種の既定値", queryset=WorkType.objects.none(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )
    default_cost_category = forms.ModelChoiceField(
        label="原価区分の既定値", queryset=CostCategory.objects.all(),
        widget=forms.Select(attrs={"class": "form-control"}),
    )

    field_order = ["site", "default_work_type", "default_cost_category", "file"]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            # unscoped: 取り込み経路はテナントコンテキスト未設定で通ることが
            # あるため company を明示して絞る。
            self.fields["site"].queryset = Site.unscoped.filter(
                company=company,
            ).exclude(status=Site.Status.CANCELLED).order_by("-created_at")
            self.fields["default_work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )
        # 材料費を既定に置く。見積書の明細は材料が大半を占める。
        material = CostCategory.objects.filter(name="材料費").first()
        if material:
            self.fields["default_cost_category"].initial = material.pk


class BudgetItemForm(forms.ModelForm):
    class Meta:
        model = BudgetItem
        fields = ["work_type", "cost_category", "name", "unit", "quantity", "unit_price", "amount"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "amount": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )


class ManualCostForm(forms.ModelForm):
    """手動原価入力フォーム（外注費・経費）。"""

    class Meta:
        model = CostTransaction
        fields = [
            "site", "work_type", "cost_category", "amount", "transaction_date",
            "source_type", "supplier",
        ]
        widgets = {
            "transaction_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "amount": forms.NumberInput(attrs={"class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        # 手動入力は外注・経費のみ
        self.fields["source_type"].choices = [
            (CostTransaction.SourceType.OUTSOURCING, "外注"),
            (CostTransaction.SourceType.EXPENSE, "経費"),
        ]
        if company:
            from apps.masters.models import Supplier
            self.fields["site"].queryset = Site.unscoped.filter(company=company)
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["supplier"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["supplier"].required = False

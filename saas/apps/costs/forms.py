from django import forms

from apps.costs.models import BudgetItem, CostTransaction
from apps.masters.models import CostCategory, WorkType
from apps.sites.models import Site


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
        fields = ["site", "work_type", "cost_category", "amount", "transaction_date", "source_type", "supplier"]
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

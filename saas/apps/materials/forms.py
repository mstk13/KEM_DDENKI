from django import forms

from apps.masters.models import Supplier, WorkType
from apps.materials.models import Material, PurchaseOrder
from apps.sites.models import Site


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ["code", "name", "unit", "category", "work_type", "is_active"]

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )


class PurchaseOrderForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrder
        fields = ["site", "supplier", "order_date", "status"]
        widgets = {
            "order_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["site"].queryset = Site.unscoped.filter(company=company)
            self.fields["supplier"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )

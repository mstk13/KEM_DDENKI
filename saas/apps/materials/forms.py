from django import forms

from apps.masters.models import Supplier, WorkType
from apps.materials.models import (
    Delivery,
    Material,
    PurchaseOrder,
    Quotation,
)
from apps.sites.models import Site


class MaterialForm(forms.ModelForm):
    class Meta:
        model = Material
        fields = ["code", "name", "unit", "category", "standard_price", "work_type", "is_active"]
        widgets = {
            "standard_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

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
        fields = ["site", "supplier", "quotation", "order_date", "status", "file"]
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
            self.fields["quotation"].queryset = Quotation.unscoped.filter(company=company)
            self.fields["quotation"].required = False
            self.fields["file"].required = False


class QuotationForm(forms.ModelForm):
    class Meta:
        model = Quotation
        fields = [
            "site", "supplier", "quotation_date", "valid_until", "total_amount",
            "status", "file", "notes",
        ]
        widgets = {
            "quotation_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "valid_until": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "total_amount": forms.NumberInput(attrs={"class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
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
            self.fields["site"].required = False
            self.fields["file"].required = False


class DeliveryForm(forms.ModelForm):
    class Meta:
        model = Delivery
        fields = ["delivery_date", "notes"]
        widgets = {
            "delivery_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

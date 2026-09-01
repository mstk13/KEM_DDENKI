from django import forms
from django.contrib.auth import get_user_model

from apps.masters.models import Supplier, WorkType
from apps.materials.models import (
    Delivery,
    DeliveryItem,
    Material,
    MaterialSupplier,
    ProcurementRecord,
    PurchaseOrder,
    PurchaseOrderItem,
    Quotation,
    QuotationItem,
)
from apps.sites.models import Site

User = get_user_model()


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
        fields = [
            "site", "supplier", "quotation", "order_date", "delivery_date",
            "subject", "payment_terms", "notes", "ordered_by", "status", "file",
        ]
        widgets = {
            "order_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "delivery_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
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
            self.fields["quotation"].queryset = Quotation.unscoped.filter(company=company)
            self.fields["quotation"].required = False
            self.fields["file"].required = False
            self.fields["ordered_by"].queryset = User.objects.filter(
                company=company, is_active=True,
            )
            self.fields["ordered_by"].required = False


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


class QuotationItemForm(forms.ModelForm):
    class Meta:
        model = QuotationItem
        fields = ["material", "material_name", "quantity", "unit_price"]
        widgets = {
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["material"].queryset = Material.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["material"].required = False
        self.fields["material_name"].help_text = "マスタにない場合は自由入力"


class PurchaseOrderItemForm(forms.ModelForm):
    class Meta:
        model = PurchaseOrderItem
        fields = [
            "material", "material_name", "quantity", "unit",
            "unit_price", "tax_rate", "work_type",
        ]
        widgets = {
            "quantity": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "unit_price": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
            "tax_rate": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "value": "0.10"},
            ),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["material"].queryset = Material.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["material"].required = False
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["work_type"].required = False
        self.fields["material_name"].help_text = "マスタにない場合は自由入力"


class DeliveryItemForm(forms.ModelForm):
    class Meta:
        model = DeliveryItem
        fields = ["material", "ordered_qty", "delivered_qty", "is_ok"]
        widgets = {
            "ordered_qty": forms.NumberInput(
                attrs={"class": "form-control", "step": "0.01", "readonly": "readonly"}
            ),
            "delivered_qty": forms.NumberInput(attrs={"class": "form-control", "step": "0.01"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["material"].queryset = Material.unscoped.filter(
                company=company, is_active=True,
            )


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


class MaterialSupplierForm(forms.ModelForm):
    class Meta:
        model = MaterialSupplier
        fields = [
            "supplier", "supplier_code", "standard_unit_price",
            "lead_time_days", "min_order_qty", "is_preferred", "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["supplier"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.CheckboxInput)):
                field.widget.attrs.setdefault("class", "form-control")


class ProcurementRecordForm(forms.ModelForm):
    class Meta:
        model = ProcurementRecord
        fields = [
            "site", "material", "supplier", "ordered_date", "delivered_date",
            "ordered_qty", "delivered_qty", "unit_price_paid", "notes",
        ]
        widgets = {
            "ordered_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "delivered_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        if company:
            self.fields["site"].queryset = Site.unscoped.filter(company=company)
            self.fields["material"].queryset = Material.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["supplier"].queryset = Supplier.unscoped.filter(
                company=company, is_active=True,
            )
        for _name, field in self.fields.items():
            if not isinstance(field.widget, forms.Textarea):
                field.widget.attrs.setdefault("class", "form-control")

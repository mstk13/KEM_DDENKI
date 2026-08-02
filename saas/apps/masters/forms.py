from django import forms

from apps.masters.models import Customer, Supplier


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["code", "name", "address", "is_active"]
        widgets = {
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["code", "name", "contact_info", "is_active"]
        widgets = {
            "contact_info": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

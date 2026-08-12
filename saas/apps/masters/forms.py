from django import forms

from apps.masters.models import Customer, Supplier


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = [
            "code", "name", "representative", "contact_person",
            "phone", "fax", "email", "address", "payment_terms", "note", "is_active",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = [
            "code", "name", "representative", "contact_person",
            "phone", "fax", "email", "address", "note", "is_active",
        ]
        widgets = {
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "note": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

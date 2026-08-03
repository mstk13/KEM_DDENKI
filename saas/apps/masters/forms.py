from django import forms

from apps.masters.models import BusinessCard, Customer, Supplier, SupplierEvaluation


class CustomerForm(forms.ModelForm):
    class Meta:
        model = Customer
        fields = ["code", "name", "industry", "region", "scale", "address", "phone", "email", "is_active"]
        widgets = {
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class SupplierForm(forms.ModelForm):
    class Meta:
        model = Supplier
        fields = ["code", "name", "contact_info", "phone", "email", "is_active"]
        widgets = {
            "contact_info": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class SupplierEvaluationForm(forms.ModelForm):
    class Meta:
        model = SupplierEvaluation
        fields = ["evaluation_date", "price_rating", "delivery_rating", "quality_rating", "service_description", "notes"]
        widgets = {
            "evaluation_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "price_rating": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
            "delivery_rating": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
            "quality_rating": forms.NumberInput(attrs={"class": "form-control", "min": 1, "max": 5}),
            "service_description": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "notes": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")


class BusinessCardForm(forms.ModelForm):
    class Meta:
        model = BusinessCard
        fields = ["person_name", "position", "phone", "email", "image"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "form-control")

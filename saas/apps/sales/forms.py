from django import forms

from apps.sales.models import SalesVisit


class SalesVisitForm(forms.ModelForm):
    class Meta:
        model = SalesVisit
        fields = [
            "industry", "company_name", "rep_name",
            "business_overview", "sales_content",
            "phone", "email", "website", "address",
            "visit_date", "received_date",
            "status", "memo",
        ]
        widgets = {
            "visit_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "received_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "business_overview": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "sales_content": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")

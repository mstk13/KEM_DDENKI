from django import forms

from apps.accounts.models import User
from apps.masters.models import Customer
from apps.sites.models import Site


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = [
            "code", "name", "customer", "status",
            "contract_amount", "start_date", "end_date",
            "manager", "address",
        ]
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "end_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "address": forms.Textarea(attrs={"class": "form-control", "rows": 2}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            if not isinstance(field.widget, (forms.Textarea, forms.DateInput)):
                field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["customer"].queryset = Customer.unscoped.filter(
                company=company, is_active=True
            )
            self.fields["manager"].queryset = User.objects.filter(company=company)

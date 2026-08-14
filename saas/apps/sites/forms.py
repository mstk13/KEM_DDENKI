from django import forms

from apps.accounts.models import User
from apps.masters.models import Customer, WorkType
from apps.sites.models import Process, Site


class SiteForm(forms.ModelForm):
    class Meta:
        model = Site
        fields = [
            "code", "name", "customer", "status",
            "contract_amount", "start_date", "end_date",
            "manager", "estimator", "address",
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
            self.fields["estimator"].queryset = User.objects.filter(company=company)


class ProcessForm(forms.ModelForm):
    """現場の工程を手入力するためのフォーム。"""

    class Meta:
        model = Process
        fields = [
            "name", "work_type", "planned_start", "planned_end",
            "actual_start", "actual_end", "status", "display_order",
        ]
        widgets = {
            "planned_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "planned_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "actual_start": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "actual_end": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )

    def clean(self):
        cleaned = super().clean()
        for start_key, end_key, label in (
            ("planned_start", "planned_end", "計画"),
            ("actual_start", "actual_end", "実績"),
        ):
            start = cleaned.get(start_key)
            end = cleaned.get(end_key)
            if start and end and end < start:
                self.add_error(
                    end_key, f"{label}終了日は{label}開始日以降にしてください。"
                )
        return cleaned

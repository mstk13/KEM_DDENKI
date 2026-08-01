from django import forms

from apps.masters.models import WorkType
from apps.reports.models import DailyReport
from apps.sites.models import Process, Site
from apps.workers.models import Worker


class DailyReportForm(forms.ModelForm):
    class Meta:
        model = DailyReport
        fields = ["site", "worker", "report_date", "process", "work_type", "work_hours", "memo"]
        widgets = {
            "report_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "work_hours": forms.NumberInput(attrs={"class": "form-control", "step": "0.25"}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["site"].queryset = Site.unscoped.filter(company=company)
            self.fields["worker"].queryset = Worker.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["work_type"].queryset = WorkType.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["process"].queryset = Process.unscoped.filter(company=company)
            self.fields["process"].required = False

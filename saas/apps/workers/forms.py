from django import forms

from apps.workers.models import (
    HealthCheckup,
    JobTitle,
    Position,
    Worker,
    WorkerEvaluation,
    WorkerQualification,
)


class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = [
            "employee_code", "name", "name_kana", "job_title", "position",
            "phone", "hourly_cost", "hire_date", "is_active", "note", "discord_user_id",
        ]
        widgets = {
            "hire_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["job_title"].queryset = JobTitle.unscoped.filter(
                company=company, is_active=True,
            )
            self.fields["position"].queryset = Position.unscoped.filter(
                company=company, is_active=True,
            )


class WorkerQualificationForm(forms.ModelForm):
    class Meta:
        model = WorkerQualification
        fields = ["name", "category", "acquired_date", "expiry_date", "certificate_image", "note"]
        widgets = {
            "acquired_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "expiry_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class HealthCheckupForm(forms.ModelForm):
    class Meta:
        model = HealthCheckup
        fields = ["checkup_date", "result", "institution", "memo", "report_file"]
        widgets = {
            "checkup_date": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")


class EvaluationForm(forms.ModelForm):
    class Meta:
        model = WorkerEvaluation
        fields = ["worker", "period", "score", "comment"]
        widgets = {
            "comment": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
        }
        help_texts = {
            "period": "例: 2026-Q2, 2026年上期",
            "score": "1〜5 の整数",
        }

    def __init__(self, *args, company=None, **kwargs):
        super().__init__(*args, **kwargs)
        for _name, field in self.fields.items():
            field.widget.attrs.setdefault("class", "form-control")
        if company:
            self.fields["worker"].queryset = Worker.unscoped.filter(
                company=company, is_active=True,
            )

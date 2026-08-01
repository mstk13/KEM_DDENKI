from django import forms

from apps.workers.models import JobTitle, Position, Worker


class WorkerForm(forms.ModelForm):
    class Meta:
        model = Worker
        fields = ["name", "job_title", "position", "hourly_cost", "hire_date", "is_active"]
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
